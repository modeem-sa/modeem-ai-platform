import { describe, it } from 'node:test';
import assert from 'node:assert';
import { buildOperationsUrl } from '../lib/operations.ts';

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
});
