# Integration results

Run at 2026-10-30T21:39:13+00:00 on host `vm`.

| Test | Status | Request sent | Real response | HTTP | Latency ms | Detail |
|---|---|---|---|---|---|---|
| factcheck_search | BLOCKED | True | False | - | 2554.5 | network: 403 Forbidden |
| factcheck_image_search | BLOCKED | True | False | - | 2396.8 | network: 403 Forbidden |
| safe_browsing_v5 | BLOCKED | True | False | - | 2519.4 | network: 403 Forbidden |
| safe_browsing_v4 | BLOCKED | True | False | - | 2542.1 | network: 403 Forbidden |
| rdap_bootstrap | BLOCKED | True | False | - | 2520.7 | network: 403 Forbidden |
| rdap_domain | BLOCKED | True | False | - | 2473.7 | network: 403 Forbidden |
| wikidata_sparql | BLOCKED | True | False | - | 2291.6 | network: 403 Forbidden |
| pib_rss | BLOCKED | True | False | - | 7441.5 | all PIB feeds failed |
| urlscan_quotas | BLOCKED | True | False | - | 2520.0 | network: 403 Forbidden |
| urlscan_scan | BLOCKED | True | False | - | 2480.9 | network: 403 Forbidden |
| sightengine_genai | BLOCKED | True | False | - | 2535.0 | network: 403 Forbidden |
| cloud_vision_web | AUTH_REQUIRED | False | False | - | 0.0 | vision not configured in .env, request not sent |
| llm_claim_extraction | AUTH_REQUIRED | False | False | - | 0.0 | llm not configured in .env, request not sent |
