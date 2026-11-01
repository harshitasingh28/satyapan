# External data sources and APIs

## How to read this page

**Test status** is from our build workspace on 31 Oct 2026, whose network blocks everything except PyPI and GitHub. So **no external API has had a live success yet**. The statuses mean:

- **AUTH_REQUIRED:** no key was configured, so the request was not sent.
- **BLOCKED:** the request was sent, using placeholder keys, and the workspace proxy refused it with 403. The service never saw it.
- **NOT_TESTED:** deliberately not run.

Run `python -m integration.run_all` on your MacBook to get real statuses.

**Verification marks:**
- **V:** we opened the official page ourselves.
- **R:** our research agent read the official page and quoted it. We did not re-open it.
- **P:** probed through a summarising web fetcher. This shows the endpoint exists, but it is not a raw HTTP test.

## Used in the spike

| Item | Official documentation | Endpoint | Auth | Free tier | Billing | Input | Output | Latency | Restrictions | Test status |
|---|---|---|---|---|---|---|---|---|---|---|
| Google Fact Check Tools, search | developers.google.com/fact-check/tools/api (V) | `GET https://factchecktools.googleapis.com/v1alpha1/claims:search` | API key | Quota not published, see Cloud console (V) | Not stated | `query` (required unless `reviewPublisherSiteFilter`), `languageCode`, `maxAgeDays`, `pageSize`, `pageToken` | `claims[]` with `text`, `claimant`, `claimDate`, `claimReview[]` (`publisher`, `url`, `title`, `reviewDate`, `textualRating`, `languageCode`) (V) | not measured | Google API Terms. ClaimReview content stays the publishers', each markup has its own `sdLicense` (R) | AUTH_REQUIRED, then BLOCKED |
| Fact Check Tools, image search | same (V) | `GET .../v1alpha1/claims:imageSearch` | API key | as above | Not stated | `imageUri`, must be a public http(s) URL (V) | `results[].claim` | not measured | User uploads would need short-lived public hosting, so this is only used for public URLs | AUTH_REQUIRED, then BLOCKED |
| Safe Browsing v5 | developers.google.com/safe-browsing/reference/rest/v5/urls/search (V) | `GET https://safebrowsing.googleapis.com/v5/urls:search?urls=...` | API key (Google standard) | default quota (R) | Not stated | up to 50 URLs (V) | `threats[]` (`url`, `threatTypes[]`), `cacheDuration` (V) | not measured | Non-commercial only. Show "Advisory provided by Google" and do not present results as certain (R). Sends raw URLs to Google, `hashes.search` avoids that | AUTH_REQUIRED, then BLOCKED |
| Safe Browsing v4 (fallback) | developers.google.com/safe-browsing/v4/lookup-api (V) | `POST .../v4/threatMatches:find?key=` | API key | default quota, "no cost" (V) | No | up to 500 URLs | `{}` if clean, else `matches[]` (V) | not measured | **Deprecated**, no shutdown date (R) | AUTH_REQUIRED, then BLOCKED |
| RDAP | data.iana.org/rdap/dns.json (V) | bootstrap, then `{server}domain/{name}`. `.in` uses `https://rdap.nixiregistry.in/rdap/` | none | not stated | No | domain | `events[]` with `registration` date, registrar | not measured | `.co` has no RDAP server in the bootstrap (V) | BLOCKED. P: `uidai.gov.in` and `google.co.in` returned registration dates |
| PIB press-release RSS | pib.gov.in/ViewRss.aspx (V) | `RssMain.aspx?ModId=6&Lang=1&Regid=3` (documented), `...&lang=1&regid=3&reg=3` (variant), `...ModId=6&Lang=2&Regid=3` (Hindi) | none | open | No | GET | RSS 2.0, about 20 items. P: **no pubDate**, and the documented English URL returned Hindi titles | not measured | Copyright (EN, V): free reproduction, no prior approval, accurate and not misleading, acknowledge source, third-party material excluded. Indexing not stated | BLOCKED. The integration test checks the title script |
| Wikidata Query Service | wikitech.wikimedia.org/wiki/Wikidata_Query_Service (R) | `GET https://query.wikidata.org/sparql?query=...&format=json` | none, descriptive User-Agent required (R) | limits not verified | No | SPARQL | bindings JSON | not measured | CC0 data (R). Used offline only, to build the allowlist | BLOCKED, and the P probe failed |
| urlscan.io | docs.urlscan.io/guides/quickstart (V), urlscan.io/pricing (R) | `POST https://urlscan.io/api/v1/scan`, poll `GET /api/v1/result/{uuid}/` (404 pending, 410 deleted), wait at least 30 s (V) | `API-Key` header | Per day: 50 private, 1,000 unlisted, 5,000 public scans, 1,000 searches, 10,000 result requests (R) | No | URL and visibility | page, final URL, verdict, screenshot | at least 30 s by design | Commercial use needs written permission. You must have permission to submit URLs (R). We use `unlisted` and need user consent | AUTH_REQUIRED, then BLOCKED |
| Sightengine `genai` | sightengine.com/docs/ai-generated-image-detection (V) | `POST https://api.sightengine.com/1.0/check.json` with `models=genai` | `api_user`, `api_secret` | 2,000 operations/month, max 500/day. Docs example shows 5 operations per call (V) | Not stated | image file or URL | `type.ai_generated` from 0 to 1 | not measured | Proprietary. Vendor-only accuracy claims (R). Consent required | AUTH_REQUIRED, then BLOCKED |
| Cloud Vision Web Detection | docs.cloud.google.com/vision/docs/detecting-web (V) | `POST https://vision.googleapis.com/v1/images:annotate` with `WEB_DETECTION` | OAuth via gcloud in the docs. API-key support not confirmed | first 1,000 units/month free, then $3.50 per 1,000 (V) | **Yes** (V) | base64 image | matching pages, full and partial matches, best-guess labels | not measured | Gives where, not when. Consent required | AUTH_REQUIRED (not configured) |
| Tesseract OCR (local) | github.com/tesseract-ocr/tessdata (R) | local binary | none | free, Apache-2.0 | No | image | text | 224 ms Hindi+English, 47 ms Telugu, on rendered text | Real-screenshot accuracy unknown. Published Hindi evidence is old (R) | LOCAL_SUCCESS on rendered text |
| c2pa-python (local) | github.com/contentauth/c2pa-python (V) | local | none | free, Apache-2.0 or MIT | No | file | manifest, signer, validation, digital source type | about 4 ms | Remote manifests need network | LOCAL_SUCCESS |

## Optional, not tested

| Item | Status and reason |
|---|---|
| LLM via an OpenAI-compatible endpoint | NOT_TESTED. Options and their terms:<br>• **Gemini free tier:** content is used to improve Google's products and "human reviewers may read" it, with the instruction "Do not submit sensitive, confidential, or personal information" (V). Base URL `https://generativelanguage.googleapis.com/v1beta/openai/` (R).<br>• **Sarvam:** ₹100 credit, and trains on your content unless you opt out (R).<br>• **Ollama:** runs locally at `http://localhost:11434/v1` (R), so nothing leaves the machine. |
| VirusTotal v3 URL report | NOT_TESTED. Public API: 4 requests/minute, 500/day, non-commercial (V) |
| SerpApi Google Lens | Not used. 250 searches/month free (R). It scrapes Google results, so terms risk sits with you |
| Reality Defender | Not used. 50 free scans/month for image, audio and text, video from $399/month (R) |
| SynthID Detector | Manual check only. Web portal, no API found, detects Google and partner watermarks only (R) |

## Investigated and not used

| Source | Reason |
|---|---|
| PIB Fact Check on Telegram | Telegram's content-licensing terms prohibit scraping, indexing or using platform data to validate, benchmark or deploy AI (V). PIB publishes debunks only on social platforms. Record PIB debunks by hand with links instead. |
| myScheme | No public API. Terms prohibit bots and scrapers without written authorisation (R) |
| data.gov.in OGD API | Needs an API key. Base URL and limits could not be verified (R) |
| RBI press-release RSS | The feed exists (R), but RBI's disclaimer prohibits caching and deep links without permission (R) |
| CERT-In advisories | No feed found (R) |
| TinEye API | From $200, card only (R) |
| Bing Visual Search | Bing Search APIs retired 11 Aug 2025 (R) |
| Google Custom Search JSON API | Closed to new customers (checked in an earlier round) |
