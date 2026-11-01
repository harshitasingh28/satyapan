"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconSeal } from "./Icons";

const NAV = [
  { href: "/verify", label: "Verify" },
  { href: "/history", label: "History" },
  { href: "/#how-it-decides", label: "How it works" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="border-b border-rule bg-surface">
      <div className="page flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
        <Link href="/" className="flex items-center gap-2.5 text-ink no-underline hover:text-ink">
          <IconSeal size={30} className="text-accent" />
          <span className="flex flex-col leading-none">
            <span className="font-serif text-lg font-bold tracking-tight">Satyapan</span>
            <span lang="hi" className="mt-0.5 text-xs text-muted">
              सत्यापन
            </span>
          </span>
        </Link>
        <nav aria-label="Main">
          <ul className="flex flex-wrap items-center gap-x-1 gap-y-1">
            {NAV.map((item) => {
              const current = item.href === pathname;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={current ? "page" : undefined}
                    className={`inline-flex min-h-11 items-center rounded-md px-3 text-[0.9375rem] font-medium no-underline ${
                      current ? "bg-accent-tint text-accent" : "text-ink-soft hover:bg-sunk hover:text-ink"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
