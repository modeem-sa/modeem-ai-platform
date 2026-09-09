import { apiDownload, apiFetch } from "./api";

export type ServiceRequestPriority = "low" | "medium" | "high" | "urgent";
export type ServiceRequestStatus =
  | "open"
  | "in_progress"
  | "waiting_customer"
  | "resolved"
  | "closed";

export interface ServiceRequestMessage {
  id: string;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

export interface ServiceRequestAttachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by_id: string;
  created_at: string;
}

export interface ServiceRequestEvent {
  id: string;
  actor_id: string | null;
  event: string;
  version: number;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ServiceRequest {
  id: string;
  tenant_id: string;
  public_reference: string;
  requester_id: string;
  assigned_employee_id: string | null;
  subject: string;
  description: string;
  requested_module: string | null;
  priority: ServiceRequestPriority;
  source: "portal" | "email";
  status: ServiceRequestStatus;
  workflow_key: string | null;
  operation_task_id: string | null;
  automation_status: "none" | "queued" | "running" | "succeeded" | "failed";
  automation_result: unknown;
  automation_error: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  messages: ServiceRequestMessage[];
  attachments: ServiceRequestAttachment[];
  events?: ServiceRequestEvent[];
}

export interface RequestModule {
  id: number;
  name: string;
  shortdesc: string;
  installed_version: string | null;
  application: boolean;
  category_id: [number, string] | false | null;
  capabilities: {
    installed: boolean;
    accepts_requests: boolean;
    read_supported: boolean;
    execution_supported: boolean;
  };
}

export interface RequestModulePage {
  records: RequestModule[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface RequestAssignee {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
}

export function fetchServiceRequests(
  tenantId: string,
  employeeInbox = false,
  includeAll = false,
): Promise<{ items: ServiceRequest[] }> {
  const query = new URLSearchParams({ tenant_id: tenantId });
  if (employeeInbox && includeAll) query.set("include_all", "true");
  return apiFetch<{ items: ServiceRequest[] }>(
    `/api/v1/service-requests${employeeInbox ? "/inbox" : ""}?${query.toString()}`,
  );
}

export function fetchServiceRequest(requestId: string): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}`,
  );
}

export function createServiceRequest(payload: {
  tenant_id: string;
  subject: string;
  description: string;
  requested_module?: string;
  priority: ServiceRequestPriority;
}): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>("/api/v1/service-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchRequestModules(
  tenantId: string,
  search?: string,
): Promise<RequestModulePage> {
  const query = new URLSearchParams({ tenant_id: tenantId, limit: "50" });
  if (search) query.set("search", search);
  return apiFetch<RequestModulePage>(
    `/api/v1/service-requests/modules?${query.toString()}`,
  );
}

export function fetchRequestAssignees(
  tenantId: string,
): Promise<{ items: RequestAssignee[] }> {
  const query = new URLSearchParams({ tenant_id: tenantId });
  return apiFetch<{ items: RequestAssignee[] }>(
    `/api/v1/service-requests/assignees?${query.toString()}`,
  );
}

export function addServiceRequestMessage(
  requestId: string,
  body: string,
): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/messages`,
    { method: "POST", body: JSON.stringify({ body }) },
  );
}

export function uploadServiceRequestAttachment(
  requestId: string,
  file: File,
): Promise<ServiceRequestAttachment> {
  const body = new FormData();
  body.set("file", file);
  return apiFetch<ServiceRequestAttachment>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/attachments`,
    { method: "POST", body },
  );
}

export function changeServiceRequestStatus(
  requestId: string,
  nextStatus: ServiceRequestStatus,
  expectedVersion: number,
): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/status`,
    {
      method: "POST",
      body: JSON.stringify({ status: nextStatus, expected_version: expectedVersion }),
    },
  );
}

export function assignServiceRequest(
  requestId: string,
  assignedEmployeeId: string,
  expectedVersion: number,
): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/assignment`,
    {
      method: "POST",
      body: JSON.stringify({
        assigned_employee_id: assignedEmployeeId,
        expected_version: expectedVersion,
      }),
    },
  );
}

export function classifyServiceRequest(
  requestId: string,
  requestedModule: string,
  expectedVersion: number,
): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/classification`,
    {
      method: "POST",
      body: JSON.stringify({
        requested_module: requestedModule,
        expected_version: expectedVersion,
      }),
    },
  );
}

export function dispatchServiceRequest(
  requestId: string,
  workflowKey: string,
  expectedVersion: number,
): Promise<ServiceRequest> {
  return apiFetch<ServiceRequest>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/dispatch`,
    {
      method: "POST",
      body: JSON.stringify({
        workflow_key: workflowKey,
        workflow_input: {},
        expected_version: expectedVersion,
      }),
    },
  );
}

export async function downloadServiceRequestAttachment(
  requestId: string,
  attachment: ServiceRequestAttachment,
): Promise<void> {
  const { blob } = await apiDownload(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/attachments/${encodeURIComponent(attachment.id)}`,
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = attachment.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}