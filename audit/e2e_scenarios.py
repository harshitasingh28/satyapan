"""End-to-end scenarios A to H through the real product path.

Data setup uses the shipped scripts: data/known_debunks.csv -> scripts/build_known_index.py.
The PIB store is seeded with ONE real release title and link obtained through a fetcher probe
on 31 Oct 2026, because the ingest job cannot reach PIB from the audit machine. Each scenario
records input, ground truth, tool calls, evidence, verdict and correctness.

Usage: python audit/e2e_scenarios.py --heldout-dir /path/to/opencv_images
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="satyapan_e2e_"))
os.environ["SATYAPAN_DATA_DIR"] = str(DATA)
os.environ.setdefault("SATYAPAN_RETRIES", "0")
if (ROOT / "tests" / "media" / "tessdata").exists():
    os.environ["TESSDATA_PREFIX"] = str(ROOT / "tests" / "media" / "tessdata")
sys.path.insert(0, str(ROOT))

from satyapan.pipeline.graph import Context, new_state, run, to_report  # noqa: E402

REAL_RELEASE = {"title": "Government Ensures Continuity of Telecom Connectivity amid Cyclone Arnab",
                "link": "https://pib.gov.in/PressReleaseIframePage.aspx?PRID=2330702", "summary": "",
                "note": "real PIB title and link, seeded manually from a fetcher probe on 31 Oct 2026"}
REAL_DEBUNK_TEXT = "The government has launched a scheme offering free laptops and is accepting applications for it."
REAL_DEBUNK_URL = "https://newsonair.gov.in/government-denies-launching-any-free-laptop-scheme-or-application-process/"


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def screenshot(src: Path, out: Path) -> Path:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    c = Image.new("RGB", (w + 80, h + 300), (236, 229, 221))
    c.paste(im, (40, 150))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, w + 80, 70], fill=(7, 94, 84))
    d.text((50, h + 180), "Forwarded many times", fill=(0, 0, 0))
    c.save(out, "JPEG", quality=70)
    return out


def tamper_c2pa(src: Path, out: Path) -> Path:
    data = bytearray(src.read_bytes())
    sos = data.rfind(b"\xff\xda")              # start of scan: image data begins after this
    for i in range(sos + 400, sos + 420):
        data[i] ^= 0x5A                       # change pixels, leave the manifest intact
    out.write_bytes(bytes(data))
    return out


def splice(src: Path, out: Path) -> Path:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    patch = im.crop((0, 0, w // 3, h // 3))
    im.paste(patch, (w // 2, h // 2))          # copy-move forgery, ground truth: manipulated
    im.save(out, "JPEG", quality=90)
    return out


def setup(heldout: Path, work: Path) -> dict:
    media = DATA / "known_media"
    media.mkdir(parents=True)
    shutil.copy(heldout / "butterfly.jpg", media / "butterfly.jpg")
    shutil.copy(heldout / "building.jpg", media / "building.jpg")
    shutil.copy(ROOT / "tests" / "media" / "audio" / "speech_a.ogg", media / "speech_a.ogg")
    for f in ("official_domains.txt", "factcheckers.txt"):
        shutil.copy(ROOT / "templates" / f, DATA / f)
    rows = [
        {"id": "KD-B", "claim_text": REAL_DEBUNK_TEXT, "debunk_url": REAL_DEBUNK_URL,
         "publisher": "All India Radio News (PIB Fact Check)", "date": "2026-04-27", "media_file": ""},
        {"id": "KD-E", "claim_text": "", "debunk_url": "https://factcheck.example/audit-image-debunk",
         "publisher": "Audit fixture debunk", "date": "2026-01-01", "media_file": "butterfly.jpg"},
        {"id": "KD-G", "claim_text": "", "debunk_url": "https://factcheck.example/audit-video-frame-debunk",
         "publisher": "Audit fixture debunk", "date": "2026-01-01", "media_file": "building.jpg"},
        {"id": "KD-H", "claim_text": "", "debunk_url": "https://factcheck.example/audit-audio-debunk",
         "publisher": "Audit fixture debunk", "date": "2026-01-01", "media_file": "speech_a.ogg"},
    ]
    with (DATA / "known_debunks.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_known_index.py")], capture_output=True,
                         text=True, env={**os.environ})
    from satyapan.sources.pib import PibStore
    PibStore(DATA / "pib_releases.jsonl").add([REAL_RELEASE])

    f = {}
    f["E_screenshot"] = screenshot(heldout / "butterfly.jpg", work / "butterfly_screenshot.jpg")
    im = Image.open(heldout / "butterfly.jpg").convert("RGB")
    im.crop((int(im.width * .4), int(im.height * .4), im.width, im.height)).save(work / "butterfly_crop.jpg", quality=60)
    f["E_offcentre_crop"] = work / "butterfly_crop.jpg"
    f["F_splice"] = splice(heldout / "fruits.jpg", work / "fruits_spliced.jpg")
    f["F_c2pa_tampered"] = tamper_c2pa(ROOT / "tests" / "media" / "c2pa" / "C.jpg", work / "C_tampered.jpg")
    slides = work / "slides"
    slides.mkdir()
    for i, name in enumerate(["apple.jpg", "building.jpg", "orange.jpg"]):
        Image.open(heldout / name).convert("RGB").resize((960, 540)).save(slides / f"s{i}.png")
    ff("-framerate", "1/4", "-i", str(slides / "s%d.png"), "-vf", "fps=25,format=yuv420p", "-c:v", "libx264",
       "-preset", "veryfast", "-b:v", "300k", str(work / "reused.mp4"))
    f["G_video"] = work / "reused.mp4"
    ff("-ss", "3", "-t", "6", "-i", str(ROOT / "tests" / "media" / "audio" / "speech_a.ogg"), "-c:a", "libopus",
       "-b:a", "16k", str(work / "speech_excerpt.ogg"))
    f["H_audio"] = work / "speech_excerpt.ogg"
    return {"files": f, "build_known_index_output": out.stdout.strip() + out.stderr.strip()[-300:]}


def scenarios(f: dict) -> list[dict]:
    puny = "uidaі.in".encode("idna").decode()           # Cyrillic і
    return [
        {"id": "A1", "input": {"text": f"{REAL_RELEASE['title']}. Read: {REAL_RELEASE['link']}"}, "truth": "TRUE",
         "acceptable": ["GENUINE"], "note": "official title plus the official link"},
        {"id": "A2", "input": {"text": "Govt says telecom connectivity will continue during Cyclone Arnab, networks are being restored"},
         "truth": "TRUE", "acceptable": ["GENUINE", "UNVERIFIED"], "note": "paraphrased forward, must not be FAKE"},
        {"id": "B1", "input": {"text": REAL_DEBUNK_TEXT}, "truth": "FALSE", "acceptable": ["FAKE"],
         "note": "debunk wording as reported by All India Radio (PIB Fact Check, 27 Apr 2026)"},
        {"id": "B2", "input": {"text": "Free laptop yojana launched by government, applications open now, apply today"},
         "truth": "FALSE", "acceptable": ["FAKE"], "note": "paraphrase of the same false claim"},
        {"id": "C1", "input": {"text": "From next month all bank ATMs in Visakhapatnam will close at 6 pm every day"},
         "truth": "UNRESOLVED", "acceptable": ["UNVERIFIED"], "note": "no fact-check exists"},
        {"id": "D1", "input": {"text": "PM Kisan: update KYC to receive Rs 6000 at https://pmkisan-gov.in.kyc-verify.top/login"},
         "truth": "FALSE", "acceptable": ["FAKE"], "note": "lookalike, official name inside another domain"},
        {"id": "D2", "input": {"text": f"UIDAI notice: download your e-Aadhaar now at https://{puny}/download"},
         "truth": "FALSE", "acceptable": ["FAKE"], "note": f"punycode homoglyph {puny}"},
        {"id": "D3", "input": {"text": "Government relief fund: claim Rs 5000 at https://bit.ly/3abcXYZ"}, "truth": "UNKNOWN",
         "acceptable": ["UNVERIFIED"], "note": "redirect target unknown without urlscan"},
        {"id": "D4", "input": {"text": "Government notice, read at http://testsafebrowsing.appspot.com/s/phishing.html"},
         "truth": "MALICIOUS_TEST_URL", "acceptable": ["FAKE"], "note": "Google's Safe Browsing test page"},
        {"id": "E1", "input": {"files": [f["E_screenshot"]]}, "truth": "REUSED_DEBUNKED_IMAGE", "acceptable": ["FAKE"],
         "note": "screenshot of an indexed debunked image"},
        {"id": "E2", "input": {"files": [f["E_offcentre_crop"]]}, "truth": "REUSED_DEBUNKED_IMAGE", "acceptable": ["FAKE"],
         "note": "off-centre crop (60%) of the indexed image"},
        {"id": "F1", "input": {"files": [f["F_splice"]]}, "truth": "MANIPULATED (copy-move)", "acceptable": ["UNVERIFIED"],
         "note": "manipulated image whose original is not indexed: the system has no manipulation detector"},
        {"id": "F2", "input": {"files": [f["F_c2pa_tampered"]]}, "truth": "MANIPULATED AFTER SIGNING", "acceptable": ["UNVERIFIED", "FAKE"],
         "note": "C2PA-signed file with pixels changed after signing", "expect_media": "credentials_invalid_reported"},
        {"id": "G1", "input": {"files": [f["G_video"]]}, "truth": "REUSED_DEBUNKED_FRAME", "acceptable": ["FAKE"],
         "note": "video containing an indexed debunked image as one scene"},
        {"id": "H1", "input": {"files": [f["H_audio"]]}, "truth": "REUSED_DEBUNKED_AUDIO", "acceptable": ["FAKE"],
         "note": "16 kbps Opus excerpt of indexed debunked audio"},
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout-dir", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "e2e_scenarios.json"))
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="satyapan_e2e_work_"))
    info = setup(Path(args.heldout_dir), work)
    print("build_known_index:", info["build_known_index_output"])
    ctx = Context.default()
    print(f"context: image index {'loaded' if ctx.image_index else 'MISSING'}, audio index "
          f"{'loaded' if ctx.audio_index else 'MISSING'}, known claims {len(ctx.known_claims)}, PIB releases {len(ctx.pib.load())}")
    rows = []
    for sc in scenarios(info["files"]):
        inp = sc["input"]
        st = run(new_state(text=inp.get("text", ""), media=[(p, p.name) for p in inp.get("files", [])]), ctx)
        rep = to_report(st)
        ok = rep.verdict in sc["acceptable"]
        media = rep.media_assessment
        cred_problem = None
        if sc.get("expect_media") == "credentials_invalid_reported":
            states = [e.data.get("validation_state") for e in rep.evidence if e.tool == "c2pa"]
            reported = any(e.tool == "c2pa" and e.stance == "contradicts" for e in rep.evidence)
            ok = ok and reported
            cred_problem = f"c2pa validation_state seen: {states}, reported as manipulation evidence: {reported}"
        rows.append({"id": sc["id"], "note": sc["note"], "input": {k: [str(x) for x in v] if isinstance(v, list) else v
                                                                    for k, v in inp.items()},
                     "ground_truth": sc["truth"], "acceptable": sc["acceptable"], "verdict": rep.verdict, "correct": ok,
                     "tool_calls": [(t.tool, t.status, t.ms) for t in rep.tool_runs],
                     "evidence": [{"id": e.id, "tool": e.tool, "stance": e.stance, "strength": e.strength,
                                   "source": e.source_url, "established": e.established} for e in rep.evidence],
                     "media_assessment": media, "reasons": [s.text for s in rep.reason], "c2pa_check": cred_problem,
                     "explanation": rep.strength_explanation})
        print(f"{'OK  ' if ok else 'FAIL'} {sc['id']:<3} truth={sc['truth']:<26} verdict={rep.verdict:<10} {sc['note'][:60]}")
        if cred_problem:
            print("        ", cred_problem)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"setup": info["build_known_index_output"], "scenarios": rows},
                                         ensure_ascii=False, indent=1, default=str))
    print(f"\n{sum(r['correct'] for r in rows)}/{len(rows)} scenarios correct. Saved {args.out}")
    sys.exit(0 if all(r["correct"] for r in rows) else 1)


if __name__ == "__main__":
    main()
