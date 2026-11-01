"""The investigation state graph.

validate_input -> extract_claims -> check_factchecks -> check_official -> investigate_links
  -> analyse_media -> rank_evidence -> [resolve_conflict, once, if strong evidence points both ways]
  -> decide -> write_report -> validate_citations

Nodes are plain functions state -> state, so the same graph runs with the tiny
runner below or with LangGraph (satyapan/pipeline/graph_langgraph.py). Every
node appends to state["trace"], which is what a UI would stream as the agent's
visible reasoning. Tool failures never crash the graph: they are recorded and
the verdict is made from whatever evidence remains.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rapidfuzz import fuzz

from satyapan.claims import amount_value, date_values, extract_claims, extract_urls, normalize, number_values
from satyapan.config import Settings, get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.hf import Embedder, cosine_top
from satyapan.http import ApiClient
from satyapan.logging_setup import redact
from satyapan.links import rdap, safebrowsing, urlscan
from satyapan.links.urlinfo import analyse_url, embedded_targets
from satyapan.llm import llm_extract_claims
from satyapan.media import c2pa_inspect, remote
from satyapan.media.audio import AudioIndex, voice_authenticity
from satyapan.media.image_index import ImageIndex
from satyapan.media.video import keyframes
from satyapan.models import Claim, Report, Statement, ToolRun
from satyapan.ocr import ocr_image
from satyapan.pipeline import checks as chk
from satyapan.pipeline.citations import validate
from satyapan.pipeline.compare import compare as ai_compare
from satyapan.pipeline.evidence import EvidenceLog, aggregate
from satyapan.pipeline.report import llm_rewrite, template_statements
from satyapan.pipeline.verdict import decide as decide_rules
from satyapan.security.ratelimit import DEFAULT_DAILY_BUDGET, DailyBudget
from satyapan.security.ssrf import validate_url
from satyapan.security.uploads import sanitized_image_copy, validate_upload
from satyapan.sources import factcheck
from satyapan.sources.official import domain_info
from satyapan.sources.pib import PibStore
from satyapan.sources.textindex import BM25, TOKEN_RE, tokenize

FC_MATCH, FC_POSSIBLE, KNOWN_MATCH = 85, 70, 85
# Embedding cosine above which a fact-check or release becomes a CANDIDATE for AI comparison.
# Provisional: set on the development split (eval/), never on the test split. A candidate is
# never evidence by itself.
SEMANTIC_CANDIDATE = float(os.environ.get("SATYAPAN_SEMANTIC_CANDIDATE", "0.80"))
NODE_LABELS = {"validate_input": "Checking the submission", "extract_claims": "Extracting claims",
               "check_factchecks": "Searching published fact-checks", "check_official": "Searching official releases",
               "investigate_links": "Checking links and domains", "analyse_media": "Analysing media provenance",
               "compare_evidence": "AI comparison of claim and evidence", "rank_evidence": "Ranking evidence",
               "resolve_conflict": "Resolving conflicting evidence", "decide": "Evidence gate decision",
               "write_report": "Writing the explanation", "validate_citations": "Checking every citation"}
_VECTOR_CACHE: dict = {}      # process-wide embedding cache (public corpus texts and fact-check texts)
# Strong: the link is built to look like a specific official site.
IMPERSONATION_FLAGS = {"official_name_inside_other_domain", "lookalike_of_official_domain",
                       "official_label_in_host", "official_name_in_userinfo"}
# Moderate: suspicious, but legitimate sites can show it too (mygov-style names, IDN domains).
WEAK_IMPERSONATION_FLAGS = {"gov_token_outside_gov_in", "official_label_fragment_in_host", "punycode_host",
                            "hidden_or_fullwidth_characters"}
# Calls to action that involve the link itself. "share" and "forward" do not.
LINK_CTAS = {"click", "apply now", "register", "claim now", "download", "kyc", "otp", "link below",
             "क्लिक", "आवेदन", "रजिस्टर", "लिंक", "క్లిక్", "దరఖాస్తు", "లింక్", "రిజిస్టర్"}
URL_RULES_KEY = "url_rules"   # all lexical link rules are ONE source: they count once
FAILED = {ToolStatus.AUTH_REQUIRED, ToolStatus.BLOCKED, ToolStatus.SERVICE_ERROR, ToolStatus.RATE_LIMITED}


def similarity(a: str, b: str) -> float:
    a, b = normalize(a).lower(), normalize(b).lower()
    return round((fuzz.token_set_ratio(a, b) + fuzz.token_sort_ratio(a, b)) / 2, 1)


@dataclass
class Context:
    client: ApiClient
    settings: Settings
    pib: PibStore
    known_claims: list[dict] = field(default_factory=list)
    image_index: ImageIndex | None = None
    audio_index: AudioIndex | None = None
    official_domains: set[str] = field(default_factory=set)
    factcheckers: set[str] = field(default_factory=set)
    budget: DailyBudget | None = None
    work_dir: Path = Path("data/work")
    run_urlscan: bool = False
    embedder: Embedder | None = None
    emit: Callable[[dict], None] | None = None     # receives live workflow events
    store: Any = None

    @classmethod
    def default(cls, client: ApiClient | None = None, store=None, emit=None) -> "Context":
        from satyapan.sources.official import load_allowlist
        s = get_settings()
        d = s.data_dir
        client = client or ApiClient(s)
        if store is not None:
            pib, known = store.pib_store(), store.known_claims()
        else:
            pib = PibStore(d / "pib_releases.jsonl")
            known = []
            if (d / "known_claims.jsonl").exists():
                import json
                known = [json.loads(ln) for ln in (d / "known_claims.jsonl").read_text(encoding="utf-8").splitlines() if ln]
        embedder = None
        if s.embeddings_configured:
            persist = getattr(store, "save_vectors", None) if store is not None else None
            if not _VECTOR_CACHE and store is not None and hasattr(store, "load_vectors"):
                try:
                    _VECTOR_CACHE.update(store.load_vectors(s.hf_embedding_model))
                except Exception:  # noqa: BLE001  a missing cache only costs extra embedding calls
                    pass
            embedder = Embedder(client, cache=_VECTOR_CACHE, persist=persist)
        limits = {**DEFAULT_DAILY_BUDGET, "hf_chat": s.daily_llm_calls, "hf_embeddings": s.daily_embedding_calls}
        return cls(client=client, settings=s, pib=pib, known_claims=known,
                   image_index=ImageIndex.load(d / "image_index") if (d / "image_index" / "index.json").exists() else None,
                   audio_index=AudioIndex.load(d / "audio_index") if (d / "audio_index" / "index.json").exists() else None,
                   official_domains=load_allowlist(_data_or_template(d, "official_domains.txt")),
                   factcheckers=load_allowlist(_data_or_template(d, "factcheckers.txt")),
                   budget=DailyBudget(d / "budget.json", limits), work_dir=d / "work",
                   embedder=embedder, emit=emit, store=store)


def _data_or_template(data_dir: Path, name: str) -> Path:
    """The operator's list in the data folder, else the shipped template.

    Before the audit fix a fresh install had EMPTY lists (nothing copies the templates), so
    rbi.org.in was not official and every fact-checker counted as unknown."""
    from satyapan.config import ROOT
    own = data_dir / name
    return own if own.exists() else ROOT / "templates" / name


def new_state(text: str = "", links: list[str] | None = None, media: list[tuple[Path, str]] | None = None,
              consent: dict | None = None) -> dict:
    return {"id": uuid.uuid4().hex[:12], "text": text or "", "user_links": links or [], "uploads": media or [],
            "consent": {"third_party_text": False, "third_party_links": False, "third_party_media": False,
                        **(consent or {})},
            "claims": [], "primary": None, "links": [], "media": [], "evidence": EvidenceLog(),
            "tool_runs": [], "trace": [], "failed_tools": [], "limitations": [], "media_assessment": {},
            "loops": 0, "agg": None, "verdict": None, "statements": [], "citation_problems": [], "report_mode": "template",
            "official_candidates": [], "fc_candidates": [], "flags": [],
            "ai": {"chat_model": None, "embedding_model": None, "extraction": "not_configured",
                   "comparison": "not_configured", "explanation": "not_configured", "problems": [], "pairs": []}}


def _run(state: dict, tool: str, target: str, fn, *args, local: bool = False, **kwargs):
    start = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
        status = ToolStatus.LOCAL_SUCCESS if local else ToolStatus.LIVE_SUCCESS
        detail = ""
    except ToolError as err:
        out, status, detail = None, err.status, redact(err.message)[:160]
    except subprocess.TimeoutExpired as err:
        out, status, detail = None, ToolStatus.SERVICE_ERROR, f"timed out after {err.timeout} s"
    except Exception as err:  # noqa: BLE001  a tool failure is recorded, never fatal for the investigation
        out, status, detail = None, ToolStatus.SERVICE_ERROR, redact(f"{type(err).__name__}: {str(err)[:140]}")
    state["tool_runs"].append(ToolRun(tool, status.value, target, round((time.perf_counter() - start) * 1000, 1), detail))
    if status in FAILED:
        state["failed_tools"].append(tool)
    return out


def _skip(state: dict, tool: str, target: str, status: ToolStatus, detail: str) -> None:
    state["tool_runs"].append(ToolRun(tool, status.value, target, 0.0, detail))


def _budget_ok(state: dict, ctx: Context, tool: str, target: str, configured: bool) -> bool:
    """Spend one unit of a paid tool's daily budget. Unconfigured tools are tried (they report
    AUTH_REQUIRED) without spending budget. A budget-file problem skips the tool, it never crashes."""
    if not configured or ctx.budget is None:
        return True
    try:
        if ctx.budget.take(tool):
            return True
        _skip(state, tool, target, ToolStatus.RATE_LIMITED, "daily budget for this tool is used up")
    except OSError as err:
        _skip(state, tool, target, ToolStatus.SERVICE_ERROR, f"budget file error: {type(err).__name__}")
    state["failed_tools"].append(tool)
    return False


def _semantic_ready(state: dict, ctx: Context) -> bool:
    return ctx.embedder is not None and state["consent"]["third_party_text"]


def _embed(state: dict, ctx: Context, texts: list[str], kind: str, target: str):
    """Embeddings through Hugging Face, recorded as a tool run. None when unavailable."""
    if not texts or not _semantic_ready(state, ctx):
        return None
    if not _budget_ok(state, ctx, "hf_embeddings", target, True):
        return None
    state["ai"]["embedding_model"] = ctx.settings.hf_embedding_model
    return _run(state, "hf_embeddings", target, ctx.embedder.embed, texts, kind)


def added_negations(message: str, release_text: str) -> list[str]:
    return sorted((set(TOKEN_RE.findall(_norm_for_match(message))) & NEGATIONS)
                  - set(TOKEN_RE.findall(_norm_for_match(release_text))))


def _emit(ctx: Context, state: dict, event: dict) -> None:
    if ctx.emit is None:
        return
    state["_seq"] = state.get("_seq", 0) + 1
    from satyapan.models import now_iso
    try:
        ctx.emit({"seq": state["_seq"], "ts": now_iso(), **event})
    except Exception:  # noqa: BLE001  a broken progress stream must not stop the investigation
        ctx.emit = None


# ---------------------------------------------------------------- nodes

def validate_input(state: dict, ctx: Context) -> dict:
    limit = ctx.settings.max_text_chars
    if len(state["text"]) > limit:
        # links after the cut are still checked: a scam link at the end of a long forward must not vanish
        tail_links = extract_urls(state["text"][limit:])
        state["user_links"] = list(state["user_links"]) + tail_links
        state["text"] = state["text"][:limit]
        state["limitations"].append(f"Text was truncated to {limit:,} characters for claim extraction"
                                    + (f". {len(tail_links)} link(s) after the cut were still checked." if tail_links else "."))
    for i, (path, name) in enumerate(state["uploads"][:4]):
        info = validate_upload(Path(path), name, ctx.settings)
        if info.ok:
            state["media"].append({"id": f"M{i + 1}", "path": Path(path), "name": name, "info": info})
        else:
            _skip(state, "upload_validation", name, ToolStatus.INPUT_ERROR, ", ".join(info.errors))
            state["limitations"].append(f"File {name} was rejected: {', '.join(info.errors)}.")
    return state


def extract(state: dict, ctx: Context) -> dict:
    claims: list[Claim] = extract_claims(state["text"]) if state["text"] else []
    for m in state["media"]:
        if m["info"].kind == "image":
            res = _run(state, "ocr_tesseract", m["id"], ocr_image, m["path"], ctx.settings.tesseract_langs, local=True)
            if res and res["ok"] and res["text"]:
                m["ocr_text"] = res["text"]
                claims += [Claim(**{**c.__dict__, "id": f"{m['id']}-{c.id}", "source": f"ocr:{m['id']}"})
                           for c in extract_claims(res["text"], source=f"ocr:{m['id']}", max_claims=2)]
            elif res and res["ok"] and res.get("low_confidence"):
                state["tool_runs"][-1].detail = (f"no confident text (mean confidence {res.get('mean_conf')}, "
                                                 f"{res.get('confident_words')} confident words), OCR text ignored")
                state["limitations"].append(f"OCR found no reliable text in {m['name']}, so no claim was read from it.")
            elif res and not res["ok"]:
                state["tool_runs"][-1].status = ToolStatus.NOT_TESTED.value
                state["tool_runs"][-1].detail = res["error"]
    ai = state["ai"]
    if state["text"] and ctx.settings.llm_configured and not state["consent"]["third_party_text"]:
        ai["extraction"] = "no_consent"
    if state["text"] and ctx.settings.llm_configured and state["consent"]["third_party_text"] \
            and _budget_ok(state, ctx, "hf_chat", "text", True):
        ai["chat_model"] = ctx.settings.llm_model
        res = _run(state, "llm_claims", "text", llm_extract_claims, ctx.client, state["text"])
        ai["extraction"] = "used" if res else f"failed: {state['tool_runs'][-1].status}"
        if res:
            kept, rejected = res
            claims += kept
            if rejected:
                state["limitations"].append(f"{len(rejected)} LLM-proposed claim(s) rejected: not found in the message.")
                ai["problems"] += [f"proposed claim not in the message: {r['quote'][:80]!r}" for r in rejected]
    state["claims"] = claims
    state["primary"] = max(claims, key=lambda c: c.checkworthiness) if claims else None
    links = list(state["user_links"])
    for c in claims:
        links += c.urls
    links = list(dict.fromkeys(links))[:10]
    for u in list(links):
        links += embedded_targets(u)       # where an open-redirect style link really sends people
    state["links"] = list(dict.fromkeys(links))[:12]
    return state


def check_factchecks(state: dict, ctx: Context) -> dict:
    claim: Claim | None = state["primary"]
    if not claim:
        _skip(state, "factcheck_search", "-", ToolStatus.SKIPPED_NOT_APPLICABLE, "no text claim")
        return state
    lang = claim.language if claim.language in ("en", "hi", "te") else None
    res = _run(state, "factcheck_search", claim.id, factcheck.search, ctx.client, claim.text[:300], language=lang)
    for rv in (res or {}).get("reviews", [])[:6]:
        sim = similarity(claim.text, rv["claim_text"])
        site = (rv.get("site") or "").lower()
        known_fc = site in ctx.factcheckers
        if rv["rating_class"] in ("false", "mixed") and sim >= FC_POSSIBLE:
            strength = ("strong" if known_fc else "moderate") if sim >= FC_MATCH else "weak"
            state["evidence"].add(
                tool="factcheck_search", source_name=f"{rv['publisher'] or site} (via Google Fact Check Tools)",
                source_url=rv["url"], target=claim.id, kind="fact_check", stance="contradicts", strength=strength,
                established=f"A fact-check rated a similar claim '{rv['rating']}' (text similarity {sim}/100).",
                independence_key=f"factcheck:{site}",
                limitations=["Similarity is lexical. The reviewed claim may differ in detail."] if sim < FC_MATCH else [],
                data={"similarity": sim, "rating": rv["rating"], "review_date": rv["review_date"],
                      "reviewed_claim": rv["claim_text"][:300]})
        elif rv["rating_class"] == "true" and sim >= FC_MATCH:
            state["evidence"].add(
                tool="factcheck_search", source_name=f"{rv['publisher'] or site} (via Google Fact Check Tools)",
                source_url=rv["url"], target=claim.id, kind="fact_check", stance="supports", strength="moderate",
                established=f"A fact-check rated a similar claim '{rv['rating']}' (text similarity {sim}/100).",
                independence_key=f"factcheck:{site}", data={"similarity": sim, "rating": rv["rating"]})
    if ctx.known_claims:
        def best_known():
            scored = [(similarity(claim.text, k["text"]), k) for k in ctx.known_claims]
            return max(scored, key=lambda x: x[0]) if scored else (0, None)
        score, item = _run(state, "known_claims_index", claim.id, best_known, local=True) or (0, None)
        if item and score >= KNOWN_MATCH:
            state["evidence"].add(
                tool="known_claims_index", source_name=item.get("publisher") or "Known debunk index",
                source_url=item.get("url"), target=claim.id, kind="fact_check", stance="contradicts", strength="strong",
                established=f"The claim matches a previously debunked claim (similarity {score}/100).",
                independence_key=f"known:{item.get('url')}", external=False,
                data={"similarity": score, "debunked_claim": item["text"][:300], "date": item.get("date")})
    _factcheck_candidates(state, ctx, claim, (res or {}).get("reviews", [])[:6])
    return state


def _factcheck_candidates(state: dict, ctx: Context, claim: Claim, reviews: list[dict]) -> None:
    """Reviews (and curated debunks) that may be the same claim in other words or another language.
    They become CANDIDATES for the AI comparison. They are not evidence."""
    cands = []
    for rv in reviews:
        if rv["rating_class"] not in ("false", "mixed"):
            continue
        lex = similarity(claim.text, rv["claim_text"])
        if lex < FC_MATCH:
            cands.append({"type": "reviewed_claim", "source": "factcheck", "text": rv["claim_text"][:900],
                          "review": rv, "lexical": lex})
    if _semantic_ready(state, ctx):
        for item in ctx.known_claims[:500]:
            lex = similarity(claim.text, item["text"])
            if lex < KNOWN_MATCH:
                cands.append({"type": "reviewed_claim", "source": "known", "text": item["text"][:900], "item": item,
                              "lexical": lex})
    if not cands:
        return
    q = _embed(state, ctx, [claim.text], "query", claim.id)
    vecs = _embed(state, ctx, [c["text"] for c in cands], "passage", "factcheck_texts") if q is not None else None
    if q is not None and vecs is not None:
        for c, score in zip(cands, vecs @ q[0]):
            c["cosine"] = round(float(score), 4)
    keep = [c for c in cands if c["lexical"] >= FC_POSSIBLE or c.get("cosine", 0) >= SEMANTIC_CANDIDATE]
    keep.sort(key=lambda c: max(c.get("cosine", 0), c["lexical"] / 100), reverse=True)
    for i, c in enumerate(keep[:3]):
        c["id"] = f"F{i + 1}"
    state["fc_candidates"] = keep[:3]


NEGATIONS = {"not", "no", "never", "nor", "cannot", "नहीं", "नही", "न", "मत", "కాదు", "లేదు", "వద్దు"}


def _norm_for_match(text: str) -> str:
    from satyapan.claims import URL_RE
    text = URL_RE.sub(" ", text).lower()
    text = re.sub(r"n['’]t\b", " not", text)                 # don't -> do not
    text = re.sub(r"(?<=\d),(?=\d)", "", text)               # 2,000 -> 2000
    return text.replace("₹", " rs ").replace("rs.", "rs ")


def title_confirmed(message: str, title: str, release_text: str) -> tuple[bool, list[str], list[str]]:
    """A release confirms a message only if EVERY content word of the release title is in the message
    and the message adds no negation the release does not have.

    Found on the team MacBook (31 Oct 2026): with 70% term overlap alone, a real title with one word
    swapped ("Lowest" to "Highest", "Uphold" to "Abandon", "will NOT celebrate") plus the real PIB
    link was GENUINE. Extra framing words in the message ("Read", "Share") are still allowed.
    """
    msg = set(tokenize(_norm_for_match(message)))
    missing = [t for t in tokenize(_norm_for_match(title)) if t not in msg]
    added_neg = sorted((set(TOKEN_RE.findall(_norm_for_match(message))) & NEGATIONS)
                       - set(TOKEN_RE.findall(_norm_for_match(release_text))))
    return (not missing and not added_neg), missing, added_neg


def check_official(state: dict, ctx: Context) -> dict:
    claim: Claim | None = state["primary"]
    if not claim:
        return state
    hits = _run(state, "pib_release_index", claim.id, ctx.pib.search, claim.text, 3, local=True) or []
    cands: list[dict] = []

    def add_cand(doc: dict, **info) -> None:
        for c in cands:
            if c["doc"]["link"] == doc["link"]:
                c.update({k: v for k, v in info.items() if v is not None})
                return
        cands.append({"type": "official_release", "text": f"{doc['title']} {doc.get('summary', '')}".strip()[:900],
                      "doc": doc, **info})

    if hits:
        top = hits[0]
        doc = top["doc"]
        text = f"{doc['title']} {doc.get('summary', '')}"
        # Exact numeric comparison: Rs 200 must not match a release that says Rs 2000.
        official_numbers = number_values(text)
        amounts_ok = all(amount_value(a) in official_numbers for a in claim.amounts if amount_value(a) is not None)
        # Dates too: a release saying 15 December must not confirm a message saying 15 November.
        dates_ok = date_values(claim.text) <= date_values(text)
        infos = [analyse_url(u, ctx.official_domains) for u in state["links"]]
        links_ok = all(i["official"] and "redirects_to_other_site" not in i["flags"] for i in infos)
        confirmed, title_missing, added_negation = title_confirmed(state["text"], doc["title"], text)
        specific = len(tokenize(_norm_for_match(doc["title"]))) >= 4    # the title words are the detail now
        prid = chk.prid_check(state["links"], doc["link"], ctx.pib)
        old = chk.outdated(state["text"], doc.get("published"))
        route1 = top["query_overlap"] >= 0.7 and amounts_ok and dates_ok and links_ok and confirmed and specific
        ev_id = None
        common = dict(tool="pib_release_index", source_name="Press Information Bureau release", source_url=doc["link"],
                      target=claim.id, kind="official_record", independence_key=f"official:{doc['link']}",
                      external=False, quote=doc["title"][:400], published_at=doc.get("published"))
        if route1 and prid["status"] == "mismatch":
            state["flags"].append("link_mismatch")
            state["evidence"].add(**common, stance="neutral", strength="none",
                established=(f"The text matches the official release '{doc['title'][:140]}', but the PIB link in the "
                             f"message points to a different release: '{prid['linked_title']}'."),
                limitations=["A real headline paired with the link of another release is a known way to make a "
                             "message look official."],
                data={"overlap": top["query_overlap"], "linked_prids": prid["prids"]})
        elif route1 and old["flag"]:
            state["flags"].append("outdated")
            state["evidence"].add(**common, stance="neutral", strength="none",
                established=(f"An official release matches: '{doc['title'][:140]}'. It was published on "
                             f"{old['published'][:10]} ({old['age_days']} days ago), but the message presents it as new "
                             f"({', '.join(old['phrases'][:3])})."),
                limitations=["Old official news forwarded as new can mislead even when every word is real."],
                data={"overlap": top["query_overlap"], "age_days": old["age_days"], "recency_words": old["phrases"]})
        elif route1:
            unknown_link = prid["status"] == "unknown"
            lims = []
            if unknown_link:
                lims.append(f"The PIB link in the message names release PRID={prid['prids'][0]}, which is not in "
                            f"Satyapan's index, so the link could not be checked.")
            if not old["date_known"]:
                lims.append("The release has no publication date in the index, so Satyapan cannot tell whether "
                            "this is old news.")
            ev = state["evidence"].add(**common, stance="supports", strength="moderate" if unknown_link else "strong",
                established=f"An official PIB release matches the claim ({int(top['query_overlap'] * 100)}% of claim terms, "
                            f"amounts and dates consistent, links official): '{doc['title'][:140]}'.",
                limitations=lims,
                data={"overlap": top["query_overlap"], "bm25": top["bm25"], "published": doc.get("published"),
                      "route": 1, "pib_link_check": prid["status"]})
            ev_id = ev.id
        elif top["query_overlap"] >= 0.5:
            state["evidence"].add(**common, stance="neutral", strength="none",
                established=f"A related official release exists: '{doc['title'][:140]}'. It does not confirm this message.",
                limitations=["Topic overlap is not confirmation. Amounts, links or details differ or are missing."],
                data={"overlap": top["query_overlap"], "amounts_consistent": amounts_ok, "dates_consistent": dates_ok,
                      "links_official": links_ok, "title_words_missing": title_missing[:8],
                      "negation_not_in_release": added_negation})
        add_cand(doc, route1_evidence=ev_id, lexical_overlap=top["query_overlap"])
    for p in chk.message_prids(state["links"]):
        linked = ctx.pib.by_prid(p)
        if linked:
            add_cand(linked, prid_identity=True)
    if _semantic_ready(state, ctx):
        docs = ctx.pib.load()[:5000]
        if docs:
            q = _embed(state, ctx, [claim.text], "query", claim.id)
            mat = _embed(state, ctx, [f"{d['title']} {d.get('summary', '')}" for d in docs], "passage", "pib_corpus") \
                if q is not None else None
            if q is not None and mat is not None:
                for i, score in cosine_top(q[0], mat, 3):
                    if score >= SEMANTIC_CANDIDATE:
                        add_cand(docs[i], cosine=score)
    for i, c in enumerate(cands[:3]):
        c["id"] = f"K{i + 1}"
    state["official_candidates"] = cands[:3]
    return state


def investigate_links(state: dict, ctx: Context) -> dict:
    claim: Claim | None = state["primary"]
    gov_claim = bool(claim and claim.entities)
    link_ctas = sorted(set(claim.calls_to_action) & LINK_CTAS) if claim else []
    public_links = []
    for url in state["links"]:
        info = _run(state, "url_analysis", url, analyse_url, url, ctx.official_domains, local=True)
        if not info:
            continue
        flags = set(info["flags"])
        if info["official"] and "redirects_to_other_site" in flags:
            targets = ", ".join(domain_info(t)["registered"] for t in info["embedded_targets"][:2])
            state["limitations"].append(f"{url} is on an official domain but carries a link onward to {targets}.")
            if gov_claim:
                state["evidence"].add(
                    tool="url_analysis", source_name="Official domain rule", source_url=None, target=url,
                    kind="link_risk", stance="contradicts", strength="moderate", external=False,
                    established=f"The link starts on {info['registered']} but carries a redirect to {targets}, "
                                f"which is a different site.",
                    independence_key=URL_RULES_KEY, data={"flags": info["flags"], "targets": info["embedded_targets"]},
                    limitations=["Official sites rarely link onward this way, but some do. The target is checked "
                                 "as its own link."])
        elif info["official"]:
            state["evidence"].add(
                tool="url_analysis", source_name="Official domain rule", source_url=None, target=url,
                kind="link_risk", stance="supports", strength="weak", external=False,
                established=f"{info['registered']} is an official government domain "
                            f"({'gov.in/nic.in' if info['official_suffix'] else 'operator allowlist'}).",
                independence_key=f"domain:{info['registered']}")
        elif gov_claim and IMPERSONATION_FLAGS & flags:
            state["evidence"].add(
                tool="url_analysis", source_name="Official domain rule", source_url=None, target=url,
                kind="link_risk", stance="contradicts", strength="strong", external=False,
                established=f"The message invokes {', '.join(claim.entities[:3])} but links to {info['registered']}, "
                            f"which is not an official domain and imitates one "
                            f"({', '.join(sorted(IMPERSONATION_FLAGS & flags))}).",
                independence_key=URL_RULES_KEY,
                data={"flags": info["flags"], "closest_official": info["closest_official"]})
        elif gov_claim and WEAK_IMPERSONATION_FLAGS & flags:
            state["evidence"].add(
                tool="url_analysis", source_name="Official domain rule", source_url=None, target=url,
                kind="link_risk", stance="contradicts", strength="moderate", external=False,
                established=f"The message invokes {', '.join(claim.entities[:3])} and links to {info['registered']}, "
                            f"which is not an official government domain "
                            f"({', '.join(sorted(WEAK_IMPERSONATION_FLAGS & flags))}).",
                independence_key=URL_RULES_KEY, data={"flags": info["flags"]},
                limitations=["Some genuine sites use 'gov' in a non-gov.in name. This alone is not proof."])
        elif gov_claim and link_ctas and "foreign_government_domain" not in flags:
            state["evidence"].add(
                tool="url_analysis", source_name="Official domain rule", source_url=None, target=url,
                kind="link_risk", stance="contradicts", strength="weak", external=False,
                established=f"The message asks readers to act ({', '.join(link_ctas[:2])}) through "
                            f"{info['registered']}, which is not an official government domain.",
                independence_key=URL_RULES_KEY, data={"flags": info["flags"]})
        if not info["valid_host"]:
            state["limitations"].append(f"Link {url} has an invalid host name and was not sent to any service.")
            continue
        check = validate_url(url)
        if not check.ok:
            state["limitations"].append(f"Link {url} was not sent to any service: {check.reason}.")
            continue
        public_links.append((info["url"], info))     # browser-normalised form is what services see
        if not info["official"]:
            r = _run(state, "rdap", info["registered"], rdap.lookup, ctx.client, info["registered"])
            if r and r.get("status") == "found" and r.get("age_days") is not None and r["age_days"] < 90:
                state["evidence"].add(
                    tool="rdap", source_name="Domain registry (RDAP)", source_url=None, target=url,
                    kind="link_risk", stance="contradicts", strength="weak",
                    established=f"{info['registered']} was registered {r['age_days']} days ago ({r['registered']}).",
                    independence_key=f"rdap:{info['registered']}", data=r)
            elif r and r.get("status") == "not_found":
                state["evidence"].add(
                    tool="rdap", source_name="Domain registry (RDAP)", source_url=None, target=url,
                    kind="link_risk", stance="contradicts", strength="weak",
                    established=f"{info['registered']} is not registered (the link is dead or invented).",
                    independence_key=f"rdap:{info['registered']}", data=r)
    if public_links:
        hits = _run(state, "safe_browsing", f"{len(public_links)} url(s)", safebrowsing.lookup, ctx.client,
                    [u for u, _ in public_links])
        for url, threats in ((hits or ({}, 0))[0]).items():
            state["evidence"].add(
                tool="safe_browsing", source_name="Google Safe Browsing (Advisory provided by Google)",
                source_url=None, target=url, kind="link_risk", stance="contradicts", strength="strong",
                established=f"Safe Browsing lists this URL for {', '.join(threats)}. This is an advisory, "
                            f"its accuracy is not guaranteed.",
                independence_key="safe_browsing", data={"threats": threats})
        for url, info in public_links:
            if info["official"]:
                continue
            if not (ctx.run_urlscan and state["consent"]["third_party_links"]):
                _skip(state, "urlscan", url, ToolStatus.SKIPPED_CONSENT if not state["consent"]["third_party_links"]
                      else ToolStatus.NOT_TESTED, "background sandbox scan not requested")
                continue
            sub = _run(state, "urlscan", url, urlscan.submit, ctx.client, url)
            if sub and sub["status"] == "submitted":
                done = _run(state, "urlscan_result", url, urlscan.wait, ctx.client, sub["uuid"])
                if done and done.get("status") == "done" and urlscan.summarize(done["result"]).get("malicious"):
                    state["evidence"].add(
                        tool="urlscan", source_name="urlscan.io", source_url=f"https://urlscan.io/result/{sub['uuid']}/",
                        target=url, kind="link_risk", stance="contradicts", strength="strong",
                        established="urlscan.io's overall verdict marks this page malicious.",
                        independence_key="urlscan", data=urlscan.summarize(done["result"]))
    return state


def _image_checks(state: dict, ctx: Context, media_id: str, path: Path, remote_ok: bool) -> dict:
    out = {"provenance": "NO_MATCH_IN_INDEX" if ctx.image_index else "INDEX_EMPTY", "tier": "unknown_provenance",
           "matches": []}
    if ctx.image_index:
        matches = _run(state, "known_media_index", media_id, ctx.image_index.query, path, local=True) or []
        for m in matches[:2]:
            t = m.get("tier", "similar_scene")
            meta = m.get("meta", {})
            out["matches"].append({"known_id": m["id"], "tier": t, "publisher": meta.get("publisher"),
                                   "source_url": meta.get("source_url"), "claim": meta.get("claim"),
                                   "phash_distance": m.get("phash_dist"), "inliers": (m.get("orb") or {}).get("inliers"),
                                   "overlap_similarity": (m.get("orb") or {}).get("sim_share")})
            common = dict(tool="known_media_index", source_name=meta.get("publisher", "Known debunk index"),
                          source_url=meta.get("source_url"), target=media_id, kind="provenance", external=False,
                          independence_key=f"known_media:{meta.get('source_url') or m['id']}",
                          data={k: m.get(k) for k in ("phash_dist", "dhash_dist", "crop_scale", "orb", "tier")})
            if t in ("exact_duplicate", "modified_duplicate"):
                out["provenance"] = "MATCHES_DEBUNKED_MEDIA"
                out["tier"] = "possible_reuse"
                state["evidence"].add(**common, stance="contradicts", strength="strong",
                    established=(f"This image is {'an exact' if t == 'exact_duplicate' else 'a cropped, resized or '
                                 'screenshotted'} copy of media from a debunked item {m['id']} (method {m.get('method')})."),
                    limitations=["A match shows the media was reused. It does not by itself show the pixels were altered."])
            else:
                out.setdefault("similar_scene", True)
                state["evidence"].add(**common, stance="neutral", strength="none",
                    established=(f"This image looks like a similar scene to debunked item {m['id']}, but the geometry "
                                 f"shows it is not a copy of the same photo. Not counted as evidence."),
                    limitations=["Different photos of the same place or object look alike. Similarity alone "
                                 "never makes a message fake."])
    if not remote_ok:
        return out
    clean = _run(state, "sanitize_copy", media_id, sanitized_image_copy, path, ctx.work_dir / state["id"], local=True)
    if clean is None:
        return out
    if _budget_ok(state, ctx, "cloud_vision_web", media_id, remote.vision_configured(ctx.settings)):
        web = _run(state, "cloud_vision_web", media_id, remote.web_detection, ctx.client, clean)
        if web:
            fc_pages = [p for p in web["pages"] if any(f in (p["url"] or "") for f in ctx.factcheckers)]
            if fc_pages:
                state["evidence"].add(
                    tool="cloud_vision_web", source_name="Google Cloud Vision (web detection)",
                    source_url=fc_pages[0]["url"], target=media_id, kind="provenance", stance="contradicts",
                    strength="moderate", established="This image appears on a fact-checker's page.",
                    independence_key=f"web_factcheck:{fc_pages[0]['url']}", data={"pages": fc_pages[:3]})
            elif web["pages"]:
                state["evidence"].add(
                    tool="cloud_vision_web", source_name="Google Cloud Vision (web detection)",
                    source_url=web["pages"][0]["url"], target=media_id, kind="provenance", stance="neutral",
                    strength="none", established=f"The image appears on {len(web['pages'])} other web page(s).",
                    independence_key="web_pages", data={"pages": web["pages"][:5]},
                    limitations=["Web Detection shows where an image appears, not when. Dates need human review."])
            out["web_pages"] = len(web["pages"])
    if _budget_ok(state, ctx, "sightengine_genai", media_id, remote.sightengine_configured(ctx.settings)):
        se = _run(state, "sightengine_genai", media_id, remote.sightengine_genai, ctx.client, clean)
        if se and se["score"] is not None:
            calibrated = ctx.settings.ai_image_detector_calibrated
            high = se["score"] >= 0.9
            state["evidence"].add(
                tool="sightengine_genai", source_name="Sightengine AI-image detector", source_url=None, target=media_id,
                kind="synthetic_signal", stance="contradicts" if (high and calibrated) else "neutral",
                strength="weak" if (high and calibrated) else "none",
                # An uncalibrated score is not a probability. It is kept for calibration work only and
                # is never shown as a number a reader could take as "x% AI".
                established=(f"AI-generation score {se['score']:.2f} from a detector calibrated on our test set."
                             if calibrated else "An AI-image detector was run. Its score is not shown because the "
                             "detector has not passed calibration on forwarded images."),
                independence_key="ai_detector",
                data={**se, "calibrated": calibrated} if calibrated else
                     {"calibrated": False, "raw_score_for_calibration_only": se["score"]},
                limitations=["Detector scores are unreliable on compressed or unseen-generator images."])
            out["synthetic_signal"] = round(se["score"], 3) if calibrated else "NOT_CALIBRATED"
    return out


def analyse_media(state: dict, ctx: Context) -> dict:
    remote_ok = state["consent"]["third_party_media"]
    for m in state["media"]:
        mid, path, kind = m["id"], m["path"], m["info"].kind
        assess: dict = {"kind": kind, "name": m["name"], "manipulation": "NOT_ASSESSED"}
        if kind in ("image", "video"):
            cred = _run(state, "c2pa", mid, c2pa_inspect.inspect, path, local=True) or {"status": "error"}
            assess["credentials"] = cred["status"]
            if cred.get("status") == "present" and cred.get("validation_state") == "Invalid":
                assess["manipulation"] = "CREDENTIALS_INVALID"
                state["evidence"].add(
                    tool="c2pa", source_name="C2PA Content Credentials", source_url=None, target=mid,
                    kind="credentials", stance="contradicts", strength="moderate", external=False,
                    established=(f"Content Credentials signed by {cred.get('issuer')} fail validation "
                                 f"({', '.join(c for c in cred.get('validation_codes', []) if c) or 'Invalid'}): "
                                 f"the file was changed after it was signed."),
                    independence_key="c2pa", data=cred,
                    limitations=["Invalid credentials show the bytes changed after signing. They do not show "
                                 "what changed or whether the change is misleading."])
            elif cred.get("status") == "present" and cred.get("validation_state") == "Trusted":
                assess["tier"] = "verified_provenance"
            if cred.get("status") == "present" and cred.get("validation_state") != "Invalid":
                state["evidence"].add(
                    tool="c2pa", source_name="C2PA Content Credentials", source_url=None, target=mid,
                    kind="credentials", stance="contradicts" if cred.get("ai_declared") else "neutral",
                    strength="moderate" if cred.get("ai_declared") else "none", external=False,
                    established=(f"Content Credentials signed by {cred.get('issuer')} "
                                 f"({cred.get('validation_state')}), AI declared: {cred.get('ai_declared')}."),
                    independence_key="c2pa", data=cred,
                    limitations=["An AI-generated picture can still illustrate a true statement."])
        if kind == "image":
            checks = _image_checks(state, ctx, mid, path, remote_ok)
            if assess.get("tier") == "verified_provenance" and checks.get("tier") == "unknown_provenance":
                checks.pop("tier")
            assess.update(checks)
        elif kind == "video":
            frames = _run(state, "video_keyframes", mid, keyframes, path, ctx.work_dir / state["id"] / mid, local=True)
            assess["frames"] = len(frames["frames"]) if frames else 0
            for i, frame in enumerate((frames or {}).get("frames", [])[:4]):
                sub = _image_checks(state, ctx, f"{mid}-frame{i}", frame, remote_ok and i < 2)
                if sub.get("provenance") == "MATCHES_DEBUNKED_MEDIA":
                    assess["provenance"] = "MATCHES_DEBUNKED_MEDIA"
            assess.setdefault("provenance", "NO_MATCH_IN_INDEX" if ctx.image_index else "INDEX_EMPTY")
            assess["deepfake"] = "NOT_ASSESSED"
            state["limitations"].append("Video was checked for reuse through keyframes. Face swaps and "
                                        "lip-sync edits are not detected.")
        elif kind == "audio":
            if ctx.audio_index:
                matches = _run(state, "audio_fingerprint", mid, ctx.audio_index.query, path, local=True) or []
                for m2 in [x for x in matches if x["match"]][:1]:
                    assess["provenance"] = "MATCHES_DEBUNKED_AUDIO"
                    state["evidence"].add(
                        tool="audio_fingerprint", source_name=m2["meta"].get("publisher", "Known debunk index"),
                        source_url=m2["meta"].get("source_url"), target=mid, kind="provenance", stance="contradicts",
                        strength="strong", external=False,
                        established=f"This audio matches debunked audio {m2['id']} ({m2['aligned_hits']} aligned hashes).",
                        independence_key=f"known_audio:{m2['meta'].get('source_url') or m2['id']}", data=m2)
            va = voice_authenticity(path)
            assess["voice_authenticity"] = va["status"]
            state["limitations"].append(va["limitation"])
        state["media_assessment"][mid] = assess
    if state["media"]:
        state["limitations"].append("Missing Content Credentials prove nothing: messaging apps strip them.")
    if state["media"] and not remote_ok:
        state["limitations"].append("Third-party media checks were skipped because consent was not given.")
    return state


def compare_evidence(state: dict, ctx: Context) -> dict:
    """AI comparison of the main claim with the official and fact-check candidates, checked in code."""
    claim: Claim | None = state["primary"]
    ai = state["ai"]
    cands = state["official_candidates"] + state["fc_candidates"]
    if not claim:
        ai["comparison"] = "not_applicable"
        return state
    if not ctx.settings.llm_configured:
        if cands:
            _skip(state, "ai_comparison", claim.id, ToolStatus.NOT_TESTED, "HF_TOKEN / HF_CHAT_MODEL not configured")
        ai["comparison"] = "not_configured"
        return state
    if not state["consent"]["third_party_text"]:
        if cands:
            _skip(state, "ai_comparison", claim.id, ToolStatus.SKIPPED_CONSENT, "no consent to send text to the AI model")
        ai["comparison"] = "no_consent"
        return state
    if not cands:
        ai["comparison"] = "no_candidates"
        return state
    if not _budget_ok(state, ctx, "hf_chat", claim.id, True):
        ai["comparison"] = "failed: RATE_LIMITED"
        return state
    res = _run(state, "ai_comparison", claim.id, ai_compare, ctx.client, claim.text, cands)
    if not res:
        ai["comparison"] = f"failed: {state['tool_runs'][-1].status}"
        state["limitations"].append("The AI comparison was unavailable, so the verdict rests on code checks only.")
        return state
    ai["comparison"], ai["chat_model"] = "used", res["model"]
    ai["problems"] += res["problems"]
    by_id = {e.id: e for e in state["evidence"].items}
    infos = [analyse_url(u, ctx.official_domains) for u in state["links"]]
    links_ok = all(i["official"] and "redirects_to_other_site" not in i["flags"] for i in infos)
    for c in cands:
        pr = res["pairs"].get(c["id"]) or {"verified": False}
        src = c.get("doc", {}).get("link") or (c.get("review") or {}).get("url") or (c.get("item") or {}).get("url")
        ai["pairs"].append({"candidate": c["id"], "type": c["type"], "source_url": src, "text": c["text"][:200],
                            "cosine": c.get("cosine"), **{k: pr.get(k) for k in
                            ("relation", "same_subject", "evidence_quote", "claim_quote", "verified", "problem")}})
        if c["type"] == "official_release":
            _apply_official(state, ctx, claim, c, pr, by_id, links_ok)
        else:
            _apply_factcheck(state, ctx, claim, c, pr)
    return state


def _apply_official(state: dict, ctx: Context, claim: Claim, c: dict, pr: dict, by_id: dict, links_ok: bool) -> None:
    doc, text = c["doc"], c["text"]
    verified = pr.get("verified")
    supports = bool(verified and pr["relation"] == "supports" and pr["same_subject"])
    common = dict(tool="pib_release_index", source_name="Press Information Bureau release", source_url=doc["link"],
                  target=claim.id, kind="official_record", independence_key=f"official:{doc['link']}", external=False,
                  published_at=doc.get("published"), origin="ai_comparison")
    if c.get("route1_evidence"):                         # Route 1 already matched: the AI may only veto
        e = by_id.get(c["route1_evidence"])
        if e is None:
            return
        if verified and not supports:
            e.strength = "moderate"
            e.limitations.append(
                f"The AI comparison did not confirm that this release supports the message "
                f"({pr['relation']}{'' if pr['same_subject'] else ', different subject'}): \"{pr['evidence_quote'][:160]}\"")
            state["flags"].append("ai_veto")
        elif supports:
            e.data["ai_confirmed"] = True
        return
    facts = chk.facts_compatible(state["text"], text)
    neg = added_negations(state["text"], text)
    old = chk.outdated(state["text"], doc.get("published"))
    if c.get("prid_identity") and "link_mismatch" not in state["flags"]:
        if supports and facts["ok"] and not neg and links_ok and not old["flag"]:      # Route 2
            lims = ["The message wording differs from the release title. The AI comparison found the same facts, "
                    "and code checked the quotes, numbers, dates, negation and links."]
            if not old["date_known"]:
                lims.append("The release has no publication date in the index, so Satyapan cannot tell whether "
                            "this is old news.")
            state["evidence"].add(**common, stance="supports", strength="strong", quote=pr["evidence_quote"],
                established=(f"The message links the official PIB release '{doc['title'][:140]}' and states the same "
                             f"facts in different words. Quoted from the release: \"{pr['evidence_quote'][:200]}\""),
                limitations=lims,
                data={"route": 2, "prid": doc.get("prid"), "ai_relation": "supports", "facts": facts,
                      "claim_quote": pr["claim_quote"]})
        else:
            reasons = []
            if not supports:
                reasons.append("the AI comparison did not find the same facts" if verified else
                               "the AI comparison gave no usable answer")
            if not facts["ok"]:
                reasons.append("numbers or dates in the message are not in the release "
                               f"({', '.join(facts['missing_numbers'] + facts['missing_dates'])})")
            if neg:
                reasons.append(f"the message adds a negation the release does not have ({', '.join(neg)})")
            if not links_ok:
                reasons.append("the message also contains links that are not official")
            if old["flag"]:
                reasons.append(f"the release is from {old['published'][:10]} but the message presents it as new")
                state["flags"].append("outdated")
            state["evidence"].add(**common, stance="neutral", strength="none", quote=doc["title"][:400],
                established=(f"The message links the official PIB release '{doc['title'][:140]}', but it is not "
                             f"confirmed: {'; '.join(reasons) or 'checks did not pass'}.".replace(";", ",")),
                data={"route": 2, "prid": doc.get("prid"), "facts": facts, "negation_not_in_release": neg})
        return
    if supports and facts["ok"] and not neg:
        state["evidence"].add(**common, stance="neutral", strength="none", quote=pr["evidence_quote"],
            established=(f"This looks like the official release '{doc['title'][:140]}' in other words or another "
                         f"language. It is not counted as confirmation because the message does not link this release."),
            limitations=["A paraphrase without a link to the specific release can also be a distortion."],
            data={"ai_relation": "supports", "cosine": c.get("cosine"), "facts": facts})


def _apply_factcheck(state: dict, ctx: Context, claim: Claim, c: dict, pr: dict) -> None:
    if not (pr.get("verified") and pr["relation"] == "supports" and pr["same_subject"]):
        return
    conflict = chk.facts_conflict(claim.text, c["text"])
    rv, item = c.get("review"), c.get("item")
    if conflict["conflict"]:
        state["evidence"].add(
            tool="factcheck_search" if rv else "known_claims_index", origin="ai_comparison",
            source_name=(rv or {}).get("publisher") or (item or {}).get("publisher") or "Fact-check",
            source_url=(rv or {}).get("url") or (item or {}).get("url"), target=claim.id, kind="fact_check",
            stance="neutral", strength="none", independence_key=f"semantic:{(rv or item or {}).get('url')}",
            established="A fact-check reviewed a similar claim, but its numbers or dates differ from this message.",
            data={"conflict": conflict, "reviewed_claim": c["text"][:300]})
        return
    how = (f"matched by AI comparison with quotes verified in both texts"
           f"{f', embedding similarity {c.get("cosine"):.2f}' if c.get('cosine') else ''}"
           f", text similarity {c['lexical']:.0f}/100, and their numbers and dates do not conflict")
    if rv:
        site = (rv.get("site") or "").lower()
        strength = "strong" if (site in ctx.factcheckers and rv["rating_class"] == "false") else "moderate"
        state["evidence"].add(
            tool="factcheck_search", origin="ai_comparison",
            source_name=f"{rv.get('publisher') or site} (via Google Fact Check Tools)", source_url=rv["url"],
            target=claim.id, kind="fact_check", stance="contradicts", strength=strength,
            quote=pr["evidence_quote"], published_at=rv.get("review_date"),
            established=f"A fact-check rated this claim '{rv['rating']}'. The message makes the same claim: {how}.",
            independence_key=f"factcheck:{site}",
            limitations=["The match between the message and the reviewed claim was made by an AI model and "
                         "checked in code. Open the fact-check to confirm."],
            data={"rating": rv["rating"], "review_date": rv.get("review_date"), "reviewed_claim": c["text"][:300],
                  "similarity": c["lexical"], "cosine": c.get("cosine"), "claim_quote": pr["claim_quote"]})
    elif item:
        state["evidence"].add(
            tool="known_claims_index", origin="ai_comparison", source_name=item.get("publisher") or "Known debunk index",
            source_url=item.get("url"), target=claim.id, kind="fact_check", stance="contradicts", strength="strong",
            quote=pr["evidence_quote"], published_at=item.get("date"), external=False,
            established=f"The claim matches a previously debunked claim: {how}.",
            independence_key=f"known:{item.get('url')}",
            limitations=["The match was made by an AI model and checked in code. Open the debunk to confirm."],
            data={"debunked_claim": c["text"][:300], "similarity": c["lexical"], "cosine": c.get("cosine")})


def rank(state: dict, ctx: Context) -> dict:
    state["agg"] = aggregate(state["evidence"].items)
    return state


def route_after_rank(state: dict) -> str:
    return "resolve_conflict" if state["agg"]["conflict"] and state["loops"] == 0 else "decide"


def resolve_conflict(state: dict, ctx: Context) -> dict:
    """Self-correction: demand stricter matches before giving up."""
    state["loops"] += 1
    changed = []
    for e in state["evidence"].items:
        if e.tool == "factcheck_search" and e.strength == "strong" and e.data.get("similarity", 0) < 90:
            e.strength = "moderate"
            changed.append(f"{e.id}: fact-check match below 90 downgraded")
        if e.tool == "pib_release_index" and e.stance == "supports" and e.data.get("overlap", 0) < 0.85:
            e.strength = "moderate"
            changed.append(f"{e.id}: official match below 85% overlap downgraded")
    state["trace"].append({"node": "resolve_conflict_detail", "changes": changed or ["no change"]})
    state["agg"] = aggregate(state["evidence"].items)
    return state


FLAG_TEXT = {"link_mismatch": " The PIB link in the message points to a different release than the one its text matches.",
             "outdated": " An official release matches, but it is old news presented as new.",
             "ai_veto": " The AI comparison did not confirm that the matched release supports the message, so it "
                        "was not counted as confirmation."}


def decide(state: dict, ctx: Context) -> dict:
    v = decide_rules(state["agg"], state["evidence"].items, state["failed_tools"])
    if v["label"] == "UNVERIFIED" and v["why"] == "insufficient":
        for flag in ("link_mismatch", "outdated", "ai_veto"):
            if flag in state["flags"]:
                v["why"] = flag
                v["explanation"] += FLAG_TEXT[flag]
                break
    state["verdict"] = v
    return state


def write_report(state: dict, ctx: Context) -> dict:
    """Template statements (copied from evidence) always. A validated AI explanation is added to them."""
    v = state["verdict"]
    ai = state["ai"]
    state["statements"] = template_statements(state["evidence"].items, v["basis"])
    if ctx.settings.llm_configured and not state["consent"]["third_party_text"]:
        ai["explanation"] = "no_consent"
    elif ctx.settings.llm_configured and not state["statements"]:
        ai["explanation"] = "nothing_to_explain"
    elif ctx.settings.llm_configured and _budget_ok(state, ctx, "hf_chat", "report", True):
        lang = state["primary"].language if state["primary"] else "en"
        start = time.perf_counter()
        rewritten, problems, mode = llm_rewrite(ctx.client, state["statements"], state["evidence"].items,
                                                v["label"], lang)
        failed = next((p["problem"] for p in problems if str(p.get("problem", "")).startswith("LLM unavailable")), None)
        status = failed.split(": ", 1)[1] if failed else ToolStatus.LIVE_SUCCESS.value
        state["tool_runs"].append(ToolRun("ai_explanation", status, "report",
                                          round((time.perf_counter() - start) * 1000, 1), failed or ""))
        if failed and status in {x.value for x in FAILED}:
            state["failed_tools"].append("ai_explanation")
        state["citation_problems"] += problems
        state["report_mode"] = ai["explanation"] = mode
        if mode == "llm_validated":
            for st in rewritten:
                st.kind = "ai_explanation"
            state["statements"] = state["statements"] + rewritten
    return state


TOOL_NAMES = {"factcheck_search": "Google Fact Check search", "safe_browsing": "Google Safe Browsing",
              "rdap": "Domain registration lookup (RDAP)", "hf_embeddings": "Multilingual embeddings",
              "llm_claims": "AI claim extraction", "ai_comparison": "AI evidence comparison",
              "ai_explanation": "AI explanation", "urlscan": "urlscan.io", "cloud_vision_web": "Google Cloud Vision",
              "sightengine_genai": "Sightengine", "wikidata": "Wikidata"}


def validate_citations(state: dict, ctx: Context) -> dict:
    v = state["verdict"]
    kept, problems = validate(state["statements"], state["evidence"].items, v["label"])
    state["citation_problems"] = state["citation_problems"] + problems
    if v["label"] != "UNVERIFIED" and not kept:
        v.update(label="UNVERIFIED", why="uncited", explanation=v["explanation"] + " No statement survived citation checks.")
    # Every statement in the report cites evidence. Unavailable tools are listed from tool_runs
    # and limitations instead, so the report never mixes a missing source into the reasons.
    state["statements"] = kept
    return state


NODES = {"validate_input": validate_input, "extract_claims": extract, "check_factchecks": check_factchecks,
         "check_official": check_official, "investigate_links": investigate_links, "analyse_media": analyse_media,
         "compare_evidence": compare_evidence,
         "rank_evidence": rank, "resolve_conflict": resolve_conflict, "decide": decide,
         "write_report": write_report, "validate_citations": validate_citations}
LINEAR = ["validate_input", "extract_claims", "check_factchecks", "check_official", "investigate_links",
          "analyse_media", "compare_evidence", "rank_evidence"]
TAIL = ["decide", "write_report", "validate_citations"]


def traced(name: str, ctx: Context):
    def node(state: dict) -> dict:
        from dataclasses import asdict
        label = NODE_LABELS.get(name, name.replace("_", " ").capitalize())
        _emit(ctx, state, {"node": name, "phase": "start", "label": label})
        start = time.perf_counter()
        runs_before, ev_before = len(state["tool_runs"]), len(state["evidence"].items)
        state = NODES[name](state, ctx)
        ms = round((time.perf_counter() - start) * 1000, 1)
        new_runs = state["tool_runs"][runs_before:]
        new_ev = [e.id for e in state["evidence"].items[ev_before:]]
        state["trace"].append({"node": name, "ms": ms, "tool_runs": [f"{r.tool}:{r.status}" for r in new_runs],
                               "new_evidence": new_ev})
        _emit(ctx, state, {"node": name, "phase": "end", "label": label, "ms": ms,
                           "tool_runs": [asdict(r) for r in new_runs], "new_evidence": new_ev})
        return state
    return node


def run(state: dict, ctx: Context) -> dict:
    for name in LINEAR:
        state = traced(name, ctx)(state)
    if route_after_rank(state) == "resolve_conflict":
        state = traced("resolve_conflict", ctx)(state)
    for name in TAIL:
        state = traced(name, ctx)(state)
    return state


def to_report(state: dict) -> Report:
    v = state["verdict"]
    claim = state["primary"] or Claim(id="C0", text="(no text claim found, media only)", source="none", language="unknown")
    for run_ in state["tool_runs"]:
        if run_.status in {s.value for s in FAILED}:
            state["limitations"].append(f"{run_.tool} was unavailable ({run_.status}), so its evidence is missing.")
    if v["label"] != "FAKE":
        state["limitations"].append("Not finding a fact-check does not mean a claim is true.")
    ai = dict(state["ai"])
    ai["chat_model"] = ai.get("chat_model") or (state["ai"]["chat_model"] if ai.get("comparison") == "used" else None)
    return Report(investigation_id=state["id"], claim=claim, verdict=v["label"],
                  strength_explanation=f"{v['explanation']} Evidence strength: {v['strength']}.",
                  reason=state["statements"], evidence=state["evidence"].items, media_assessment=state["media_assessment"],
                  limitations=list(dict.fromkeys(state["limitations"])), tool_runs=state["tool_runs"], trace=state["trace"],
                  claims=list(state["claims"]), verdict_reason=v["why"], evidence_strength=v["strength"], ai=ai)
