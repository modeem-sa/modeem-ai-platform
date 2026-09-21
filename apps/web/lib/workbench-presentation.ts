import type { WorkbenchAction } from "./service-requests";
import type { WorkbenchCommunication } from "./service-requests";

export const workbenchStatusLabels: Record<string, { en: string; ar: string }> = {
  proposed: { en: "Proposed", ar: "مقترح" },
  awaiting_approval: { en: "Awaiting approval", ar: "بانتظار الموافقة" },
  approved: { en: "Approved · not queued", ar: "تمت الموافقة · لم يُدرج في قائمة التنفيذ" },
  queued: { en: "Queued for execution", ar: "بانتظار التنفيذ" },
  executing: { en: "Executing", ar: "قيد التنفيذ" },
  verifying: { en: "Verifying", ar: "قيد التحقق" },
  succeeded: { en: "Succeeded", ar: "نجح التنفيذ" },
  failed: { en: "Failed", ar: "فشل التنفيذ" },
};

export const communicationStatusLabels: Record<string, { en: string; ar: string }> = {
  draft: { en: "Draft", ar: "مسودة" },
  awaiting_approval: { en: "Awaiting communication approval", ar: "بانتظار موافقة التواصل" },
  approved: { en: "Approved · not queued", ar: "تمت الموافقة · لم يُدرج في قائمة التنفيذ" },
  queued: { en: "Queued for delivery", ar: "بانتظار الإرسال" },
  sending: { en: "Sending", ar: "جارٍ الإرسال" },
  verifying: { en: "Verifying delivery", ar: "جارٍ التحقق من الإرسال" },
  succeeded: { en: "Sent and verified", ar: "تم الإرسال والتحقق" },
  failed: { en: "Delivery failed", ar: "فشل الإرسال" },
};

export function getWorkbenchStatusLabel(status: WorkbenchAction["status"], locale: "ar" | "en") {
  return workbenchStatusLabels[status][locale];
}

export function hasVerifiedExecutionSuccess(action: WorkbenchAction) {
  const items = action.execution_items ?? [];
  return action.status === "succeeded"
    && items.length > 0
    && items.every((item) => item.status === "succeeded" && Boolean(item.verified_at) && item.external_activity_id != null)
    && (action.verified_count ?? 0) >= (action.target_count ?? items.length);
}

export function canPrepareCustomerCommunication(action: WorkbenchAction) {
  return hasVerifiedExecutionSuccess(action);
}

export function communicationCardIsEditable(message: WorkbenchCommunication) {
  return message.status === "draft" && message.can_edit && message.can_submit;
}

export function communicationActions(message: WorkbenchCommunication) {
  return {
    canEdit: communicationCardIsEditable(message),
    canSubmit: message.status === "draft" && message.can_submit,
    canApprove: message.status === "awaiting_approval" && message.can_approve,
    canReject: message.status === "awaiting_approval" && message.can_reject,
    canQueueDelivery: message.status === "approved" && message.can_queue_delivery,
    canRetryDelivery: message.status === "failed" && message.can_retry_delivery,
    canSend: false as const,
  };
}

export function getCommunicationStatusLabel(status: WorkbenchCommunication["status"], locale: "ar" | "en") {
  return communicationStatusLabels[status][locale];
}

export function hasVerifiedCommunicationDeliverySuccess(message: WorkbenchCommunication) {
  return message.status === "succeeded"
    && message.external_message_id != null
    && Boolean(message.verified_at);
}