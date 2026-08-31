import { test } from "node:test";
import * as assert from "node:assert";
import { 
  buildDocumentRequest, 
  buildFormSubmitRequest, 
  formatFormDataAsMessage,
  isRevisionRequest,
  type Message 
} from "../lib/content-manager-utils.ts";

test("content-manager-utils", async (t) => {
  await t.test("buildDocumentRequest - new document", () => {
    const messages: Message[] = [];
    const payload = buildDocumentRequest({
      requestText: "Draft a proposal",
      currentDocument: null,
      activeDocumentType: null,
      latestCorrection: null,
      isRevision: false,
      messages,
    });
    
    assert.deepStrictEqual(payload, {
      original_request: "Draft a proposal",
      current_document: null,
      active_document_type: null,
      latest_correction: null,
      conversation_messages: [],
    });
  });

  await t.test("buildDocumentRequest - revision", () => {
    const messages: Message[] = [{ role: "user", content: "Initial request" }];
    const payload = buildDocumentRequest({
      documentId: "7f60d3fc-d6d6-4695-9ddd-3f0d9c5e40f0",
      requestText: "Make it shorter",
      originalRequest: "Draft an internal memo",
      currentDocument: "Document content...",
      activeDocumentType: "memo",
      latestCorrection: "Old correction",
      isRevision: true,
      messages,
    });
    
    assert.deepStrictEqual(payload, {
      document_id: "7f60d3fc-d6d6-4695-9ddd-3f0d9c5e40f0",
      original_request: "Draft an internal memo",
      current_document: "Document content...",
      active_document_type: "memo",
      latest_correction: "Make it shorter", // should use the requestText since isRevision is true
      conversation_messages: messages,
    });
  });

  await t.test("buildFormSubmitRequest", () => {
    const messages: Message[] = [{ role: "user", content: "Initial request" }];
    const payload = buildFormSubmitRequest({
      originalRequest: "Initial request",
      formData: { purpose: "Fundraising", audience: "Investors" },
      currentDocument: null,
      activeDocumentType: null,
      latestCorrection: null,
      messages,
    });
    
    assert.deepStrictEqual(payload, {
      original_request: "Initial request",
      provided_fields: { purpose: "Fundraising", audience: "Investors" },
      current_document: null,
      active_document_type: null,
      latest_correction: null,
      conversation_messages: messages,
    });
  });

  await t.test("formatFormDataAsMessage", () => {
    const result1 = formatFormDataAsMessage({ purpose: "Fundraising", audience: "Investors" });
    assert.strictEqual(result1, "Provided info: purpose: Fundraising, audience: Investors");

    const result2 = formatFormDataAsMessage({ purpose: "  ", audience: "" });
    assert.strictEqual(result2, "Provided info: (empty)");
  });

  await t.test("derives the same revision mode for keyboard and form submission", () => {
    assert.strictEqual(isRevisionRequest(null), false);
    assert.strictEqual(isRevisionRequest("Existing document"), true);
  });
});
