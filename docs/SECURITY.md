# Security and privacy audit

**Status column:**
- **Tested** means a test in `tests/` exercises the control with real inputs.
- **Logic-tested** means a fake resolver or fake transport was used, so the decision logic is proven but not a live network path.

| Risk | Control | Code | Status |
|---|---|---|---|
| SSRF through user URLs | The backend never fetches a user URL. Outbound calls go only to an allowlist of API hosts, HTTPS only, redirects off | `http.py` | Tested: other hosts and plain http are refused |
| Private IP and localhost targets | Every submitted link is validated. Rejected targets are never sent to any third party. Rejects loopback, private, link-local and metadata `169.254.169.254`, CGNAT `100.64/10`, `0.0.0.0/8`, IPv4-mapped IPv6, and integer, hex and short IPv4 forms (`2130706433`, `0x7f000001`, `127.1`). Also rejects `.local` and `.internal` names, credentials in URLs, and ports other than 80/443 | `security/ssrf.py` | Tested (18 unsafe cases, 2 safe) |
| Redirect handling | No redirects anywhere by default. The optional shortener expander (`guarded_fetch`, off by default) re-validates every hop | `security/ssrf.py` | Logic-tested: a redirect to `127.0.0.1` is refused |
| DNS rebinding | `guarded_fetch` resolves once, rejects if any address is non-public, connects to the checked IP, and sends Host and SNI for the real name, as OWASP advises | `security/ssrf.py` | Logic-tested with a fake resolver. Live path not tested |
| File type spoofing | Magic-byte sniffing (JPEG, PNG, WebP, MP4/MOV, WebM, Ogg, WAV, MP3, M4A). The file name is never trusted. Content type wins over the extension | `security/uploads.py` | Tested: a shell script named `.jpg` is rejected |
| Corrupt and hostile media | Pillow full decode. ffprobe with a 10 s timeout. FFmpeg with timeouts. Files stored under random names | `security/uploads.py`, `api/app.py` | Tested: a truncated JPEG is rejected |
| Size and dimension limits | 10 MB images, 50 MB video, 10 MB audio, 180 s duration (0.5 s tolerance), 40 MP pixel limit checked from the header before decoding. Every POST must declare Content-Length, and bodies over 52 MB are refused with 413 BEFORE they are read (Starlette otherwise parses the whole multipart body first) | config, `api/app.py`, `security/uploads.py` | Tested in the audit: 60 MP image rejected, 60 MB body and a declared 2 GB body refused with 413, missing Content-Length gets 411. Audit finding: before the fix, 40 to 80 MP images were accepted and bodies were fully buffered |
| Malware | Uploads are never executed or served back. **Not done:** antivirus scanning. **Residual risk:** media parsers have had CVEs. Run FFmpeg and Tesseract in the container, keep them updated, and add ClamAV if time allows | n/a | Residual risk |
| Path traversal | Ids must be alphanumeric. Upload paths are generated, never taken from the client | `storage.py`, `api/app.py` | Tested |
| API key exposure | Keys only in the server's `.env`, never sent to the browser. `.env` is gitignored. Keys are redacted from logs, call records, every `ToolError` message and stored tool details: key-like parameters and headers, plus the literal value of every configured secret | `logging_setup.py`, `errors.py` | Tested in the audit with a service that echoes the key back. Audit finding: before the fix the key leaked into the stored report through `tool_runs.detail` |
| Third-party uploads | Three consent flags, all **off by default**: text to an LLM, links to urlscan, media to Cloud Vision and Sightengine. Images are re-encoded without EXIF or GPS before upload. urlscan uses `unlisted`, with `private` available | `pipeline/graph.py`, `security/uploads.py` | Tested: consent gating and EXIF stripping |
| Safe Browsing privacy | v5 `urls:search` sends raw URLs to Google. `hashes.search` exists for privacy-preserving checks (R) | `links/safebrowsing.py` | Documented. Consider `hashes.search` |
| LLM providers | Free Gemini: "human reviewers may read" inputs, "Do not submit... personal information" (V). Sarvam trains on content unless you opt out (R). For user content use local Ollama, a paid tier, or consent plus redaction | `llm.py` | Default off |
| Retention | Uploads and working files are deleted as soon as an investigation finishes. Investigation records (they contain the user's text) are deleted after 24 h by `Store.sweep`, which the API runs at start-up and at most every 10 minutes. The known-debunk indexes store hashes, keypoints and fingerprints, not media | `storage.py`, `api/app.py` | Tested in the audit. Audit finding: before the fix the sweep was never called and did not cover investigation records |
| Abuse and quotas | Token bucket, 10 POSTs per minute per client IP. uvicorn trusts `X-Forwarded-For` from 127.0.0.1 by default, so a proxy on the same host works as is, and any local process can bypass the limit with a fake header (measured). A proxy on another host needs `--forwarded-allow-ips=<proxy IP>`, otherwise all users share one bucket. Daily budgets per paid-quota tool (Sightengine 80, Vision 30, urlscan 100, VirusTotal 400), with a process-wide lock, a file lock and atomic writes. At most `SATYAPAN_MAX_CONCURRENT_JOBS` investigations run at once, the rest queue | `security/ratelimit.py`, `api/app.py` | Tested in the audit: 8 threads, exactly 20 of 40 budget units granted. Audit finding: before the fix concurrent budget use raised JSONDecodeError |
| Platform terms | No Telegram scraping or indexing (AI use prohibited). No myScheme scraping (bots prohibited). No YouTube downloading ("download... any Content" prohibited, R) | design | n/a |

## Before any public deployment

1. Put the backend behind HTTPS with request size limits at the proxy as well.
2. Keep the built-in retention sweep, or run `Store.sweep()` from cron if the API is not always running.
3. Show the consent text in the UI before any third-party check, and record consent per investigation.
4. Show "Advisory provided by Google" next to any Safe Browsing result.
5. Commercial use breaks several free tiers: Safe Browsing, VirusTotal, urlscan (written permission needed) and Vercel Hobby. Re-check them before going beyond the hackathon.
6. The Gemini API requires users to be 18 or older (V). Check your own team before signing up.


## Satyapan 2.0 additions (1 Nov 2026)

- **Secrets:** `HF_TOKEN`, `MONGODB_URI` and `GOOGLE_API_KEY` live only in the API's environment (Secret Manager on Cloud Run). The web app has one public setting, `NEXT_PUBLIC_API_BASE_URL`. `npm run check-bundle` fails the build if a token pattern appears in the built files. Logs redact `hf_` tokens, MongoDB credentials and every configured secret value (`audit/key_leakage.py` plants all three and checks reports, call records and logs).
- **Private records:** each investigation returns a random access token once (`secrets.token_urlsafe(32)`). Only its SHA-256 hash is stored and compared in constant time. A wrong token gives 404.
- **Hosted models only:** the HTTP client refuses non-HTTPS URLs, so no local model server can be configured.
- **AI output:** never trusted. Claims must be quoted from the message, comparison quotes must be found in both texts, explanation sentences must cite evidence and pass the citation checks, and a model's attempt to return a verdict is ignored (`audit/llm_injection.py`, `tests/test_v2_pipeline.py`).
- **CORS:** only `SATYAPAN_ALLOWED_ORIGINS`, methods GET and POST, headers `Content-Type` and `X-Access-Token`.
- **Rate limiting behind Cloud Run:** with `SATYAPAN_TRUSTED_PROXY_HOPS=1` the client IP is the last `X-Forwarded-For` entry. Entries a client adds are ignored. Limits are per instance, so `--max-instances` bounds the total.
- **Spending:** daily caps on Hugging Face chat and embedding calls per instance.
- **Data minimisation:** uploaded files are deleted after each report. MongoDB keeps hashes and match results, never pixels. Vectors of user text are never stored. Records expire after 7 days (TTL).
- **Third-party processing:** user text goes to Hugging Face and the provider named in the model suffix only with the user's consent. The provider's data policy has not been reviewed yet.
- **AI provider:** the consent box names the provider that receives the text (Cloudflare Workers AI by default). Read that provider's data terms before using real private messages. Cloudflare's terms have not been reviewed in this project yet. If a Gemini free-tier key is ever configured, the consent box also warns that Google may use the text to improve its products.
- **Cloudflare token:** create it with only the Workers AI permissions. The account ID is validated as 32 hexadecimal characters before it is put into any URL. The token is redacted from logs like every other secret.
