import { describe, it } from 'node:test';
import assert from 'node:assert';
import { buildOperationsUrl, toTaskDueAt } from '../lib/operations.ts';

describe('Operations API Utilities', () => {
  it('should build operations URL without filters', () => {
    const url = buildOperationsUrl({});
    assert.strictEqual(url, '/api/v1/operations/tasks?limit=200&offset=0');
  });

  it('should build operations URL with some filters', () => {
    const url = buildOperationsUrl({
      tenant_id: 't-123',
      status: 'pending',
    });
    // URLSearchParams might order differently, so test components
    assert.ok(url.startsWith('/api/v1/operations/tasks?'));
    assert.ok(url.includes('limit=200'));
    assert.ok(url.includes('offset=0'));
    assert.ok(url.includes('tenant_id=t-123'));
    assert.ok(url.includes('status=pending'));
    assert.ok(!url.includes('category='));
  });

  it('should build operations URL ignoring empty string filters', () => {
    const url = buildOperationsUrl({
      status: "",
      category: "financial"
    });
    assert.ok(url.includes('category=financial'));
    assert.ok(!url.includes('status='));
  });

  it('normalizes valid task due dates without shifting the calendar day', () => {
    assert.strictEqual(toTaskDueAt('2026-08-31'), '2026-08-31T12:00:00.000Z');
    assert.strictEqual(toTaskDueAt(''), undefined);
  });

  it('rejects malformed, impossible, and expanded-year due dates', () => {
    for (const date of ['202601-01-01', '2026-02-31', '2026/01/01', '0999-01-01']) {
      assert.throws(() => toTaskDueAt(date), /INVALID_DUE_DATE/);
    }
  });
});
