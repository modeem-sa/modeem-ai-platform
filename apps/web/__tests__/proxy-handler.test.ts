/**
 * Tests for the proxy authorization boundary and upstream forwarding.
 *
 * proxy-handler.ts has no next/server dependency (returns ProxyResult, not
 * NextResponse), so these tests run with plain node:test — no mocking needed.
 *
 * Run with: node --experimental-strip-types --test '__tests__/**\/*.test.ts'
 */

import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import { proxyRequest } from "../lib/proxy-handler.ts";
import { SESSION_COOKIE_NAME } from "../lib/tenant-resolver.ts";

const FAKE_SECRET = "test-session-secret-value";
const AUTH_SECRET = "test-auth-secret-value";
const TENANT_ID = "11111111-2222-3333-4444-555555555555";

function b64url(data: string): string {
  return Buffer.from(data).toString("base64url");
}

function makeToken(claims: Record<string, unknown>, secret = AUTH_SECRET): string {
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(JSON.stringify(claims));
  const sig = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${sig}`;
}

function validSessionCookie(): string {
  const token = makeToken({
    sub: "u1",
    tid: TENANT_ID,
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
  return `${SESSION_COOKIE_NAME}=${token}`;
}

// ── Minimal request stub — satisfies ProxyableRequest ─────────────────────
function makeReq(url: string, { method = "GET", cookie = null as string | null } = {}) {
  const headerMap: Record<string, string | null> = { cookie };
  return {
    url,
    method,
    body: null,
    headers: { get: (n: string) => headerMap[n.toLowerCase()] ?? null },
  };
}

// ── Fake upstream that returns a 200 JSON response ─────────────────────────
function okFetch(captureUrl?: { value: string }, captureInit?: { value: RequestInit }) {
  return async (url: string | URL, init?: RequestInit): Promise<Response> => {
    if (captureUrl) captureUrl.value = String(url);
    if (captureInit) captureInit.value = init ?? {};
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}

const savedSecret = process.env.SESSION_SECRET;
const savedAuth = process.env.AUTH_SECRET;

before(() => {
  process.env.SESSION_SECRET = FAKE_SECRET;
  process.env.AUTH_SECRET = AUTH_SECRET;
});
after(() => {
  process.env.SESSION_SECRET = savedSecret;
  process.env.AUTH_SECRET = savedAuth;
});

// ── Authorization boundary ─────────────────────────────────────────────────

describe("authorization boundary — anonymous requests", () => {
  it("returns 401 without calling fetchFn when no session cookie", async () => {
    let fetched = false;
    const neverFetch = async () => { fetched = true; return new Response(); };

    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/stats"),
      ["api", "v1", "stats"],
      "",
      neverFetch as never,
    );

    assert.equal(result.status, 401);
    assert.deepEqual(JSON.parse(Buffer.from(result.body as string).toString()), {
      error: "authentication required",
    });
    assert.equal(fetched, false, "fetch must not be called for anonymous data requests");
  });

  it("blocks all data paths without fetching", async () => {
    let fetchCalls = 0;
    const neverFetch = async () => { fetchCalls++; return new Response(); };

    for (const [segs, qs] of [
      [["api", "v1", "stats"], ""],
      [["api", "v1", "connections"], "?limit=50"],
      [["api", "v1", "audit-logs"], ""],
      [["api", "v1", "workflows"], ""],
      [["api", "v1", "executions"], ""],
    ] as Array<[string[], string]>) {
      const r = await proxyRequest(makeReq(`http://x/${segs.join("/")}`), segs, qs, neverFetch as never);
      assert.equal(r.status, 401, `/${segs.join("/")} must be 401`);
    }
    assert.equal(fetchCalls, 0);
  });

  it("rejects a forged session cookie", async () => {
    const forged = makeToken(
      { tid: TENANT_ID, exp: Math.floor(Date.now() / 1000) + 3600 },
      "attacker-secret",
    );
    let fetched = false;
    const neverFetch = async () => { fetched = true; return new Response(); };

    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/stats", { cookie: `${SESSION_COOKIE_NAME}=${forged}` }),
      ["api", "v1", "stats"],
      "",
      neverFetch as never,
    );
    assert.equal(result.status, 401);
    assert.equal(fetched, false);
  });

  it("forwards anonymous auth requests (login must be reachable)", async () => {
    const url = { value: "" };
    const init = { value: {} as RequestInit };

    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/auth/login", { method: "POST" }),
      ["api", "v1", "auth", "login"],
      "",
      okFetch(url, init) as never,
    );

    assert.equal(result.status, 200);
    assert.equal(url.value, "http://localhost:8000/api/v1/auth/login");
    const headers = init.value.headers as Headers;
    assert.equal(headers.get("X-Internal-Token"), FAKE_SECRET);
    assert.equal(headers.get("X-Tenant-ID"), null, "no tenant header for anonymous auth");
  });
});

// ── Authenticated forwarding ───────────────────────────────────────────────

describe("authenticated session — upstream forwarding", () => {
  it("forwards with internal auth headers and the session's tenant", async () => {
    const url = { value: "" };
    const init = { value: {} as RequestInit };

    const result = await proxyRequest(
      makeReq("http://localhost/backend/api/v1/stats", { cookie: validSessionCookie() }),
      ["api", "v1", "stats"],
      "",
      okFetch(url, init) as never,
    );

    assert.equal(result.status, 200);
    assert.equal(url.value, "http://localhost:8000/api/v1/stats");

    const headers = init.value.headers as Headers;
    assert.equal(headers.get("X-Internal-Token"), FAKE_SECRET);
    assert.equal(headers.get("X-Tenant-ID"), TENANT_ID);
    assert.equal(headers.get("Content-Type"), "application/json");
  });

  it("appends query string to upstream URL", async () => {
    const url = { value: "" };

    await proxyRequest(
      makeReq("http://localhost/backend/api/v1/connections?limit=10&offset=5", {
        cookie: validSessionCookie(),
      }),
      ["api", "v1", "connections"],
      "?limit=10&offset=5",
      okFetch(url) as never,
    );

    assert.equal(url.value, "http://localhost:8000/api/v1/connections?limit=10&offset=5");
  });

  it("returns 500 and does not fetch when SESSION_SECRET is absent", async () => {
    process.env.SESSION_SECRET = "";
    let fetched = false;
    const neverFetch = async () => { fetched = true; return new Response(); };

    try {
      const result = await proxyRequest(
        makeReq("http://localhost/backend/api/v1/stats", { cookie: validSessionCookie() }),
        ["api", "v1", "stats"],
        "",
        neverFetch as never,
      );
      assert.equal(result.status, 500);
      assert.equal(fetched, false);
    } finally {
      process.env.SESSION_SECRET = FAKE_SECRET;
    }
  });
});
