/**
 * Core proxy logic for the /backend/** route handler.
 *
 * Intentionally free of `next/server` imports so it can be unit-tested with
 * plain `node --experimental-strip-types --test` without needing a Next.js
 * runtime. The route handler wraps the returned ProxyResult in NextResponse.
 *
 * The optional `fetchFn` parameter lets tests inject a mock instead of the
 * global fetch.
 */

import {
  resolveSessionFromRequest,
  resolveTenantFromRequest,
} from "./tenant-resolver.ts";

const API_ORIGIN = "http://localhost:8000";

const SAFE_UPSTREAM_RESPONSE_HEADERS = [
  "Content-Disposition",
  "Cache-Control",
  "X-Content-Type-Options",
] as const;
/** Plain return value — no Next.js types. */
export interface ProxyResult {
  status: number;
  body: ArrayBuffer | string;
  contentType: string;
  setCookie?: string | null;
  responseHeaders?: Record<string, string>;
}

/** Minimal request shape needed by the proxy — satisfied by NextRequest. */
export interface ProxyableRequest {
  url: string;
  method: string;
  body: BodyInit | null | undefined;
  headers?: { get(name: string): string | null };
}

/**
 * Paths reachable without an authenticated session. Auth endpoints must be
 * anonymous (login/register create the session); FastAPI still enforces its
 * own cookie authentication on the rest of the auth router (me, logout,
 * change-password). Health/info are public liveness probes.
 */
function isPublicPath(segments: string[]): boolean {
  const path = segments.join("/");
  return (
    path === "api/v1/health" ||
    path === "api/v1/info" ||
    path === "api/v1/auth" ||
    path.startsWith("api/v1/auth/")
  );
}

function supportsTenantlessSession(segments: string[]): boolean {
  const path = segments.join("/");
  return (
    path === "api/v1/operations/board" ||
    path.startsWith("api/v1/operations/board/tasks/")
  );
}

/**
 * Resolve the tenant from the authenticated session cookie, guard
 * non-public paths, then forward to FastAPI.
 *
 * Returns a ProxyResult that the route handler converts to a NextResponse.
 * Returning a plain object (not NextResponse) keeps this module testable
 * without a Next.js runtime.
 */
export async function proxyRequest(
  req: ProxyableRequest,
  segments: string[],
  search: string,
  fetchFn: typeof fetch = fetch,
): Promise<ProxyResult> {
  // ── Authorization boundary ─────────────────────────────────────────────
  // Tenant comes from the verified session JWT — never from client headers.
  const tenantId = resolveTenantFromRequest(req);
  const session = resolveSessionFromRequest(req);
  const mayUseTenantlessSession = supportsTenantlessSession(segments) && session;
  if (!tenantId && !mayUseTenantlessSession && !isPublicPath(segments)) {
    return {
      status: 401,
      body: JSON.stringify({ error: "authentication required" }),
      contentType: "application/json",
    };
  }

  // ── Server-side secret — never exposed to the browser ──────────────────
  const secret = process.env.SESSION_SECRET;
  if (!secret) {
    return {
      status: 500,
      body: JSON.stringify({ detail: "Server misconfigured: SESSION_SECRET not set" }),
      contentType: "application/json",
    };
  }

  // ── Forward to FastAPI with internal auth + tenant context ─────────────
  const upstream = `${API_ORIGIN}/${segments.join("/")}${search}`;

  // Build a clean header set — do NOT forward arbitrary client headers to
  // avoid header-injection. The session cookie and CSRF token are passed
  // through so FastAPI's cookie-authenticated endpoints (auth, connections
  // management) keep working through this proxy.
  const fwdHeaders = new Headers({
    "Content-Type": req.headers?.get("content-type") ?? "application/json",
    "X-Internal-Token": secret,
  });
  if (tenantId) fwdHeaders.set("X-Tenant-ID", tenantId);
  const cookie = req.headers?.get("cookie");
  if (cookie) fwdHeaders.set("Cookie", cookie);
  const csrf = req.headers?.get("x-csrf-token");
  if (csrf) fwdHeaders.set("X-CSRF-Token", csrf);

  const upstreamRes = await fetchFn(upstream, {
    method: req.method,
    headers: fwdHeaders,
    body: req.method !== "GET" && req.method !== "HEAD" ? req.body : undefined,
    // Node's fetch requires half-duplex when forwarding a streamed body.
    ...(req.method !== "GET" && req.method !== "HEAD" ? { duplex: "half" as const } : {}),
  } as RequestInit);

  const responseHeaders: Record<string, string> = {};
  for (const headerName of SAFE_UPSTREAM_RESPONSE_HEADERS) {
    const value = upstreamRes.headers.get(headerName);
    if (value) responseHeaders[headerName] = value;
  }

  return {
    status: upstreamRes.status,
    body: await upstreamRes.arrayBuffer(),
    contentType: upstreamRes.headers.get("Content-Type") ?? "application/json",
    setCookie: upstreamRes.headers.get("set-cookie"),
    responseHeaders,
  };
}
