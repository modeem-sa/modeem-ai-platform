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
  const signature = createHmac("sha256", secret)
    .update(`${header}.${payload}`)
    .digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function sessionCookie(withTenant = true): string {
  const claims: Record<string, unknown> = {
    sub: "u1",
    exp: Math.floor(Date.now() / 1000) + 3600,
  };
  if (withTenant) claims.tid = TENANT_ID;
  return `${SESSION_COOKIE_NAME}=${makeToken(claims)}`;
}

function makeReq(
  url: string,
  { method = "GET", cookie = null as string | null } = {},
) {
  return {
    url,
    method,
    body: null,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "cookie" ? cookie : null,
    },
  };
}

function okFetch(capture?: { url: string; init?: RequestInit }) {
  return async (url: string | URL, init?: RequestInit): Promise<Response> => {
    if (capture) {
      capture.url = String(url);
      capture.init = init;
    }
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

describe("proxy authorization boundary", () => {
  it("blocks anonymous data requests without fetching upstream", async () => {
    let fetched = false;
    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/stats"),
      ["api", "v1", "stats"],
      "",
      (async () => {
        fetched = true;
        return new Response();
      }) as never,
    );

    assert.equal(result.status, 401);
    assert.equal(fetched, false);
  });

  it("allows anonymous login requests", async () => {
    const capture: { url: string; init?: RequestInit } = { url: "" };
    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/auth/login", { method: "POST" }),
      ["api", "v1", "auth", "login"],
      "",
      okFetch(capture) as never,
    );

    assert.equal(result.status, 200);
    assert.equal(capture.url, "http://localhost:8000/api/v1/auth/login");
  });

  it("allows the aggregate board without a selected tenant", async () => {
    const capture: { url: string; init?: RequestInit } = { url: "" };
    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/operations/board", {
        cookie: sessionCookie(false),
      }),
      ["api", "v1", "operations", "board"],
      "",
      okFetch(capture) as never,
    );

    assert.equal(result.status, 200);
    const headers = capture.init?.headers as Headers;
    assert.equal(headers.get("X-Tenant-ID"), null);
  });

  it("forwards tenant-scoped requests with trusted internal headers", async () => {
    const capture: { url: string; init?: RequestInit } = { url: "" };
    const result = await proxyRequest(
      makeReq("http://x/backend/api/v1/stats", { cookie: sessionCookie() }),
      ["api", "v1", "stats"],
      "?limit=10",
      okFetch(capture) as never,
    );

    assert.equal(result.status, 200);
    assert.equal(capture.url, "http://localhost:8000/api/v1/stats?limit=10");
    const headers = capture.init?.headers as Headers;
    assert.equal(headers.get("X-Internal-Token"), FAKE_SECRET);
    assert.equal(headers.get("X-Tenant-ID"), TENANT_ID);
  });
});

describe("binary export forwarding", () => {
  for (const testCase of [
    {
      format: "pdf",
      bytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
      contentType: "application/pdf",
    },
    {
      format: "docx",
      bytes: new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
      contentType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
  ] as const) {
    it(`preserves ${testCase.format} bytes and safe download headers`, async () => {
      const filename = `modeem-report.${testCase.format}`;
      const exportFetch = async (): Promise<Response> =>
        new Response(testCase.bytes, {
          status: 200,
          headers: {
            "Content-Type": testCase.contentType,
            "Content-Disposition": `attachment; filename="${filename}"`,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Upstream-Internal": "must-not-leak",
          },
        });

      const segments = [
        "api",
        "v1",
        "agents",
        "content-manager",
        "documents",
        "export",
        testCase.format,
      ];
      const result = await proxyRequest(
        makeReq(`http://x/backend/${segments.join("/")}`, {
          method: "POST",
          cookie: sessionCookie(),
        }),
        segments,
        "",
        exportFetch as never,
      );

      assert.equal(result.status, 200);
      assert.equal(result.contentType, testCase.contentType);
      assert.deepEqual(new Uint8Array(result.body as ArrayBuffer), testCase.bytes);
      assert.deepEqual(result.responseHeaders, {
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
    });
  }
});