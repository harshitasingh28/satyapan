import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-20 border-t border-rule bg-surface">
      <div className="page grid gap-6 py-8 text-sm text-muted sm:grid-cols-[2fr_1fr]">
        <div className="measure space-y-2">
          <p>
            Satyapan is a student project built for the Forge Gen AI Buildathon. It is not a government service and does not
            speak for any department.
          </p>
          <p>Before you act on a message about money, documents or deadlines, confirm it on the department’s own website.</p>
        </div>
        <ul className="space-y-1 sm:justify-self-end">
          <li>
            <Link href="/verify">Verify a message</Link>
          </li>
          <li>
            <Link href="/history">Your history</Link>
          </li>
          <li>
            <Link href="/#how-it-decides">How Satyapan decides</Link>
          </li>
        </ul>
      </div>
    </footer>
  );
}
