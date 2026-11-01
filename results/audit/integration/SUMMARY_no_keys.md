# Integration results

Run at 2026-10-30T21:38:57+00:00 on host `vm`.

| Test | Status | Request sent | Real response | HTTP | Latency ms | Detail |
|---|---|---|---|---|---|---|
| factcheck_search | AUTH_REQUIRED | False | False | - | 0.0 | google_api_key not configured in .env, request not sent |
| factcheck_image_search | AUTH_REQUIRED | False | False | - | 0.0 | google_api_key not configured in .env, request not sent |
| safe_browsing_v5 | AUTH_REQUIRED | False | False | - | 0.0 | google_api_key not configured in .env, request not sent |
| safe_browsing_v4 | AUTH_REQUIRED | False | False | - | 0.0 | google_api_key not configured in .env, request not sent |
| rdap_bootstrap | BLOCKED | True | False | - | 2475.1 | network: 403 Forbidden |
| rdap_domain | BLOCKED | True | False | - | 2560.8 | network: 403 Forbidden |
| wikidata_sparql | BLOCKED | True | False | - | 2493.3 | network: 403 Forbidden |
| pib_rss | BLOCKED | True | False | - | 7526.0 | all PIB feeds failed |
| urlscan_quotas | AUTH_REQUIRED | False | False | - | 0.0 | urlscan_api_key not configured in .env, request not sent |
| urlscan_scan | NOT_TESTED | False | False | - | 0.0 | sends data to a third party: rerun with --allow-third-party |
| sightengine_genai | NOT_TESTED | False | False | - | 0.0 | sends data to a third party: rerun with --allow-third-party |
| cloud_vision_web | NOT_TESTED | False | False | - | 0.0 | sends data to a third party: rerun with --allow-third-party |
| llm_claim_extraction | NOT_TESTED | False | False | - | 0.0 | sends data to a third party: rerun with --allow-third-party |
