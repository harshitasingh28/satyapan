# Satyapan security audit report

Final run `run_20261030T222654Z` (UTC). Raw outputs: `results/audit/run_20261030T222654Z/security_portfix.log` (rerun with the port fix), `security_practical_portfix.json`, `leakage.log`, `concurrency.json`. Baseline: `audit_logs/08_security_baseline.log`, `results/audit/security_practical_BASELINE.json`. The full analysis, including what was NOT tested, is section H of `docs/FINAL_TEST_AUDIT.md`.

All payloads were safe and local. A real uvicorn server on 127.0.0.1 was attacked. Nothing went to a third party.

## Practical checks (`audit/security_practical.py`)

Before fixes: 14 of 20 reported as passing, one of them falsely (the backslash parser differential parsed as pib.gov.in, which was the bug). After fixes: **21 of 21**.

| Area | Check | Result now | Detail now |
|---|---|---|---|
| SSRF | server made no request to itself via submitted links | PASS | /health hits before 0, after 0 |
| SSRF | unsafe links never passed to RDAP / Safe Browsing / urlscan | PASS | [] |
| Path traversal | client filename not used as a path | PASS |  |
| Uploads | oversized upload refused (413) | PASS | HTTP 413 after 0.12 s |
| Uploads | huge Content-Length rejected before reading the body | PASS | reply: 413 |
| Retention | uploads are removed after processing | PASS | 0 uploaded files still on disk after all investigations finished |
| Retention | sweep deletes investigation records older than the retention window | PASS | removed 1, left ['newrecord1'] |
| Retention | the API schedules the sweep (start-up and while serving) | PASS | _last_sweep=1793400395.1877813 |
| Uploads | 60 MP image rejected (configured limit 40 MP) | PASS | ok=False errors=['image exceeds the pixel limit (8000x7500 > 40,000,000 pixels)'] size=7354 bytes |
| Uploads | random bytes with an MP4 header rejected | PASS |  |
| Uploads | corrupt WAV rejected | PASS |  |
| Uploads | MP4 with no video stream handled (rejected as video or accepted as audio) | PASS | kind=video ok=False errors=['no video stream'] |
| Uploads | JPEG with appended payload (polyglot) noted | PASS | accepted=True. Not executed, and re-encoded before any third-party upload |
| URL schemes | javascript rejected | PASS |  |
| URL schemes | data rejected | PASS |  |
| URL schemes | file rejected | PASS |  |
| URL schemes | vbscript rejected | PASS |  |
| URL schemes | jar rejected | PASS |  |
| Injection | crafted host never reaches an RDAP request path: http://evil%2F..%2Fadmin.com/ | PASS | registered='evil%2f..%2fadmin.com' valid_host=False requests=[] |
| Injection | crafted host never reaches an RDAP request path: http://a.b.com%23frag/ | PASS | registered='a.b.com%23frag' valid_host=False requests=[] |
| Injection | crafted host never reaches an RDAP request path: http://x.com\@pib.gov.in/ | PASS | registered='x.com' valid_host=True requests=['https://data.iana.org/rdap/dns.json'] |

## Secret leakage (`audit/key_leakage.py`, mocked service that echoes the key)

```
### 2026-10-30T22:27:10Z leakage: python audit/key_leakage.py
PASS  key_in_report: False
PASS  key_in_call_records: False
PASS  key_in_logs: False
    ('factcheck_search', 'SERVICE_ERROR', 'bad request for https://factchecktools.googleapis.com/v1alpha1/claims:search?pageSize=10&query=PIB%3A+free+laptops+for+students%2C+register+at&languageCode=en&k')
    ('rdap', 'SERVICE_ERROR', 'bootstrap HTTP 400')
    ('safe_browsing', 'SERVICE_ERROR', 'bad request for https://safebrowsing.googleapis.com/v4/threatMatches:find?key=REDACTED body={"client":{"clientId":"satyapan","clientVersion":"0.2"},"threatInfo"')
    ('urlscan', 'SKIPPED_CONSENT', 'background sandbox scan not requested')
```

## Concurrency and quota budget (`audit/concurrency.py`)

* Budget race: 20 of 40 units granted with a limit of 20, exceptions: none.
* 8 simultaneous 12 MP image investigations: 8 of 8 done, 44.4 s in total, server peak memory 819.2 MB.

## Not tested or not mitigated

* Live DNS rebinding through `guarded_fetch` (off by default, logic-tested with a fake resolver only).
* Slow-body attacks under the 52 MB limit: uvicorn has no body-read timeout. Use a reverse proxy with timeouts.
* No authentication on the API. No antivirus scanning. Media parsers (FFmpeg, Pillow, Tesseract) remain attack surface.
* Prompt injection against a REAL LLM provider (only a local fake LLM was used).
* Rate limit: requests from 127.0.0.1 can fake their address with X-Forwarded-For (uvicorn trusts loopback by default), measured in `audit_logs/33_xff_behaviour.log`. Remote clients cannot.
