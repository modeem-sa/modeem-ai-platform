/**
 * Tenant resolution for the server-side proxy.
 *
 * Resolves the tenant from the authenticated session cookie (modeem_session),
 * a HS256 JWT issued by FastAPI (app/core/security.py). The token is verified
 * here with the shared signing secret so the proxy never trusts an
 * unauthenticated tenant hint.
 *
 * This module is intentionally free of next/server imports so it can be
 * unit-tested without a Next.js runtime.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** Must match SESSION_COOKIE_NAME in apps/api/app/core/security.py. */
export const SESSION_COOKIE_NAME = "modeem_session";

/** Minimal request interface needed for tenant resolution. */
export interface ResolvableRequest {
  url: string;
  headers?: { get(name: string): string | null };
}

/**
 * The JWT signing secret, mirroring FastAPI's config: AUTH_SECRET when set,
 * with a development-only fallback to SESSION_SECRET (the API applies the
 * same fallback outside production).
 */
function getAuthSecret(): string | null {
  const explicit = process.env.AUTH_SECRET;
  if (explicit) return explicit;
  if (process.env.NODE_ENV !== "production") {
    return process.env.SESSION_SECRET ?? null;
  }
  return null;
}

function base64UrlDecode(segment: string): Buffer | null {
  try {
    return Buffer.from(segment, "base64url");
  } catch {
    return null;
  }
}

/** Extract a cookie value from a raw Cookie header. */
export function getCookieValue(cookieHeader: string, name: string): string | null {
  for (const part of cookieHeader.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) {
      return part.slice(eq + 1).trim();
    }
  }
  return null;
}

interface SessionClaims {
  sub?: string;
  tid?: string;
  exp?: number;
}

/**
 * Verify an HS256 JWT and return its claims, or null when invalid/expired.
 * Mirrors decode_session_token() in FastAPI's security module.
 */
export function verifySessionToken(token: string, secret: string): SessionClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [headerB64, payloadB64, signatureB64] = parts;

  const headerBuf = base64UrlDecode(headerB64);
  const payloadBuf = base64UrlDecode(payloadB64);
  const signature = base64UrlDecode(signatureB64);
  if (!headerBuf || !payloadBuf || !signature) return null;

  let header: { alg?: string; typ?: string };
  let claims: SessionClaims;
  try {
    header = JSON.parse(headerBuf.toString("utf8"));
    claims = JSON.parse(payloadBuf.toString("utf8"));
  } catch {
    return null;
  }

  // Only the algorithm FastAPI issues — reject "none" and everything else.
  if (header.alg !== "HS256") return null;

  const expected = createHmac("sha256", secret)
    .update(`${headerB64}.${payloadB64}`)
    .digest();
  if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) {
    return null;
  }

  if (typeof claims.exp !== "number" || claims.exp <= Math.floor(Date.now() / 1000)) {
    return null;
  }
  return claims;
}

/**
 * Resolve the tenant ID for an incoming server-side request from the
 * authenticated session cookie.
 *
 * Returns `null` (→ 401 in the proxy) when there is no cookie, the token is
 * invalid or expired, or the session carries no tenant.
 */
export function resolveTenantFromRequest(req: ResolvableRequest): string | null {
  const cookieHeader = req.headers?.get("cookie");
  if (!cookieHeader) return null;

  const token = getCookieValue(cookieHeader, SESSION_COOKIE_NAME);
  if (!token) return null;

  const secret = getAuthSecret();
  if (!secret) return null;

  const claims = verifySessionToken(token, secret);
  return claims?.tid ?? null;
}
