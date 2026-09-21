import { describe, it } from "node:test";
import assert from "node:assert";
import { communicationActions, communicationCardIsEditable, getWorkbenchStatusLabel, hasVerifiedExecutionSuccess } from "../lib/workbench-presentation.ts";
import { approveWorkbenchCommunication, rejectWorkbenchCommunication } from "../lib/service-requests.ts";
import type { WorkbenchAction, WorkbenchCommunication } from "../lib/service-requests.ts";

const action = (overrides: Partial<WorkbenchAction> = {}): WorkbenchAction => ({
  id: "a", task_id: "t", service_request_id: "r", action_key: "finance.prepare_collection_followup",
  status: "succeeded", approval_policy: "internal_manager",
  proposal: {} as WorkbenchAction["proposal"], proposal_hash: "h", proposal_hash_short: "h",
  approved_hash: "h", approved_by_user_id: "u", approved_at: null, prepared_by_user_id: "u",
  prepared_at: "", updated_at: "", version: 2, rejection_reason: null, not_executed: true,
  can_edit: false, can_submit: false, can_approve: false, can_reject: false,
  ...overrides,
});

const communication = (overrides: Partial<WorkbenchCommunication> = {}): WorkbenchCommunication => ({
  id: "message-a",
  service_request_id: "request-a",
  action_id: "action-a",
  partner_id: 10,
  customer: "Customer A",
  company_id: 1,
  invoice_ids: [42],
  invoice_records: [{ invoice_id: 42, invoice_number: "INV/42", currency: "SAR", remaining_amount: "100.00" }],
  status: "draft",
  policy_state: "allowed",
  prepared_by: "user-a",
  prepared_at: "2026-01-01T00:00:00Z",
  source: "Verified Phase 4B Odoo execution",
  version: 1,
  draft_content: "رسالة تحصيل",
  draft_version: 1,
  draft_hash: "a".repeat(64),
  source_hash: "b".repeat(64),
  source_version: 1,
  submitted_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  can_edit: true,
  can_submit: true,
  can_approve: false,
  can_reject: false,
  ...overrides,
});

describe("Workbench execution presentation", () => {
  it("uses the queued-only bilingual state", () => {
    assert.strictEqual(getWorkbenchStatusLabel("queued", "en"), "Queued for execution");
    assert.strictEqual(getWorkbenchStatusLabel("queued", "ar"), "بانتظار التنفيذ");
  });

  it("requires succeeded action and verified receipts before success copy", () => {
    const verified = action({
      target_count: 1, verified_count: 1,
      execution_items: [{ invoice_id: 42, status: "succeeded", attempt_count: 1, external_activity_id: 9, verified_at: "2026-01-01T00:00:00Z" }],
    });
    assert.strictEqual(hasVerifiedExecutionSuccess(verified), true);
    assert.strictEqual(hasVerifiedExecutionSuccess({ ...verified, status: "queued" }), false);
    assert.strictEqual(hasVerifiedExecutionSuccess({ ...verified, verified_count: 0 }), false);
    assert.strictEqual(hasVerifiedExecutionSuccess({ ...verified, execution_items: [{ ...verified.execution_items![0], verified_at: null }] }), false);
  });

  it("allows preparation only after a fully verified Workbench success", () => {
    const verified = action({
      target_count: 1, verified_count: 1,
      execution_items: [{ invoice_id: 42, status: "succeeded", attempt_count: 1, external_activity_id: 9, verified_at: "2026-01-01T00:00:00Z" }],
    });
    assert.strictEqual(hasVerifiedExecutionSuccess(verified), true);
    assert.strictEqual(hasVerifiedExecutionSuccess({ ...verified, status: "approved" }), false);
    assert.strictEqual(hasVerifiedExecutionSuccess({ ...verified, verified_count: 0 }), false);
  });

  it("makes submitted cards non-editable and exposes no send action", () => {
    const submitted = communication({ status: "awaiting_approval", can_edit: false, can_submit: false, submitted_at: "2026-01-01T00:00:00Z" });
    assert.strictEqual(communicationCardIsEditable(submitted), false);
    assert.deepStrictEqual(communicationActions(submitted), { canEdit: false, canSubmit: false, canApprove: false, canReject: false, canSend: false });
  });

  it("uses only server-issued communication approval capabilities", () => {
    const awaiting = communication({
      status: "awaiting_approval",
      can_edit: false,
      can_submit: false,
      can_approve: true,
      can_reject: true,
      submitted_at: "2026-01-01T00:00:00Z",
    });
    assert.deepStrictEqual(communicationActions(awaiting), {
      canEdit: false,
      canSubmit: false,
      canApprove: true,
      canReject: true,
      canSend: false,
    });
    assert.deepStrictEqual(communicationActions({
      ...awaiting,
      can_approve: false,
      can_reject: false,
    }), {
      canEdit: false,
      canSubmit: false,
      canApprove: false,
      canReject: false,
      canSend: false,
    });
  });

  it("keeps approved messages non-editable and delivery-free", () => {
    const approved = communication({
      status: "approved",
      can_edit: false,
      can_submit: false,
      can_approve: false,
      can_reject: false,
      approved_hash: "c".repeat(64),
    });
    assert.strictEqual(communicationCardIsEditable(approved), false);
    assert.strictEqual(communicationActions(approved).canSend, false);
    assert.strictEqual(communicationActions(approved).canApprove, false);
    assert.strictEqual(communicationActions(approved).canReject, false);
  });

  it("sends only optimistic-concurrency evidence for approval and rejection", async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    globalThis.fetch = async (input, init) => {
      requests.push({
        url: String(input),
        method: String(init?.method),
        body: JSON.parse(String(init?.body)),
      });
      return new Response(JSON.stringify({ message: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    const evidence = {
      expected_message_version: 3,
      expected_draft_version: 2,
      expected_draft_hash: "a".repeat(64),
      expected_source_version: 1,
      expected_source_hash: "b".repeat(64),
    };
    try {
      await approveWorkbenchCommunication("request/1", "message/1", evidence);
      await rejectWorkbenchCommunication("request/1", "message/1", { ...evidence, rejection_reason: "Please revise the tone." });
    } finally {
      globalThis.fetch = originalFetch;
    }
    assert.deepStrictEqual(requests, [
      {
        url: "/backend/api/v1/service-requests/request%2F1/agent/communications/message%2F1/approve",
        method: "POST",
        body: evidence,
      },
      {
        url: "/backend/api/v1/service-requests/request%2F1/agent/communications/message%2F1/reject",
        method: "POST",
        body: { ...evidence, rejection_reason: "Please revise the tone." },
      },
    ]);
  });

  it("keeps one communication card per server-derived customer", () => {
    const messages = [
      communication({ id: "message-a", partner_id: 10, customer: "Customer A" }),
      communication({ id: "message-b", partner_id: 20, customer: "Customer B" }),
    ];
    const cards = messages.map((message) => `${message.partner_id}:${message.id}`);
    assert.deepStrictEqual(cards, ["10:message-a", "20:message-b"]);
    assert.notStrictEqual(messages[0].partner_id, messages[1].partner_id);
  });
});