import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // Replit preview is served through a proxied iframe on a different origin.
  allowedDevOrigins: [
    "*.replit.dev",
    "*.repl.co",
    "127.0.0.1",
    "localhost",
    ...(process.env.REPLIT_DEV_DOMAIN ? [process.env.REPLIT_DEV_DOMAIN] : []),
  ],
  outputFileTracingRoot: path.join(__dirname),
  // /backend/* is handled exclusively by the route handler at
  // app/backend/[...path]/route.ts, which verifies the session cookie,
  // resolves the tenant, and injects the internal auth token before
  // forwarding to FastAPI. A rewrite here would bypass that security
  // boundary (requests would reach FastAPI without X-Internal-Token),
  // so no rewrites are configured.
  async headers() {
    if (process.env.NODE_ENV === "production") return [];
    // Prevent the Replit preview proxy/browser from caching stale responses in development.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store, max-age=0" },
          { key: "Pragma", value: "no-cache" },
        ],
      },
    ];
  },
  // No extra /backend rewrite needed beyond the one above; the server-side
  // route handler at app/backend/[...path]/route.ts takes precedence for
  // /backend/* and injects the internal auth token and tenant context
  // (plus forwarded cookies/CSRF) before forwarding to the FastAPI process.
};

export default nextConfig;
