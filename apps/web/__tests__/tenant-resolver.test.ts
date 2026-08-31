/**
 * Unit tests for session-based tenant resolution.
 * Run with: node --experimental-strip-types --test
 *
 * Tokens are minted here with the same HS256 scheme FastAPI uses
 * (app/core/security.py), so verification is tested end-to-end.
 */

import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

// Relative import — no @/ alias (not resolved by the node loader)
import {
  SESSION_COOKIE_NAME,
  getCookieValue,
  resolveTenantFromRequest,
  resolveSessionFromRequest,
  verifySessionToken,
} from "../lib/tenant-resolver.ts";

const SECRET = "test-auth-secret-value";
const TENANT_ID = "11111111-2222-3333-4444-555555555555";

const savedAuth = process.env.AUTH_SECRET;
const savedSession = process.env.SESSION_SECRET;
before(() => {
  process.env.AUTH_SECRET = SECRET;
});
after(() => {
  process.env.AUTH_SECRET = savedAuth;
  process.env.SESSION_SECRET = savedSession;
});

function b64url(data: Buffer | string): string {
  return Buffer.from(data).toString("base64url");
}

function makeToken(
  claims: Record<string, unknown>,
  { secret = SECRET, alg = "HS256" }: { secret?: string; alg?: string } = {},
): string {
  const header = b64url(JSON.stringify({ alg, typ: "JWT" }));
  const payload = b64url(JSON.stringify(claims));
  const sig = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${sig}`;
}

function futureExp(): number {
  return Math.floor(Date.now() / 1000) + 3600;
}

function reqWithCookie(cookie: string | null) {
  return {
    url: "http://localhost/backend/api/v1/stats",
    headers: { get: (n: string) => (n.toLowerCase() === "cookie" ? cookie : null) },
  };
}

describe("verifySessionToken", () => {
  it("accepts a valid HS256 token and returns claims", () => {
    const token = makeToken({ sub: "u1", tid: TENANT_ID, exp: futureExp() });
    const claims = verifySessionToken(token, SECRET);
    assert.equal(claims?.tid, TENANT_ID);
  });

  it("rejects a token signed with the wrong secret", () => {
    const token = makeToken({ tid: TENANT_ID, exp: futureExp() }, { secret: "other" });
    assert.equal(verifySessionToken(token, SECRET), null);
  });

  it("rejects an expired token", () => {
    const token = makeToken({ tid: TENANT_ID, exp: Math.floor(Date.now() / 1000) - 10 });
    assert.equal(verifySessionToken(token, SECRET), null);
  });

  it("rejects a token without exp", () => {
    const token = makeToken({ tid: TENANT_ID });
    assert.equal(verifySessionToken(token, SECRET), null);
  });

  it("rejects alg=none tokens", () => {
    const header = b64url(JSON.stringify({ alg: "none", typ: "JWT" }));
    const payload = b64url(JSON.stringify({ tid: TENANT_ID, exp: futureExp() }));
    assert.equal(verifySessionToken(`${header}.${payload}.`, SECRET), null);
  });

  it("rejects tampered payloads", () => {
    const token = makeToken({ tid: TENANT_ID, exp: futureExp() });
    const [h, , s] = token.split(".");
    const forged = b64url(JSON.stringify({ tid: "attacker", exp: futureExp() }));
    assert.equal(verifySessionToken(`${h}.${forged}.${s}`, SECRET), null);
  });

  it("rejects malformed tokens", () => {
    assert.equal(verifySessionToken("not-a-jwt", SECRET), null);
    assert.equal(verifySessionToken("a.b", SECRET), null);
    assert.equal(verifySessionToken("", SECRET), null);
  });
});

describe("getCookieValue", () => {
  it("extracts the named cookie among several", () => {
    const header = `foo=1; ${SESSION_COOKIE_NAME}=abc.def.ghi; bar=2`;
    assert.equal(getCookieValue(header, SESSION_COOKIE_NAME), "abc.def.ghi");
  });

  it("returns null when absent", () => {
    assert.equal(getCookieValue("foo=1; bar=2", SESSION_COOKIE_NAME), null);
  });
});

describe("resolveTenantFromRequest", () => {
  it("returns the tenant from a valid session cookie", () => {
    const token = makeToken({ sub: "u1", tid: TENANT_ID, exp: futureExp() });
    const req = reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`);
    assert.equal(resolveTenantFromRequest(req), TENANT_ID);
  });

  it("returns null for anonymous requests (no cookie header)", () => {
    assert.equal(resolveTenantFromRequest(reqWithCookie(null)), null);
  });

  it("returns null when the session cookie is missing", () => {
    assert.equal(resolveTenantFromRequest(reqWithCookie("other=1")), null);
  });

  it("returns null for an invalid/forged token", () => {
    const token = makeToken({ tid: TENANT_ID, exp: futureExp() }, { secret: "wrong" });
    assert.equal(resolveTenantFromRequest(reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`)), null);
  });

  it("returns null for a session without a tenant claim", () => {
    const token = makeToken({ sub: "u1", exp: futureExp() });
    assert.equal(resolveTenantFromRequest(reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`)), null);
  });

  it("falls back to SESSION_SECRET outside production when AUTH_SECRET unset", () => {
    const prevAuth = process.env.AUTH_SECRET;
    const prevSession = process.env.SESSION_SECRET;
    try {
      delete (process.env as Record<string, string | undefined>).AUTH_SECRET;
      process.env.SESSION_SECRET = SECRET;
      const token = makeToken({ sub: "u1", tid: TENANT_ID, exp: futureExp() });
      assert.equal(
        resolveTenantFromRequest(reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`)),
        TENANT_ID,
      );
    } finally {
      process.env.AUTH_SECRET = prevAuth;
      process.env.SESSION_SECRET = prevSession;
    }
  });
});

describe("resolveSessionFromRequest", () => {
  it("accepts an authenticated multi-membership session without a tenant", () => {
    const token = makeToken({ sub: "u1", exp: futureExp() });
    const session = resolveSessionFromRequest(
      reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`),
    );
    assert.equal(session?.sub, "u1");
    assert.equal(session?.tid, undefined);
  });

  it("rejects a signed token without a user identity", () => {
    const token = makeToken({ exp: futureExp() });
    assert.equal(
      resolveSessionFromRequest(reqWithCookie(`${SESSION_COOKIE_NAME}=${token}`)),
      null,
    );
  });
});
