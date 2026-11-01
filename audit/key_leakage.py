"""Secret-leakage test with a LOCAL echoing service (labelled: mocked transport, no network).

A fake key is configured. Every external request is answered by a mock that echoes the
full request URL and body back in an HTTP 400 error, the way some APIs do. We then look
for the key anywhere a user or log reader could see it: the stored report, the client's
call records, and the JSON logs.
Usage: python audit/key_leakage.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KEY = "AUDITKEY1234567890abcdef"
SECRET = "AUDITSECRETzyx987654"
HFTOK = "hf_AUDITtoken0123456789abcdefXYZ"
MONGO = "mongodb+srv://satyapan:AUDITdbPassw0rd@cluster0.example.mongodb.net/?retryWrites=true"
CFTOK = "AUDITcloudflareTOKEN0123456789abcdef"


def main() -> None:
    os.environ.update({"GOOGLE_API_KEY": KEY, "SIGHTENGINE_USER": "audituser", "SIGHTENGINE_SECRET": SECRET,
                       "HF_TOKEN": HFTOK, "HF_CHAT_MODEL": "audit/model", "MONGODB_URI": MONGO, "SATYAPAN_STORE": "json",
                       "CLOUDFLARE_ACCOUNT_ID": "0123456789abcdef0123456789abcdef", "CLOUDFLARE_API_TOKEN": CFTOK,
                       "SATYAPAN_DATA_DIR": tempfile.mkdtemp(), "SATYAPAN_RETRIES": "0"})
    import httpx
    from satyapan.config import get_settings
    from satyapan.http import ApiClient
    from satyapan.logging_setup import RedactingJsonFormatter
    from satyapan.pipeline.graph import Context, new_state, run, to_report
    from satyapan.sources.pib import PibStore

    get_settings.cache_clear()
    s = get_settings()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(RedactingJsonFormatter())
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)

    def echo(request: httpx.Request):
        body = request.content.decode(errors="replace")[:400] if request.content else ""
        # a badly behaved service that echoes the key, the Authorization header and the body back
        return httpx.Response(400, text=f"bad request for {request.url} body={body} key={KEY} "
                                        f"auth={request.headers.get('authorization')}")

    client = ApiClient(s, transport=httpx.MockTransport(echo))
    tmp = Path(tempfile.mkdtemp())
    ctx = Context(client=client, settings=s, pib=PibStore(tmp / "p.jsonl"), official_domains={"pib.gov.in"},
                  work_dir=tmp / "w")
    st = run(new_state(text="PIB: free laptops for students, register at http://pib-laptop.top/apply",
                       consent={"third_party_text": True}), ctx)
    report = json.dumps(to_report(st).to_dict(), default=str)
    calls = json.dumps([c.__dict__ for c in client.calls], default=str)
    logging.getLogger("satyapan.audit").error("tool failed: %s", [t.detail for t in st["tool_runs"]])
    logging.getLogger("satyapan.audit").error("database error connecting to %s", MONGO)
    logs = buf.getvalue()
    secrets = (KEY, SECRET, HFTOK, "AUDITdbPassw0rd", CFTOK)
    out = {"key_in_report": any(x in report for x in secrets), "key_in_call_records": any(x in calls for x in secrets),
           "key_in_logs": any(x in logs for x in secrets),
           "ai_called": any("api.cloudflare.com" in c.url for c in client.calls),
           "tool_run_details": [(t.tool, t.status, t.detail[:160]) for t in st["tool_runs"] if t.detail]}
    path = ROOT / "results" / "audit" / "key_leakage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    for k in ("key_in_report", "key_in_call_records", "key_in_logs"):
        print(f"{'FAIL' if out[k] else 'PASS'}  {k}: {out[k]}")
    for row in out["tool_run_details"]:
        print("   ", row)
    sys.exit(1 if any(out[k] for k in ("key_in_report", "key_in_call_records", "key_in_logs")) else 0)


if __name__ == "__main__":
    main()
