import path from "node:path";
import type { NextConfig } from "next";

// The only configuration is the public API base URL. It is not a secret: it is
// inlined into the browser bundle at build time.
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

const isProd = process.env.NODE_ENV === "production";

// Next.js injects small inline bootstrap scripts, so script-src needs
// 'unsafe-inline' without a nonce setup. Development also needs 'unsafe-eval'
// for fast refresh, so the policy is only sent from production builds.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${originOf(apiBase)}`.trim(),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
  poweredByHeader: false,
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  async headers() {
    const common = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ];
    return [
      {
        source: "/:path*",
        headers: isProd ? [...common, { key: "Content-Security-Policy", value: csp }] : common,
      },
    ];
  },
};

export default nextConfig;
