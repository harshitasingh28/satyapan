# Integration results

Run at 2026-10-30T20:35:51+00:00 on host `vm`.

| Test | Status | Request sent | Real response | HTTP | Latency ms | Detail |
|---|---|---|---|---|---|---|
| factcheck_search | BLOCKED | True | False | - | 2507.0 | network: 403 Forbidden |
| factcheck_image_search | BLOCKED | True | False | - | 2571.6 | network: 403 Forbidden |
| safe_browsing_v5 | BLOCKED | True | False | - | 2554.0 | network: 403 Forbidden |
| safe_browsing_v4 | BLOCKED | True | False | - | 2483.6 | network: 403 Forbidden |
| rdap_bootstrap | BLOCKED | True | False | - | 2480.5 | network: 403 Forbidden |
| rdap_domain | BLOCKED | True | False | - | 2568.1 | network: 403 Forbidden |
| wikidata_sparql | BLOCKED | True | False | - | 2517.2 | network: 403 Forbidden |
| pib_rss | BLOCKED | True | False | - | 7512.7 | all PIB feeds failed |
| urlscan_quotas | BLOCKED | True | False | - | 2456.7 | network: 403 Forbidden |
| urlscan_scan | BLOCKED | True | False | - | 2543.0 | network: 403 Forbidden |
| sightengine_genai | BLOCKED | True | False | - | 2529.6 | network: 403 Forbidden |
| cloud_vision_web | AUTH_REQUIRED | False | False | - | 0.0 | vision not configured in .env, request not sent |
| llm_claim_extraction | AUTH_REQUIRED | False | False | - | 0.0 | llm not configured in .env, request not sent |
