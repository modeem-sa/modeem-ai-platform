import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { findViolations } from "../check-production-links.mjs";

function fixture() {
  return mkdtempSync(join(tmpdir(), "production-links-"));
}

function write(root, path, contents) {
  const destination = join(root, path);
  mkdirSync(join(destination, ".."), { recursive: true });
  writeFileSync(destination, contents);
}

test("detects an internal registry in package-lock", () => {
  const root = fixture();
  write(
    root,
    "apps/web/package-lock.json",
    '{"resolved":"https://package-firewall.replit.local/pkg.tgz"}',
  );

  assert.deepEqual(findViolations(root), [
    {
      path: "apps/web/package-lock.json",
      lineNumber: 1,
      hostname: "package-firewall.replit.local",
    },
  ]);
});

test("detects a Replit host in explicitly named production config", () => {
  const root = fixture();
  write(root, "deploy.production.env", "API_URL=https://api.example.replit.dev\n");
  assert.equal(findViolations(root).length, 1);
});

test("detects a Replit host serialized into the production server config", () => {
  const root = fixture();
  write(
    root,
    "apps/web/.next/required-server-files.json",
    '{"config":{"allowedDevOrigins":["preview.example.replit.dev"]}}',
  );
  assert.equal(findViolations(root, "apps/web/.next").length, 1);
});

test("ignores comments and development documentation", () => {
  const root = fixture();
  write(
    root,
    "infrastructure/docker/web.Dockerfile",
    "# Development preview: https://example.replit.dev\nFROM node:20-alpine\n",
  );
  write(root, "docs/setup.md", "Use https://example.replit.dev in development.\n");
  assert.deepEqual(findViolations(root), []);
});