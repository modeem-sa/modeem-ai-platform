import { describe, it } from "node:test";
import assert from "node:assert";
import { collectAllModulePages } from "../lib/module-pagination.ts";

type Module = { id: number; name: string };

function pagedInventory(total: number, duplicateBoundary = false) {
  const modules = Array.from({ length: total }, (_, index) => ({
    id: index + 1,
    name: `module_${String(index + 1).padStart(3, "0")}`,
  }));
  return async (offset: number) => {
    const start = duplicateBoundary && offset > 0 ? offset - 1 : offset;
    const records = modules.slice(start, offset + 50);
    const nextOffset = Math.min(offset + 50, total);
    return {
      records,
      offset,
      returned_count: records.length,
      has_more: nextOffset < total,
      next_offset: nextOffset < total ? nextOffset : null,
    };
  };
}

describe("complete Odoo module pagination", () => {
  for (const total of [10, 50, 51, 137]) {
    it(`loads all ${total} installed modules`, async () => {
      const result = await collectAllModulePages(pagedInventory(total));
      assert.strictEqual(result.length, total);
      assert.strictEqual(new Set(result.map((item) => item.name)).size, total);
    });
  }

  it("deduplicates records repeated across page boundaries", async () => {
    const result = await collectAllModulePages(pagedInventory(137, true));
    assert.strictEqual(result.length, 137);
  });

  it("rejects a non-advancing next offset instead of returning partial data", async () => {
    await assert.rejects(
      collectAllModulePages(async (offset) => ({
        records: [{ id: 1, name: "base" }],
        offset,
        returned_count: 1,
        has_more: true,
        next_offset: offset,
      })),
      /did not advance/,
    );
  });

  it("rejects repeated or mismatched offsets", async () => {
    await assert.rejects(
      collectAllModulePages(async () => ({
        records: [],
        offset: 999,
        returned_count: 0,
        has_more: false,
        next_offset: null,
      })),
      /response/,
    );
  });
});