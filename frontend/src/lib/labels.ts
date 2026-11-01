import { humanise } from "./format";
import type { ClaimLanguage, EvidenceKind, EvidenceOrigin, MediaTier, Stance, Strength, ToolStatus, Verdict } from "./types";

export const VERDICT_MEANING: Record<Verdict, string> = {
  GENUINE: "Supported by a specific official source with matching facts.",
  FAKE: "Contradicted by reliable evidence.",
  UNVERIFIED: "Not enough reliable evidence to decide. This is not the same as true.",
};

export function verdictTone(verdict: string): "genuine" | "fake" | "unverified" {
  if (verdict === "GENUINE") return "genuine";
  if (verdict === "FAKE") return "fake";
  return "unverified";
}

export function verdictMeaning(verdict: string): string {
  return verdict in VERDICT_MEANING ? VERDICT_MEANING[verdict as Verdict] : "The server returned a verdict this page does not know.";
}

const VERDICT_REASON: Record<string, string> = {
  supported: "An official source supports the claim with matching facts.",
  contradicted: "Reliable evidence contradicts the claim.",
  conflict: "Reliable sources disagree with each other, so no side was taken.",
  insufficient: "Not enough reliable evidence was found.",
  uncited: "No statement could be tied to a cited, checked source.",
  outdated: "The matching evidence is too old to settle this claim.",
  link_mismatch: "The links in the message do not match the official source.",
};

export function verdictReasonText(reason: string): string {
  return VERDICT_REASON[reason] ?? humanise(reason);
}

const STRENGTH_LEVEL: Record<string, string> = { high: "High", medium: "Medium", "n/a": "Not applicable" };
export function evidenceStrengthLabel(level: string): string {
  return STRENGTH_LEVEL[level] ?? humanise(level);
}

export type Tone = "good" | "bad" | "warn" | "neutral" | "info";

const TOOL_STATUS: Record<ToolStatus, { label: string; tone: Tone; failed: boolean; skipped: boolean }> = {
  LIVE_SUCCESS: { label: "Ran live", tone: "good", failed: false, skipped: false },
  LOCAL_SUCCESS: { label: "Ran locally", tone: "good", failed: false, skipped: false },
  AUTH_REQUIRED: { label: "Not configured", tone: "warn", failed: true, skipped: false },
  RATE_LIMITED: { label: "Rate limited", tone: "bad", failed: true, skipped: false },
  BLOCKED: { label: "Blocked", tone: "bad", failed: true, skipped: false },
  SERVICE_ERROR: { label: "Service error", tone: "bad", failed: true, skipped: false },
  INPUT_ERROR: { label: "Input error", tone: "bad", failed: true, skipped: false },
  NOT_TESTED: { label: "Not tested", tone: "neutral", failed: false, skipped: true },
  SKIPPED_CONSENT: { label: "Skipped, no permission", tone: "neutral", failed: false, skipped: true },
  SKIPPED_NOT_APPLICABLE: { label: "Not applicable", tone: "neutral", failed: false, skipped: false },
};

export function toolStatusInfo(status: string): { label: string; tone: Tone; failed: boolean; skipped: boolean } {
  return TOOL_STATUS[status as ToolStatus] ?? { label: humanise(status), tone: "neutral", failed: false, skipped: false };
}

export const STANCE_LABEL: Record<Stance, { label: string; tone: Tone }> = {
  supports: { label: "Supports the claim", tone: "good" },
  contradicts: { label: "Contradicts the claim", tone: "bad" },
  neutral: { label: "Neutral", tone: "neutral" },
};

export function stanceInfo(stance: string): { label: string; tone: Tone } {
  return STANCE_LABEL[stance as Stance] ?? { label: humanise(stance), tone: "neutral" };
}

const STRENGTH_LABEL: Record<Strength, string> = {
  strong: "Strong evidence",
  moderate: "Moderate evidence",
  weak: "Weak evidence",
  none: "No weight",
};
export function strengthLabel(strength: string): string {
  return STRENGTH_LABEL[strength as Strength] ?? humanise(strength);
}

const ORIGIN_LABEL: Record<EvidenceOrigin, string> = {
  api: "API",
  official_index: "Official index",
  local_algorithm: "Local algorithm",
  deterministic_check: "Code check",
  ai_comparison: "AI comparison",
};
export function originLabel(origin: string): string {
  return ORIGIN_LABEL[origin as EvidenceOrigin] ?? humanise(origin);
}

const KIND_LABEL: Record<EvidenceKind, string> = {
  fact_check: "Published fact check",
  official_record: "Official record",
  provenance: "Media provenance",
  credentials: "Content credentials",
  synthetic_signal: "Synthetic media signal",
  link_risk: "Link safety",
  context: "Context",
};
export function evidenceKindLabel(kind: string): string {
  return KIND_LABEL[kind as EvidenceKind] ?? humanise(kind);
}

const LANGUAGE_LABEL: Record<ClaimLanguage, string> = {
  en: "English",
  hi: "Hindi",
  te: "Telugu",
  mixed: "Mixed languages",
  unknown: "Language not detected",
};
export function languageLabel(language: string): string {
  return LANGUAGE_LABEL[language as ClaimLanguage] ?? humanise(language);
}

/** BCP 47 tag for the lang attribute, when the claim has a single known language. */
export function langAttribute(language: string): string | undefined {
  return language === "en" || language === "hi" || language === "te" ? language : undefined;
}

export function claimSourceLabel(source: string): string {
  if (source === "user_text") return "From your message";
  if (source === "llm") return "Found by the AI model";
  if (source.startsWith("ocr:")) return `Text read from file ${source.slice(4)}`;
  return humanise(source);
}

export const MEDIA_TIER: Record<MediaTier, { label: string; meaning: string; tone: Tone }> = {
  exact_duplicate: {
    label: "Exact duplicate",
    meaning: "The same file is already in the index of known media.",
    tone: "info",
  },
  modified_duplicate: {
    label: "Modified duplicate",
    meaning: "A changed copy of known media, for example cropped, resized or screenshotted.",
    tone: "info",
  },
  similar_scene: {
    label: "Similar scene",
    meaning: "Looks like a similar scene to known media. This is not evidence that the file is fake.",
    tone: "neutral",
  },
  possible_reuse: {
    label: "Possible reuse",
    meaning: "May reuse earlier media. Check the matches before relying on it.",
    tone: "warn",
  },
  verified_provenance: {
    label: "Verified provenance",
    meaning: "Its origin was confirmed from an official or credentialed source.",
    tone: "good",
  },
  unknown_provenance: {
    label: "Unknown provenance",
    meaning: "Where this file came from could not be established. That does not make it genuine or fake.",
    tone: "neutral",
  },
};

export function mediaTierInfo(tier: string): { label: string; meaning: string; tone: Tone } {
  return MEDIA_TIER[tier as MediaTier] ?? { label: humanise(tier), meaning: "", tone: "neutral" };
}

const CREDENTIALS: Record<string, string> = {
  present: "Present. The file carries C2PA content credentials.",
  absent: "Not present. Most files have none, so this proves nothing on its own.",
  error: "Could not be read.",
};
export function credentialsLabel(value: string): string {
  return CREDENTIALS[value] ?? humanise(value);
}

const PROVENANCE: Record<string, string> = {
  MATCHES_DEBUNKED_MEDIA: "Matches media that fact checkers have already debunked.",
  NO_MATCH_IN_INDEX: "No match in the index of known media.",
  INDEX_EMPTY: "The index of known media is empty, so no comparison was possible.",
};
export function provenanceLabel(value: string): string {
  return PROVENANCE[value] ?? humanise(value);
}

const MANIPULATION: Record<string, string> = {
  NOT_ASSESSED: "Not assessed",
  CREDENTIALS_INVALID: "Content credentials are present but invalid",
};
export function manipulationLabel(value: string): string {
  return MANIPULATION[value] ?? humanise(value);
}

export function aiStepLabel(value: string): string {
  if (value === "used") return "Ran";
  if (value === "not_configured") return "Not configured on this server";
  if (value === "no_consent") return "Skipped, no permission to send text";
  if (value.startsWith("failed")) {
    const status = value.split(":").slice(1).join(":").trim();
    return status ? `Failed (${toolStatusInfo(status).label})` : "Failed";
  }
  return humanise(value);
}

export function aiExplanationLabel(value: string): string {
  if (value === "llm_validated") return "Written by the AI model, then checked against the evidence in code";
  if (value === "template") return "Written from a fixed template, without AI";
  if (value === "not_configured") return "No AI model is configured, so no AI explanation was written";
  if (value === "no_consent") return "Skipped, no permission to send text";
  return aiStepLabel(value);
}

const INTEGRATIONS: Record<string, string> = {
  factcheck: "Google Fact Check Tools",
  safe_browsing: "Google Safe Browsing",
  ai_chat: "AI chat model",
  ai_embeddings: "AI embeddings",
  hf_chat: "Hugging Face chat model",
  hf_embeddings: "Hugging Face embeddings",
  mongodb: "MongoDB storage",
  urlscan: "urlscan.io",
  vision: "Google Cloud Vision",
  cloud_vision: "Google Cloud Vision",
  rdap: "RDAP domain registration lookup",
  wikidata: "Wikidata",
  virustotal: "VirusTotal",
  sightengine: "Sightengine",
};
export function integrationLabel(key: string): string {
  return INTEGRATIONS[key] ?? humanise(key);
}
