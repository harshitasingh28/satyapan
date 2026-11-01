"""Regression tests for the bugs found in the end-to-end audit (docs/FINAL_TEST_AUDIT.md, section K).

Each test names the audit finding it guards. All are offline. Fixtures marked FIXTURE are
test data for matching logic, not evaluation data.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from conftest import MEDIA, ROOT, need
from satyapan.errors import ToolError, ToolStatus
from satyapan.links.urlinfo import analyse_url
from satyapan.models import Evidence, Statement
from satyapan.pipeline.citations import validate
from satyapan.pipeline.graph import Context, _run, new_state, run, to_report
from satyapan.sources.official import domain_info
from satyapan.sources.pib import PibStore

OFFICIAL = {"pib.gov.in", "pmkisan.gov.in", "uidai.gov.in", "mygov.in"}


def ctx_for(client, tmp: Path, **kw) -> Context:
    from satyapan.config import get_settings
    return Context(client=client, settings=get_settings(), pib=PibStore(tmp / "pib.jsonl"),
                   official_domains=OFFICIAL, work_dir=tmp / "work", **kw)


# K1: gov-token heuristic accused genuine and foreign government sites -------------------------

def test_k1_foreign_government_and_mygov_are_not_impersonation(offline_client, tmp_dir):
    a = analyse_url("https://travel.state.gov/content/travel.html", OFFICIAL)
    assert "foreign_government_domain" in a["flags"] and "gov_token_outside_gov_in" not in a["flags"]
    assert analyse_url("https://www.mygov.in/quiz", OFFICIAL)["official"]
    for text in ("US government publishes a travel advisory for India at https://travel.state.gov/content/travel.html",
                 "Government of India invites citizens to the quiz at https://www.mygov.in/quiz"):
        assert to_report(run(new_state(text=text), ctx_for(offline_client, tmp_dir))).verdict != "FAKE"


def test_k1_specific_impersonation_is_still_strong(offline_client, tmp_dir):
    for url in ("http://pmkisan-gov.top/apply", "https://uidai.gov.in.verify-kyc.top/x", "https://pmkisam.in/",
                "https://pib.gov.in@evil-relief.top/claim", "http://x.com\\@pib.gov.in/verify"):
        st = run(new_state(text=f"PM Kisan Yojana: Rs 6000 for farmers, register at {url}"),
                 ctx_for(offline_client, tmp_dir))
        assert to_report(st).verdict == "FAKE", url


# K2: "share" was a call to action, and every link counted as a separate source ----------------

def test_k2_news_links_with_share_are_not_fake(offline_client, tmp_dir):
    text = ("Government announces PM Kisan instalment for farmers. Read and share: "
            "https://www.thehindu.com/news/a.ece https://indianexpress.com/article/b/")
    rep = to_report(run(new_state(text=text), ctx_for(offline_client, tmp_dir)))
    assert rep.verdict != "FAKE"


def test_k2_lexical_link_rules_count_once(offline_client, tmp_dir):
    text = "Government scheme: register now at http://relief-gov.top/a and http://help-gov.xyz/b"
    st = run(new_state(text=text), ctx_for(offline_client, tmp_dir))
    lexical = [e for e in st["evidence"].items if e.tool == "url_analysis" and e.stance == "contradicts"]
    assert len(lexical) == 2 and len({e.independence_key for e in lexical}) == 1
    assert st["agg"]["contradicts"]["score"] == 2 and to_report(st).verdict == "UNVERIFIED"


# K3: amounts matched as substrings (Rs 200 confirmed by a Rs 2000 release) ---------------------

def test_k3_amounts_compared_exactly(offline_client, tmp_dir):
    from satyapan.claims import amount_value, number_values
    assert amount_value("Rs 2,000") == 2000 and amount_value("2 lakh") == 200000
    assert 200 not in number_values("FIXTURE PM Kisan instalment of Rs 2000 released")
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "PM Kisan 21st instalment of Rs 2000 released to farmers",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=900001", "summary": ""}])
    bad = run(new_state(text="PM Kisan 21st instalment of Rs 200 released to farmers. Check pmkisan.gov.in"), ctx)
    assert to_report(bad).verdict != "GENUINE"
    good = run(new_state(text="PM Kisan 21st instalment of Rs 2,000 released to farmers. Check pmkisan.gov.in"), ctx)
    assert to_report(good).verdict == "GENUINE"


# K4: an LLM rewrite could contradict the verdict and still pass the citation check -------------

def test_k4_citation_rejects_verdict_contradicting_and_ungrounded_statements():
    e = Evidence(id="E1", tool="url_analysis", source_name="Official domain rule", source_url=None, target="u",
                 kind="link_risk", stance="contradicts", strength="strong",
                 established="The message invokes pib but links to pib-relief.top, which is not an official domain.",
                 independence_key="url_rules")
    kept, problems = validate([
        Statement("This message is genuine and safe to share with everyone", ["E1"]),
        Statement("Farmers across the nation celebrate the generous festival bonus", ["E1"]),
        Statement("The link goes to pib-relief.top, which is not an official domain", ["E1"]),
    ], [e], "FAKE")
    assert [s.text for s in kept] == ["The link goes to pib-relief.top, which is not an official domain"]
    assert {p["problem"] for p in problems} == {"wording disagrees with the FAKE verdict",
                                                "statement is not grounded in the cited evidence"}


def test_k4_rating_words_from_the_evidence_are_allowed():
    e = Evidence(id="E1", tool="factcheck_search", source_name="Factly", source_url="https://factly.in/x",
                 target="C1", kind="fact_check", stance="contradicts", strength="strong",
                 established="A fact-check rated a similar claim 'False' (text similarity 92/100).",
                 independence_key="factcheck:factly.in")
    kept, _ = validate([Statement("Factly rated a similar claim False", ["E1"])], [e], "FAKE")
    assert kept


# K5: C2PA credentials that failed validation were reported as neutral --------------------------

def test_k5_invalid_content_credentials_are_evidence(offline_client, tmp_dir):
    src = need(MEDIA / "c2pa" / "C.jpg")
    data = bytearray(src.read_bytes())
    sos = data.rfind(b"\xff\xda")
    for i in range(sos + 400, sos + 420):
        data[i] ^= 0x5A
    tampered = tmp_dir / "tampered.jpg"
    tampered.write_bytes(bytes(data))
    ctx = ctx_for(offline_client, tmp_dir)
    st = run(new_state(media=[(tampered, "tampered.jpg")]), ctx)
    ev = [e for e in st["evidence"].items if e.tool == "c2pa"]
    assert ev and ev[0].stance == "contradicts" and ev[0].strength == "moderate"
    assert st["media_assessment"]["M1"]["manipulation"] == "CREDENTIALS_INVALID"
    st2 = run(new_state(media=[(src, "C.jpg")]), ctx)
    assert all(e.stance == "neutral" for e in st2["evidence"].items if e.tool == "c2pa")


# K6: the audio index was built but never saved, so audio reuse was never detected --------------

def test_k6_audio_index_save_and_load(tmp_dir):
    from satyapan.media.audio import AudioIndex
    speech = need(MEDIA / "audio" / "speech_a.ogg")
    idx = AudioIndex()
    idx.add("A", speech, source_url="https://factcheck.example/a")
    idx.save(tmp_dir / "audio_index")
    loaded = AudioIndex.load(tmp_dir / "audio_index")
    r1, r2 = idx.query(speech)[0], loaded.query(speech)[0]
    assert r2["match"] and r1["aligned_hits"] == r2["aligned_hits"] and r2["meta"]["source_url"]


# K7: API keys echoed by a service leaked into the stored report --------------------------------

def test_k7_tool_errors_are_redacted(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "SECRETKEY123456")
    err = ToolError(ToolStatus.SERVICE_ERROR, "bad request for https://x.googleapis.com/v4/a?key=SECRETKEY123456 "
                                              "echo SECRETKEY123456")
    assert "SECRETKEY123456" not in err.message and "SECRETKEY123456" not in str(err)
    state = new_state()

    def boom():
        raise RuntimeError("upstream said SECRETKEY123456")
    _run(state, "x", "-", boom)
    assert "SECRETKEY123456" not in state["tool_runs"][0].detail


# K8: DailyBudget raced (JSONDecodeError) when several investigations ran at once ---------------

def test_k8_budget_is_exact_under_threads_and_survives_corruption(tmp_dir):
    from satyapan.security.ratelimit import DailyBudget
    path = tmp_dir / "budget.json"
    granted, errors = [], []

    def worker():
        b = DailyBudget(path, {"tool": 20})
        for _ in range(5):
            try:
                granted.append(b.take("tool"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sum(granted) == 20
    path.write_text("{not json")
    assert DailyBudget(path, {"tool": 1}).take("tool") is True


# K9: a subprocess timeout (OCR under load) crashed the whole investigation ---------------------

def test_k9_subprocess_timeout_is_a_tool_failure_not_a_crash():
    state = new_state()

    def slow():
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=30)
    assert _run(state, "ocr_tesseract", "M1", slow, local=True) is None
    assert state["tool_runs"][0].status == "SERVICE_ERROR" and "timed out" in state["tool_runs"][0].detail


def test_k9_ocr_ignores_photos_without_text():
    from satyapan.ocr import available_languages, ocr_image
    if "eng" not in available_languages():
        pytest.skip("tesseract eng data not available")
    res = ocr_image(need(MEDIA / "images" / "chelsea.png"), "eng")
    assert res["ok"] and res["low_confidence"] and res["text"] == ""


def test_k9_ocr_keeps_a_caption_next_to_a_photo(tmp_dir):
    """A whole-image mean-confidence gate dropped captions when the photo part was large.
    The line-level gate keeps confident lines and drops photo junk."""
    from PIL import ImageDraw, ImageFont
    from satyapan.ocr import available_languages, ocr_image
    if "eng" not in available_languages():
        pytest.skip("tesseract eng data not available")
    font = need(MEDIA / "fonts" / "NotoSansDevanagari.ttf")
    photo = Image.open(need(MEDIA / "images" / "coffee.png")).convert("RGB")
    canvas = Image.new("RGB", (photo.width + 40, photo.height + 120), (236, 229, 221))
    canvas.paste(photo, (20, 20))
    ImageDraw.Draw(canvas).text((20, photo.height + 40), "PIB: Government gives Rs 5000 to every family, register now",
                                font=ImageFont.truetype(str(font), 22), fill="black")
    path = tmp_dir / "caption.jpg"
    canvas.save(path, quality=80)
    res = ocr_image(path, "eng")
    assert not res["low_confidence"] and "Government gives Rs 5000" in res["text"]


# K10: upload limits ----------------------------------------------------------------------------

def test_k10_pixel_limit_between_one_and_two_times(tmp_dir):
    from satyapan.security.uploads import validate_upload
    p = tmp_dir / "60mp.png"
    Image.new("1", (8000, 7500)).save(p, "PNG")
    info = validate_upload(p, "60mp.png")
    assert not info.ok and "pixel limit" in info.errors[0]


def test_k10_api_requires_and_enforces_content_length(monkeypatch):
    from fastapi.testclient import TestClient
    import satyapan.api.app as api
    client = TestClient(api.app)
    api.bucket._state.clear()
    r = client.post("/v1/investigations", content=iter([b"text=hello"]),
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 411
    monkeypatch.setattr(api, "MAX_REQUEST", 100)
    r = client.post("/v1/investigations", data={"text": "x" * 500})
    assert r.status_code == 413
    api.bucket._state.clear()


# K11: retention was never enforced and did not cover investigation records ---------------------

def test_k11_sweep_covers_investigation_records(tmp_dir):
    from satyapan.storage import Store
    st = Store(tmp_dir)
    st.save("old1", {"status": "done"})
    st.save("new1", {"status": "done"})
    old = time.time() - 48 * 3600
    os.utime(tmp_dir / "investigations" / "old1.json", (old, old))
    assert st.sweep(retention_hours=24) == 1
    assert st.load("old1") is None and st.load("new1") is not None


# K12: crafted host names reached the RDAP request path -----------------------------------------

def test_k12_crafted_hosts_are_invalid_and_never_official(offline_client):
    from satyapan.links import rdap
    info = domain_info("http://evil%2F..%2Fpib.gov.in/")
    assert not info["valid_host"] and not info["official_suffix"]
    with pytest.raises(ToolError) as exc:
        rdap.lookup(offline_client, "evil%2f..%2fadmin.com")
    assert exc.value.status == ToolStatus.INPUT_ERROR
    assert domain_info("http://x.com\\@pib.gov.in/")["registered"] == "x.com"


# K13: a 180.02 s file was rejected by a 180 s limit --------------------------------------------

def test_k13_duration_limit_has_a_tolerance(tmp_dir):
    from satyapan.security.uploads import validate_upload
    p = tmp_dir / "a.ogg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=300:sample_rate=8000:duration=180.2", "-c:a", "libopus", "-b:a", "8k", str(p)],
                   check=True)
    assert validate_upload(p, "a.ogg").ok


# K14: the dataset validator missed near-duplicate leakage --------------------------------------

def test_k14_validator_flags_near_duplicate_images_and_claims(tmp_dir, images):
    sys.path.insert(0, str(ROOT / "eval"))
    from validate_manifest import near_duplicates
    media = tmp_dir / "media"
    media.mkdir()
    Image.open(images[0]).convert("RGB").save(media / "dev.jpg", "JPEG")
    Image.open(images[0]).convert("RGB").resize((200, 150)).save(media / "test.jpg", "JPEG", quality=60)
    rows = [{"sample_id": "D1", "split": "dev", "input_file": "dev.jpg", "claim_text": "Free laptops for all students",
             "notes": ""},
            {"sample_id": "T1", "split": "test", "input_file": "test.jpg",
             "claim_text": "Free laptops for all the students!", "notes": ""}]
    problems = near_duplicates(rows, media)
    assert any("image" in p for p in problems) and any("claim text" in p for p in problems)
    rows[1]["notes"] = "leak-reviewed"
    assert near_duplicates(rows, media) == []


# K15: reason statements were not ordered by strength -------------------------------------------

def test_k15_statements_strongest_first():
    from satyapan.pipeline.report import template_statements
    evs = [Evidence(id=f"E{i}", tool="t", source_name="S", source_url=None, target="x", kind="k", stance="contradicts",
                    strength=s, established=f"fact {i}", independence_key=f"k{i}")
           for i, s in ((1, "weak"), (2, "strong"), (10, "moderate"))]
    out = template_statements(evs, ["E1", "E2", "E10"])
    assert [s.evidence_ids[0] for s in out] == ["E2", "E10", "E1"]


# K16: a fresh install loaded EMPTY allowlists (templates were never copied into data/) ---------

def test_k16_default_context_falls_back_to_shipped_lists(tmp_dir, monkeypatch):
    from satyapan.config import get_settings
    monkeypatch.setenv("SATYAPAN_DATA_DIR", str(tmp_dir / "fresh"))
    get_settings.cache_clear()
    try:
        ctx = Context.default()
        assert "rbi.org.in" in ctx.official_domains and ctx.factcheckers
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# K17: an UNCALIBRATED AI-detector score was shown as a number (reads like "97% AI") ------------

def test_k17_uncalibrated_detector_score_is_not_presented(tmp_dir, monkeypatch, images):
    """Mocked transport: the Sightengine reply below is a FIXTURE, not a live response."""
    import httpx
    from satyapan.config import get_settings
    from satyapan.http import ApiClient
    monkeypatch.setenv("SIGHTENGINE_USER", "fixtureuser")
    monkeypatch.setenv("SIGHTENGINE_SECRET", "fixturesecret")
    get_settings.cache_clear()
    try:
        def fake(request: httpx.Request):
            if request.url.host == "api.sightengine.com":
                return httpx.Response(200, json={"status": "success", "type": {"ai_generated": 0.97},
                                                 "request": {"operations": 5}})
            raise httpx.ConnectError("offline", request=request)
        client = ApiClient(get_settings(), transport=httpx.MockTransport(fake))
        st = run(new_state(media=[(images[0], images[0].name)], consent={"third_party_media": True}),
                 ctx_for(client, tmp_dir))
        rep = to_report(st)
        ev = [e for e in rep.evidence if e.tool == "sightengine_genai"]
        assert ev and ev[0].stance == "neutral" and "0.97" not in ev[0].established
        assert rep.media_assessment["M1"]["synthetic_signal"] == "NOT_CALIBRATED"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# K18 to K22 were found by an INDEPENDENT tester that never saw the cases above or the code
# (audit/independent_adversarial.py). Inputs below are that tester's cases.

# K18: a Devanagari danda after a URL became part of the host, so a genuine Hindi message was FAKE

def test_k18_danda_after_url_is_punctuation(offline_client, tmp_dir):
    from satyapan.claims import extract_urls
    text = "प्रधानमंत्री किसान सम्मान निधि की 21वीं किस्त जारी कर दी गई है। लाभार्थी अपनी स्थिति यहाँ देखें https://pmkisan.gov.in।"
    assert extract_urls(text) == ["https://pmkisan.gov.in"]
    assert to_report(run(new_state(text=text), ctx_for(offline_client, tmp_dir))).verdict != "FAKE"
    assert not domain_info("https://pmkisan.gov.in।/")["valid_host"]


# K19: zero-width and full-width characters hid an official name inside a scam host

def test_k19_invisible_and_fullwidth_characters_are_normalised(offline_client, tmp_dir):
    for text in ("PM Kisan: Rs 6,000 extra benefit for registered farmers. Register before 5 November: "
                 "http://pmki​san.gov.in.benefit-claim.top/register",
                 "UIDAI alert: your Aadhaar will be deactivated in 24 hours. Update KYC now: "
                 "https://uidai．gov．in．kyc-update．top/login"):
        rep = to_report(run(new_state(text=text), ctx_for(offline_client, tmp_dir)))
        assert rep.verdict == "FAKE", text
    a = analyse_url("http://pmki​san.gov.in.benefit-claim.top/register", OFFICIAL)
    assert "hidden_or_fullwidth_characters" in a["flags"] and "official_name_inside_other_domain" in a["flags"]


# K20: text was cut at 5,000 characters BEFORE links were read, so a link at the end vanished

def test_k20_links_survive_text_truncation(offline_client, tmp_dir):
    text = "Government of India scheme update for all citizens. " * 1150 + \
           "Claim your PM Kisan bonus now: https://pmkisan.gov.in.bonus-claim.top/apply"
    st = run(new_state(text=text), ctx_for(offline_client, tmp_dir))
    assert "https://pmkisan.gov.in.bonus-claim.top/apply" in st["links"]
    assert to_report(st).verdict == "FAKE"


# K21: dates were not compared, so a release saying December "confirmed" a message saying November

def test_k21_dates_must_agree_for_official_support(offline_client, tmp_dir):
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "CBDT extends due date for filing income tax returns to 15 December 2026",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100002", "summary": ""}])
    bad = "CBDT extends due date for filing income tax returns to 15 November 2026. File at https://www.incometax.gov.in"
    good = "CBDT extends due date for filing income tax returns to 15 December 2026. File at https://www.incometax.gov.in"
    assert to_report(run(new_state(text=bad), ctx)).verdict != "GENUINE"
    assert to_report(run(new_state(text=good), ctx)).verdict == "GENUINE"


# K22: an open redirect on an official domain counted as an official link

def test_k22_redirect_parameter_on_official_domain_is_not_official(offline_client, tmp_dir):
    url = "https://uidai.gov.in/redirect?url=https%3A%2F%2Faadhaar-docs-update.top%2Flogin"
    a = analyse_url(url, OFFICIAL)
    assert "redirects_to_other_site" in a["flags"] and a["embedded_targets"] == ["https://aadhaar-docs-update.top/login"]
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "UIDAI extends free online Aadhaar document update facility till 14 December 2026",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100004", "summary": ""}])
    text = f"UIDAI extends free online Aadhaar document update facility till 14 December 2026. Update: {url}"
    st = run(new_state(text=text), ctx)
    assert to_report(st).verdict != "GENUINE"
    assert "https://aadhaar-docs-update.top/login" in st["links"]
    plain = "UIDAI extends free online Aadhaar document update facility till 14 December 2026. Update: https://uidai.gov.in/"
    assert to_report(run(new_state(text=plain), ctx)).verdict == "GENUINE"


# K23: "Rs 5 crore" was read as Rs 5 (the multiplier was dropped after a currency prefix)

def test_k23_lakh_and_crore_after_currency_prefix(offline_client, tmp_dir):
    from satyapan.claims import AMOUNT_RE, amount_value
    assert AMOUNT_RE.findall("cover of Rs 5 crore per family") == ["Rs 5 crore"]
    assert amount_value("Rs 5 crore") == 5e7 and amount_value("₹5 lakh") == 5e5
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "Ayushman Bharat PM-JAY health cover of Rs 5 lakh per family extended in 5 more states",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100001", "summary": ""}])
    bad = "Ayushman Bharat PM-JAY health cover of Rs 5 crore per family extended in 5 more states. https://pmjay.gov.in"
    good = "Ayushman Bharat PM-JAY health cover of Rs 5 lakh per family extended in 5 more states. https://pmjay.gov.in"
    assert to_report(run(new_state(text=bad), ctx)).verdict != "GENUINE"
    assert to_report(run(new_state(text=good), ctx)).verdict == "GENUINE"


# K24: one swapped word in a real release title still got GENUINE (found on the team MacBook)

@pytest.mark.parametrize("text,expected", [
    ("Delhi Records Lowest Average AQI for October in the Last Eight Years at 166. Read: {link}", "GENUINE"),
    ("Delhi Records Highest Average AQI for October in the Last Eight Years at 166. Read: {link}", "UNVERIFIED"),
    ("Delhi Records Average AQI for October in the Last Eight Years at 166. Share: {link}", "UNVERIFIED"),
    ("Delhi does not record Lowest Average AQI for October in the Last Eight Years at 166. {link}", "UNVERIFIED"),
    ("Breaking: Delhi records lowest average AQI for October in the last eight years at 166!! Share {link}", "GENUINE"),
])
def test_k24_every_title_word_and_no_added_negation(offline_client, tmp_dir, text, expected):
    link = "https://pib.gov.in/PressReleaseIframePage.aspx?PRID=2331001"
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "Delhi Records Lowest Average AQI for October in the Last Eight Years at 166",
                  "link": link, "summary": ""}])
    assert to_report(run(new_state(text=text.format(link=link)), ctx)).verdict == expected


def test_k24_number_and_currency_formats_still_confirm(offline_client, tmp_dir):
    ctx = ctx_for(offline_client, tmp_dir)
    ctx.pib.add([{"fixture": True, "title": "Union Government releases tax devolution of ₹1,09,019 crore to State Governments",
                  "link": "https://pib.gov.in/PressReleaseIframePage.aspx?PRID=2331028", "summary": ""}])
    text = ("Union Government releases tax devolution of Rs 109019 crore to State Governments. "
            "https://pib.gov.in/PressReleaseIframePage.aspx?PRID=2331028")
    assert to_report(run(new_state(text=text), ctx)).verdict == "GENUINE"
