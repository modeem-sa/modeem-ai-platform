import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
  buildExactCollectionMessagePayload,
  buildExactActionPayload,
  buildOperationsUrl,
  buildOperationsCatalogUrl,
  buildFinanceReadPayload,
  getCollectionDeliveryPresentation,
  resetFinanceSelectionForModule,
  resetFinanceSelectionForTenant,
  toTaskDueAt,
  type CollectionMessage,
} from '../lib/operations.ts';

describe('Operations API Utilities', () => {
  it('should build operations URL without filters', () => {
    const url = buildOperationsUrl({});
    assert.strictEqual(url, '/api/v1/operations/board?limit=200&offset=0');
  });

  it('should build operations URL with some filters', () => {
    const url = buildOperationsUrl({
      tenant_id: 't-123',
      status: 'pending',
    });
    // URLSearchParams might order differently, so test components
    assert.ok(url.startsWith('/api/v1/operations/board?'));
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

  it('builds the association-scoped catalog URL and finance read payload', () => {
    assert.strictEqual(
      buildOperationsCatalogUrl('tenant id'),
      '/api/v1/operations/catalog?tenant_id=tenant+id',
    );
    assert.deepStrictEqual(buildFinanceReadPayload('tenant-1', 'invoices', 50, 100), {
      tenant_id: 'tenant-1',
      service: 'invoices',
      limit: 50,
      offset: 100,
    });
  });

  it('clears dependent finance selections and data when association or module changes', () => {
    const tenantSelection = resetFinanceSelectionForTenant('tenant-2');
    assert.deepStrictEqual(tenantSelection, {
      tenant_id: 'tenant-2', module_key: '', service: '', page: null,
    });
    assert.deepStrictEqual(resetFinanceSelectionForModule({
      ...tenantSelection,
      module_key: 'account',
      service: 'invoices',
      page: {} as never,
    }, 'accounting'), {
      tenant_id: 'tenant-2', module_key: 'accounting', service: '', page: null,
    });
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

  it('builds hash- and version-bound exact action payloads', () => {
    assert.deepStrictEqual(buildExactActionPayload(7, 3, 'b'.repeat(64)), {
      expected_version: 7,
      expected_action_version: 3,
      expected_proposal_hash: 'b'.repeat(64),
    });
  });

  it('builds the collection-message request with every reviewed identity field', () => {
    assert.deepStrictEqual(buildExactCollectionMessagePayload(8, {
      version: 4,
      draft_version: 2,
      draft_hash: 'c'.repeat(64),
      source_hash: 'd'.repeat(64),
      source_version: 9,
    }), {
      expected_version: 8,
      expected_message_version: 4,
      expected_draft_version: 2,
      expected_draft_hash: 'c'.repeat(64),
      expected_source_hash: 'd'.repeat(64),
      expected_source_version: 9,
    });
  });

  it('presents collection-message delivery states', () => {
    const message = {
      status: 'sending',
    } as CollectionMessage;
    assert.deepStrictEqual(getCollectionDeliveryPresentation(message), {
      state: 'sending',
      labelKey: 'opDeliverySending',
      tone: 'in_flight',
    });
    assert.strictEqual(getCollectionDeliveryPresentation({
      status: 'succeeded',
    } as CollectionMessage).tone, 'success');
  });
});
