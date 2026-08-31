import { readFileSync } from "node:fs";
import { test } from "node:test";
import * as assert from "node:assert";
import { fileURLToPath } from "node:url";

const pagePath = fileURLToPath(
  new URL("../app/(main)/agents/content-manager/page.tsx", import.meta.url),
);

test("content manager browser flow keeps the visible create-to-review wiring", () => {
  const page = readFileSync(pagePath, "utf8");

  // This source-level browser contract is intentionally deterministic: it
  // catches accidental removal of the user-visible controls without needing
  // provider credentials or a seeded browser session.
  assert.match(page, /data-testid="content-manager-revise"/);
  assert.match(
    page,
    /document\.getElementById\("content-manager-revision-input"\)\?\.focus\(\)/,
  );
  assert.match(page, /id="content-manager-revision-input"/);
  assert.match(page, /isRevisionRequest\(currentDocument\)/);
  assert.match(page, /aria-label=\{t\("cmSubmit"\)\}/);
});