# Satyapan 2.0 API contract

The FastAPI backend is the only component that holds secrets. The browser talks to it directly with `fetch`. All JSON field names are exactly as below.

Base URL: `NEXT_PUBLIC_API_BASE_URL` (for example `http://localhost:8000`). CORS allows the origins in `SATYAPAN_ALLOWED_ORIGINS`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /health` | `{"ok": true}` |
| `GET /v1/status` | Which integrations are configured (booleans only, never keys), models, corpus sizes, limits |
| `POST /v1/investigations/stream` | Multipart submission. Response is `text/event-stream` with live pipeline events |
| `POST /v1/investigations` | Same form, returns `202 {"id", "status": "queued", "access_token"}`. The pipeline runs in the background (local and CLI use) |
| `GET /v1/investigations/{id}` | Header `X-Access-Token: <token>`. Returns the stored record |
| `GET /v1/investigations/{id}/events` | Header `X-Access-Token`. Returns `{"events": StepEvent[]}` saved during the run |
| `GET /v1/investigations/{id}/report.md` | Header `X-Access-Token` or query `?token=`. Markdown audit report download |
| `GET /v1/investigations/{id}/report.json` | Same, JSON download |

A wrong or missing token returns **404** (the API never confirms that an id exists). Errors return `{"detail": "..."}` or `{"error": "..."}` with status 400, 404, 411, 413 or 429.

## Submission form fields (multipart/form-data)

| Field | Type | Notes |
|---|---|---|
| `text` | string | Up to 5,000 characters. English, Hindi, Telugu or mixed |
| `links` | string | One URL per line, at most 10 used |
| `files` | file, repeatable | At most 4. Images, video, audio. Limits come from `/v1/status` |
| `consent_third_party_text` | `"true"` or `"false"` | Allows sending text to Hugging Face models and Google Fact Check |
| `consent_third_party_links` | `"true"` or `"false"` | Allows link checks with third-party services |
| `consent_third_party_media` | `"true"` or `"false"` | Allows third-party media checks |

The request must carry a `Content-Length` header (browsers do this for `FormData`).

## Server-sent events from `POST /v1/investigations/stream`

Each message is `event: <name>\ndata: <json>\n\n`. Lines starting with `:` are keep-alive comments.

| Event | Data |
|---|---|
| `created` | `{"id": string, "access_token": string, "status": "queued", "expires_at": ISO}` |
| `queued` | `{"id": string, "message": string}` when other investigations are running |
| `step` | `StepEvent` |
| `done` | `{"id": string, "status": "done", "report": Report}` |
| `error` | `{"id": string or null, "status": "error", "message": string}` |

```ts
type StepEvent = {
  seq: number;                 // 1, 2, 3 ... in order
  ts: string;                  // ISO time on the server
  node: string;                // e.g. "extract_claims". New nodes may appear, render unknown ones generically
  phase: "start" | "end";
  label: string;               // human label from the server, e.g. "Extracting claims"
  ms?: number;                 // on "end"
  tool_runs?: ToolRun[];       // on "end", tools that ran in this node
  new_evidence?: string[];     // on "end", evidence ids added in this node
};
```

## Stored record (`GET /v1/investigations/{id}`)

```ts
type InvestigationRecord = {
  id: string;
  status: "queued" | "running" | "done" | "error" | "interrupted";
  created_at: string;
  expires_at: string;          // records are deleted automatically after 7 days by default
  report?: Report;             // when status is "done"
  error?: string;
};
```

## Report

```ts
type Verdict = "GENUINE" | "FAKE" | "UNVERIFIED";
type ToolStatus = "LIVE_SUCCESS" | "LOCAL_SUCCESS" | "AUTH_REQUIRED" | "RATE_LIMITED" | "BLOCKED"
  | "SERVICE_ERROR" | "NOT_TESTED" | "SKIPPED_CONSENT" | "SKIPPED_NOT_APPLICABLE" | "INPUT_ERROR";

type Claim = {
  id: string; text: string;
  source: string;              // "user_text", "ocr:<media id>", "llm"
  language: "en" | "hi" | "te" | "mixed" | "unknown";
  entities: string[]; amounts: string[]; urls: string[]; phones: string[];
  calls_to_action: string[]; checkworthiness: number;
};

type Evidence = {
  id: string;                  // "E1", "E2" ...
  tool: string;                // e.g. "pib_release_index", "factcheck_search", "safe_browsing", "ai_comparison"
  source_name: string;
  source_url: string | null;   // render as a link only if it starts with http:// or https://
  target: string;              // claim id, link URL or media id
  kind: "fact_check" | "official_record" | "provenance" | "credentials" | "synthetic_signal" | "link_risk" | "context";
  stance: "supports" | "contradicts" | "neutral";
  strength: "strong" | "moderate" | "weak" | "none";
  established: string;         // what the tool established, plain words, from data only
  independence_key: string;
  limitations: string[];
  data: Record<string, unknown>;
  retrieved_at: string;        // ISO
  external: boolean;
  origin: "api" | "official_index" | "local_algorithm" | "deterministic_check" | "ai_comparison";
  quote: string | null;        // exact text copied from the source, verified in code
  published_at: string | null; // when the source says it was published, if known
};

type ToolRun = { tool: string; status: ToolStatus; target: string; ms: number; detail: string };

type Statement = {
  text: string;
  evidence_ids: string[];
  kind: "verified_fact" | "ai_explanation" | "unavailable";
};
// Every statement in report.reason cites at least one evidence id. Build the "Not available"
// section from tool_runs whose status is AUTH_REQUIRED, RATE_LIMITED, BLOCKED or SERVICE_ERROR,
// plus report.limitations. The backend currently never puts kind "unavailable" in report.reason.

type MediaMatch = {
  known_id: string;
  tier: "exact_duplicate" | "modified_duplicate" | "similar_scene";
  publisher?: string; source_url?: string | null; claim?: string;
  phash_distance?: number; inliers?: number; overlap_similarity?: number | null;
};

type MediaAssessment = {
  kind: "image" | "video" | "audio";
  name?: string;               // original file name
  manipulation: string;        // e.g. "NOT_ASSESSED", "CREDENTIALS_INVALID"
  credentials?: string;        // C2PA: "present", "absent", "error"
  provenance?: string;         // e.g. "MATCHES_DEBUNKED_MEDIA", "NO_MATCH_IN_INDEX", "INDEX_EMPTY"
  tier?: "exact_duplicate" | "modified_duplicate" | "similar_scene" | "possible_reuse"
       | "verified_provenance" | "unknown_provenance";
  matches?: MediaMatch[];
  frames?: number; deepfake?: string; voice_authenticity?: string;
  ocr_text?: string;
};

type Report = {
  investigation_id: string;
  created_at: string;
  claim: Claim | null;         // the main claim
  claims: Claim[];             // every claim found
  verdict: Verdict;
  verdict_reason: string;      // "supported", "contradicted", "conflict", "insufficient", "uncited", "outdated", "link_mismatch"
  evidence_strength: "high" | "medium" | "n/a";
  strength_explanation: string;
  reason: Statement[];
  evidence: Evidence[];
  media_assessment: Record<string, MediaAssessment>;
  limitations: string[];
  tool_runs: ToolRun[];
  trace: { node: string; ms: number; tool_runs: string[]; new_evidence: string[] }[];
  ai: {
    chat_model: string | null;
    embedding_model: string | null;
    extraction: string;        // "used", "not_configured", "no_consent", "failed: <status>"
    comparison: string;        // same values
    explanation: string;       // "llm_validated", "template", "not_configured", "no_consent"
    problems: string[];        // AI outputs rejected by code checks
  };
};
```

## `GET /v1/status`

```ts
type Status = {
  version: string;
  store: "mongo" | "json";
  integrations: Record<string, boolean>;   // e.g. factcheck, safe_browsing, hf_chat, hf_embeddings, mongodb, urlscan
  models: { chat: string | null; chat_fallback: string | null; embedding: string | null };
  corpus: { pib_releases: number; known_claims: number; known_images: number; known_audio: number };
  limits: { max_text_chars: number; max_links: number; max_files: number;
            max_image_mb: number; max_video_mb: number; max_audio_mb: number; max_media_seconds: number };
  retention_hours: number;
};
```
