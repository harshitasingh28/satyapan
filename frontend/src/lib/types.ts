// Types copied from docs/API_CONTRACT.md. Field names are final: do not rename.

export type Verdict = "GENUINE" | "FAKE" | "UNVERIFIED";

export type ToolStatus =
  | "LIVE_SUCCESS"
  | "LOCAL_SUCCESS"
  | "AUTH_REQUIRED"
  | "RATE_LIMITED"
  | "BLOCKED"
  | "SERVICE_ERROR"
  | "NOT_TESTED"
  | "SKIPPED_CONSENT"
  | "SKIPPED_NOT_APPLICABLE"
  | "INPUT_ERROR";

export type ClaimLanguage = "en" | "hi" | "te" | "mixed" | "unknown";

export type Claim = {
  id: string;
  text: string;
  source: string; // "user_text", "ocr:<media id>", "llm"
  language: ClaimLanguage;
  entities: string[];
  amounts: string[];
  urls: string[];
  phones: string[];
  calls_to_action: string[];
  checkworthiness: number;
};

export type EvidenceKind =
  | "fact_check"
  | "official_record"
  | "provenance"
  | "credentials"
  | "synthetic_signal"
  | "link_risk"
  | "context";

export type Stance = "supports" | "contradicts" | "neutral";
export type Strength = "strong" | "moderate" | "weak" | "none";
export type EvidenceOrigin = "api" | "official_index" | "local_algorithm" | "deterministic_check" | "ai_comparison";

export type Evidence = {
  id: string;
  tool: string;
  source_name: string;
  source_url: string | null;
  target: string;
  kind: EvidenceKind;
  stance: Stance;
  strength: Strength;
  established: string;
  independence_key: string;
  limitations: string[];
  data: Record<string, unknown>;
  retrieved_at: string;
  external: boolean;
  origin: EvidenceOrigin;
  quote: string | null;
  published_at: string | null;
};

export type ToolRun = { tool: string; status: ToolStatus; target: string; ms: number; detail: string };

export type StatementKind = "verified_fact" | "ai_explanation" | "unavailable";

export type Statement = {
  text: string;
  evidence_ids: string[];
  kind: StatementKind;
};

export type MatchTier = "exact_duplicate" | "modified_duplicate" | "similar_scene";

export type MediaMatch = {
  known_id: string;
  tier: MatchTier;
  publisher?: string;
  source_url?: string | null;
  claim?: string;
  phash_distance?: number;
  inliers?: number;
  overlap_similarity?: number | null;
};

export type MediaTier =
  | "exact_duplicate"
  | "modified_duplicate"
  | "similar_scene"
  | "possible_reuse"
  | "verified_provenance"
  | "unknown_provenance";

export type MediaAssessment = {
  kind: "image" | "video" | "audio";
  name?: string;
  manipulation: string;
  credentials?: string;
  provenance?: string;
  tier?: MediaTier;
  matches?: MediaMatch[];
  frames?: number;
  deepfake?: string;
  voice_authenticity?: string;
  synthetic_signal?: string | number;
  ocr_text?: string;
};

export type TraceEntry = { node: string; ms: number; tool_runs: string[]; new_evidence: string[]; notes?: string[] };

export type AiPlanDecision = {
  check: string;
  run: boolean;
  decided_by: "ai" | "code";
  why: string;
  queries?: string[];
};

export type AiReplan = {
  status: string;
  why?: string;
  queries?: string[];
  problems?: string[];
  found?: number;
};

export type AiPlan = {
  replan?: AiReplan;
  status: string;
  model?: string | null;
  claim_type?: string | null;
  language?: string | null;
  decisions?: AiPlanDecision[];
  factcheck_queries?: string[];
  official_query?: string | null;
  problems?: string[];
};

export type AiPair = {
  candidate: string;
  type: string;
  source_url?: string | null;
  text?: string;
  cosine?: number | null;
  relation?: string | null;
  same_subject?: boolean | null;
  evidence_quote?: string | null;
  claim_quote?: string | null;
  verified?: boolean | null;
  problem?: string | null;
};

export type AiInfo = {
  chat_model: string | null;
  embedding_model: string | null;
  extraction: string;
  comparison: string;
  explanation: string;
  problems: string[];
  plan?: AiPlan;
  pairs?: AiPair[];
};

export type Report = {
  investigation_id: string;
  created_at: string;
  claim: Claim | null;
  claims: Claim[];
  verdict: Verdict;
  verdict_reason: string;
  evidence_strength: "high" | "medium" | "n/a";
  strength_explanation: string;
  reason: Statement[];
  evidence: Evidence[];
  media_assessment: Record<string, MediaAssessment>;
  limitations: string[];
  tool_runs: ToolRun[];
  trace: TraceEntry[];
  ai: AiInfo;
};

export type StepEvent = {
  seq: number;
  ts: string;
  node: string;
  phase: "start" | "end";
  label: string;
  ms?: number;
  tool_runs?: ToolRun[];
  new_evidence?: string[];
  notes?: string[];
};

export type InvestigationStatus = "queued" | "running" | "done" | "error" | "interrupted";

export type InvestigationRecord = {
  id: string;
  status: InvestigationStatus;
  created_at: string;
  expires_at: string;
  report?: Report;
  error?: string;
};

export type Limits = {
  max_text_chars: number;
  max_links: number;
  max_files: number;
  max_image_mb: number;
  max_video_mb: number;
  max_audio_mb: number;
  max_media_seconds: number;
};

export type Status = {
  version: string;
  store: "mongo" | "json";
  integrations: Record<string, boolean>;
  models: { chat: string | null; chat_fallback: string | null; embedding: string | null };
  // Host names that receive text for AI processing (never keys). Older servers omit this.
  providers?: { chat: string | null; chat_fallback: string | null; embedding: string | null };
  corpus: { pib_releases: number; known_claims: number; known_images: number; known_audio: number };
  limits: Limits;
  retention_hours: number;
};

// Server-sent event payloads from POST /v1/investigations/stream
export type CreatedEvent = { id: string; access_token: string; status: "queued"; expires_at: string };
export type QueuedEvent = { id: string; message: string };
export type DoneEvent = { id: string; status: "done"; report: Report };
export type ErrorEvent = { id: string | null; status: "error"; message: string };
