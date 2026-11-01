import type { Limits } from "./types";

/** Used only when /v1/status cannot be read. The server still enforces its own limits. */
export const FALLBACK_LIMITS: Limits = {
  max_text_chars: 5000,
  max_links: 10,
  max_files: 4,
  max_image_mb: 10,
  max_video_mb: 50,
  max_audio_mb: 10,
  max_media_seconds: 180,
};

export type MediaKind = "image" | "video" | "audio";

const EXTENSIONS: Record<MediaKind, readonly string[]> = {
  image: ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif", "avif"],
  video: ["mp4", "m4v", "mov", "webm", "mkv", "3gp", "avi", "mpeg", "mpg"],
  audio: ["mp3", "wav", "ogg", "oga", "opus", "m4a", "aac", "amr", "flac", "weba"],
};

export const ACCEPT_ATTRIBUTE = "image/*,video/*,audio/*";

type FileLike = { name: string; size: number; type: string; lastModified?: number };

export function mediaKindOf(file: Pick<FileLike, "name" | "type">): MediaKind | null {
  const type = file.type.toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  const dot = file.name.lastIndexOf(".");
  if (dot === -1) return null;
  const ext = file.name.slice(dot + 1).toLowerCase();
  for (const kind of ["image", "video", "audio"] as const) {
    if (EXTENSIONS[kind].includes(ext)) return kind;
  }
  return null;
}

export function maxBytesFor(kind: MediaKind, limits: Limits): number {
  const mb = kind === "image" ? limits.max_image_mb : kind === "video" ? limits.max_video_mb : limits.max_audio_mb;
  return mb * 1024 * 1024;
}

export type RejectedFile = { name: string; size: number; reason: string };
export type FileValidation<T extends FileLike> = { accepted: T[]; rejected: RejectedFile[] };

function sameFile(a: FileLike, b: FileLike): boolean {
  return a.name === b.name && a.size === b.size && (a.lastModified ?? 0) === (b.lastModified ?? 0);
}

/**
 * Checks newly picked files against the ones already chosen and the server
 * limits. Accepted files keep their order; every rejection says why.
 */
export function validateFiles<T extends FileLike>(existing: readonly T[], incoming: readonly T[], limits: Limits): FileValidation<T> {
  const accepted: T[] = [];
  const rejected: RejectedFile[] = [];
  for (const file of incoming) {
    const kind = mediaKindOf(file);
    if (!kind) {
      rejected.push({ name: file.name, size: file.size, reason: "This is not an image, video or audio file." });
      continue;
    }
    if (file.size === 0) {
      rejected.push({ name: file.name, size: file.size, reason: "This file is empty." });
      continue;
    }
    const max = maxBytesFor(kind, limits);
    if (file.size > max) {
      rejected.push({
        name: file.name,
        size: file.size,
        reason: `Too large. The limit for ${kind} files is ${max / (1024 * 1024)} MB.`,
      });
      continue;
    }
    if ([...existing, ...accepted].some((f) => sameFile(f, file))) {
      rejected.push({ name: file.name, size: file.size, reason: "This file is already added." });
      continue;
    }
    if (existing.length + accepted.length >= limits.max_files) {
      rejected.push({
        name: file.name,
        size: file.size,
        reason: `Only ${limits.max_files} files can be sent with one message.`,
      });
      continue;
    }
    accepted.push(file);
  }
  return { accepted, rejected };
}

/** Non-empty lines from the links box. */
export function parseLinks(raw: string): string[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}
