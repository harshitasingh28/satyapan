"""Evidence ranking, verdict rules, citation validation and the full graph, offline.

The graph tests use an ApiClient whose network always fails. They prove the
pipeline degrades gracefully and decides only from evidence it actually has.
Release records below are TEST FIXTURES for matching logic, not evaluation data.
"""
from pathlib import Path

import pytest
from PIL import Image

from satyapan.models import Evidence, Statement
from satyapan.pipeline.citations import validate
from satyapan.pipeline.evidence import aggregate
from satyapan.pipeline.graph import Context, new_state, run, to_report
from satyapan.pipeline.verdict import decide
from satyapan.media.image_index import ImageIndex
from satyapan.sources.pib import PibStore


def ev(i, stance, strength, key, **kw):
    return Evidence(id=f"E{i}", tool="t", source_name="S", source_url=kw.get("url"), target="C1", kind="context",
                    stance=stance, strength=strength, established=kw.get("est", "x"), independence_key=key,
                    data=kw.get("data", {}))


def test_independence_counts_once():
    agg = aggregate([ev(1, "contradicts", "moderate", "pib"), ev(2, "contradicts", "strong", "pib"),
                     ev(3, "contradicts", "weak", "rdap")])
    assert agg["contradicts"]["score"] == 4 and agg["contradicts"]["groups"] == 2


@pytest.mark.parametrize("items,label", [
    ([("contradicts", "strong", "a")], "FAKE"),
    ([("contradicts", "moderate", "a"), ("contradicts", "weak", "b")], "FAKE"),
    ([("contradicts", "moderate", "a")], "UNVERIFIED"),
    ([("supports", "strong", "a")], "GENUINE"),
    ([("supports", "strong", "a"), ("contradicts", "weak", "b")], "UNVERIFIED"),
    ([("supports", "strong", "a"), ("contradicts", "strong", "b")], "UNVERIFIED"),
    ([], "UNVERIFIED"),
])
def test_verdict_rules(items, label):
    evs = [ev(i, s, st, k) for i, (s, st, k) in enumerate(items)]
    assert decide(aggregate(evs), evs, [])["label"] == label


def test_citation_validator():
    evidence = [ev(1, "contradicts", "strong", "a", url="https://factly.in/x", est="rated 'False' (similarity 91/100)"),
                ev(2, "supports", "weak", "b")]
    statements = [
        Statement("Factly rated it False, similarity 91 (https://factly.in/x)", ["E1"]),
        Statement("Rated false by 3 fact-checkers", ["E1"]),          # invented number
        Statement("See https://evil.example/proof", ["E1"]),          # invented link
        Statement("Official site", ["E2"]),                           # wrong stance for FAKE
        Statement("Something", ["E9"]),                               # unknown id
        Statement("Uncited claim", []),
    ]
    kept, problems = validate(statements, evidence, "FAKE")
    assert [s.text for s in kept] == [statements[0].text] and len(problems) == 5


def _ctx(client, tmp: Path, **kw) -> Context:
    from satyapan.config import get_settings
    return Context(client=client, settings=get_settings(), pib=PibStore(tmp / "pib.jsonl"),
                   official_domains={"pmkisan.gov.in", "pib.gov.in"}, work_dir=tmp / "work", **kw)


def test_graph_impersonation_is_fake_even_offline(offline_client, tmp_dir):
    st = run(new_state(text="PM Kisan Yojana: सभी किसानों को ₹10,000 मिलेंगे। Apply now at "
                            "http://pmkisan-gov.top/register"), _ctx(offline_client, tmp_dir))
    r = to_report(st)
    assert r.verdict == "FAKE" and r.reason and r.reason[0].evidence_ids
    assert any(t.status == "BLOCKED" or t.status == "AUTH_REQUIRED" for t in r.tool_runs)
    assert any("unavailable" in lim for lim in r.limitations)


def test_graph_genuine_needs_official_record(offline_client, tmp_dir):
    ctx = _ctx(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "PM Kisan 21st instalment of Rs 2000 released to farmers",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=1", "summary": ""}])
    st = run(new_state(text="PM Kisan 21st instalment of Rs 2000 released to farmers. Check pmkisan.gov.in"), ctx)
    assert to_report(st).verdict == "GENUINE"
    st2 = run(new_state(text="PM Kisan 21st instalment of Rs 9000 released to farmers. Check pmkisan.gov.in"), ctx)
    assert to_report(st2).verdict != "GENUINE"      # amount differs from the official record


def test_graph_nothing_found_is_unverified(offline_client, tmp_dir):
    r = to_report(run(new_state(text="The bridge in our town will close next week for repairs."),
                      _ctx(offline_client, tmp_dir)))
    assert r.verdict == "UNVERIFIED" and r.limitations


def test_graph_known_debunked_image(offline_client, tmp_dir, images):
    idx = ImageIndex()
    idx.add("DEBUNK-1", images[0], source_url="https://factcheck.example/debunk-1", publisher="Test fact-checker")
    shot = tmp_dir / "fwd.jpg"
    im = Image.open(images[0]).convert("RGB")
    im.crop((0, 0, int(im.width * 0.7), int(im.height * 0.7))).save(shot, "JPEG", quality=40)
    r = to_report(run(new_state(media=[(shot, "fwd.jpg")]), _ctx(offline_client, tmp_dir, image_index=idx)))
    assert r.verdict == "FAKE"
    assert r.media_assessment["M1"]["provenance"] == "MATCHES_DEBUNKED_MEDIA"
    assert r.media_assessment["M1"]["manipulation"] == "NOT_ASSESSED"


def test_graph_conflict_runs_self_correction(offline_client, tmp_dir):
    ctx = _ctx(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "Free laptop scheme for students Rs 25000 announced",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2", "summary": ""}])
    ctx.known_claims = [{"text": "Free laptop scheme for students Rs 25000 announced",
                         "url": "https://factcheck.example/laptop", "publisher": "Test fact-checker"}]
    st = run(new_state(text="Free laptop scheme for students Rs 25000 announced"), ctx)
    nodes = [t["node"] for t in st["trace"]]
    assert "resolve_conflict" in nodes and to_report(st).verdict == "UNVERIFIED"


def test_langgraph_runner_matches_plain_runner(offline_client, tmp_dir):
    pytest.importorskip("langgraph")
    from satyapan.pipeline.graph_langgraph import build
    text = "PM Kisan Yojana gives ₹10,000. Apply now at http://pmkisan-gov.top/register"
    plain = run(new_state(text=text), _ctx(offline_client, tmp_dir))
    graph = build(_ctx(offline_client, tmp_dir)).invoke(new_state(text=text))
    assert graph["verdict"]["label"] == plain["verdict"]["label"]
    assert [e.established for e in graph["evidence"].items] == [e.established for e in plain["evidence"].items]
