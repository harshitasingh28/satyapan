import type { ReactNode } from "react";
import { formatDateTime } from "@/lib/format";
import type { Tone } from "@/lib/labels";
import { isHttpUrl } from "@/lib/url";
import { IconExternal } from "./Icons";

export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className="chip" data-tone={tone}>
      {children}
    </span>
  );
}

/**
 * Renders an <a> only for http:// and https:// URLs, opening in a new tab
 * without passing the opener or referrer. Anything else is shown as text.
 */
export function SafeLink({ url, children, className }: { url: string | null | undefined; children?: ReactNode; className?: string }) {
  if (!url) return <span className="text-muted">No link</span>;
  if (!isHttpUrl(url)) {
    return <span className={`break-anywhere ${className ?? ""}`}>{children ?? url}</span>;
  }
  return (
    <a href={url.trim()} target="_blank" rel="noopener noreferrer" className={`break-anywhere ${className ?? ""}`}>
      {children ?? url}
      <IconExternal size={14} className="ml-1 inline-block align-[-2px]" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

export function DateTime({ iso, fallback = "Not known" }: { iso: string | null | undefined; fallback?: string }) {
  if (!iso) return <span>{fallback}</span>;
  return <time dateTime={iso}>{formatDateTime(iso)}</time>;
}
