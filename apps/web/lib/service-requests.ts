import { apiDownload, apiFetch } from "./api";
import { collectAllModulePages } from "./module-pagination";

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
  can_use_workbench: boolean;
  messages: ServiceRequestMessage[];
  attachments: ServiceRequestAttachment[];
  events?: ServiceRequestEvent[];
}

export interface AgentMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  analysis: RequestAnalysis | null;
  created_at: string;
}

export type FinanceToolKey =
  | "finance.get_overdue_customer_invoices"
  | "finance.get_customer_invoices"
  | "finance.get_receivables_summary"
  | "finance.get_vendor_bills"
  | "finance.get_recent_payments";

export interface FinanceCurrencyTotal {
  currency_id?: number;
  currency: string;
  invoice_count?: number;
  bill_count?: number;
  payment_count?: number;
  outstanding_amount?: string;
  total_amount?: string;
  amount?: string;
  open_receivables_total?: string;
  overdue_receivables_total?: string;
  overdue_invoice_count?: number;
  aging?: Record<string, string>;
}

export interface FinanceResult {
  source: string;
  connection_name: string;
  as_of: string;
  filters_used?: Array<{ field: string; operator: string; value?: unknown }>;
  complete?: boolean;
  result_truncated?: boolean;
  needs_narrower_filter?: boolean;
  returned_count?: number;
  returned_customer_count?: number;
  totals_by_currency?: FinanceCurrencyTotal[];
  invoices?: Array<Record<string, unknown>>;
  bills?: Array<Record<string, unknown>>;
  payments?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface FinanceToolCall {
  id: string;
  tool_key: FinanceToolKey;
  mode: "read";
  status: "started" | "completed" | "failed";
  input: Record<string, unknown>;
  result: FinanceResult | null;
  error_code: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RequestAnalysis {
  request_summary: string;
  customer_goal: string;
  service_category: string;
  required_information: string[];
  missing_information: string[];
  suggested_steps: string[];
  potential_risks: string[];
  data_sources_needed: string[];
  approval_likely_required: boolean;
}

export interface AgentSession {
  id: string;
  request_id: string;
  tenant_id: string;
  employee_user_id: string;
  status: "active" | "completed" | "failed";
  provider_model: string | null;
  prompt_version: string | null;
  analysis: RequestAnalysis | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentSessionResponse {
  session: AgentSession | null;
  messages: AgentMessage[];
  tool_calls: FinanceToolCall[];
  actions: WorkbenchAction[];
}

export type WorkbenchFollowupType = "phone" | "email" | "message" | "review";

export interface WorkbenchTargetRecord {
  invoice_id: number | string;
  customer_id: number | string;
  customer: string;
  invoice_number: string;
  currency_id: number;
  currency: string;
  remaining_amount: string;
  days_overdue: number;
}

export interface WorkbenchProposal {
  action_key: "finance.prepare_collection_followup";
  approval_policy: "internal_manager";
  service_request_id: string;
  tenant_id: string;
  connection_id: string;
  company_id: number;
  source_tool_call_id: string;
  requested_source_tool_call_id: string;
  source_snapshot_hash: string;
  source_as_of: string;
  source_tool_input: Record<string, unknown>;
  target_records: WorkbenchTargetRecord[];
  totals_by_currency: FinanceCurrencyTotal[];
  followup_type: WorkbenchFollowupType;
  draft_message: string;
  internal_note: string;
  reverify_before_execution: true;
}

export interface WorkbenchAction {
  id: string;
  task_id: string;
  service_request_id: string;
  action_key: "finance.prepare_collection_followup";
  status: "proposed" | "awaiting_approval" | "approved" | "queued" | "executing" | "verifying" | "succeeded" | "failed";
  approval_policy: "internal_manager";
  proposal: WorkbenchProposal;
  proposal_hash: string;
  proposal_hash_short: string;
  approved_hash: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  prepared_by_user_id: string;
  prepared_at: string;
  updated_at: string;
  version: number;
  rejection_reason: string | null;
  not_executed: true;
  can_edit: boolean;
  can_submit: boolean;
  can_approve: boolean;
  can_reject: boolean;
  can_queue_execution?: boolean;
  can_retry_execution?: boolean;
  execution_items?: WorkbenchExecutionItem[];
  target_count?: number;
  verified_count?: number;
  last_execution_at?: string | null;
}

export interface WorkbenchExecutionItem {
  id?: string;
  invoice?: string | number;
  customer?: string;
  invoice_id?: string | number;
  status: "pending" | "executing" | "verifying" | "succeeded" | "failed";
  external_activity_id?: string | number | null;
  attempt_count: number;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  verified_at?: string | null;
  receipt?: Record<string, unknown> | null;
}

export interface WorkbenchCommunicationInvoice {
  invoice_id: number | string;
  invoice_number?: string;
  customer?: string;
  currency?: string;
  remaining_amount?: string;
  currency_id?: number | string;
  [key: string]: unknown;
}

export type WorkbenchCommunicationStatus = "draft" | "awaiting_approval";

export interface WorkbenchCommunication {
  id: string;
  service_request_id: string;
  action_id: string;
  partner_id: number;
  customer?: string;
  company_id: number;
  invoice_ids: Array<number | string>;
  invoice_records: WorkbenchCommunicationInvoice[];
  status: WorkbenchCommunicationStatus;
  policy_state: string;
  prepared_by: string;
  prepared_at: string;
  source: string;
  version: number;
  draft_content: string;
  draft_version: number;
  draft_hash: string;
  source_hash: string;
  source_version: number;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
  can_edit: boolean;
  can_submit: boolean;
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
  authorized?: boolean;
}

export interface RequestModulePage {
  records: RequestModule[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface ModuleInventorySummary {
  installed: number;
  applications: number;
  technical: number;
  visible_to_user: number;
  read_supported: number;
  execution_supported: number;
}

export interface ModuleInventoryPage extends RequestModulePage {
  summary: ModuleInventorySummary;
  connection: { id: string; name: string };
}

export interface ModuleInventory {
  records: RequestModule[];
  summary: ModuleInventorySummary;
  connection: { id: string; name: string };
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

export function fetchAgentSession(requestId: string): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/session`,
  );
}

export function startAgentSession(
  requestId: string,
  locale: "ar" | "en",
): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/session`,
    { method: "POST", body: JSON.stringify({ locale }) },
  );
}

export function analyzeServiceRequest(
  requestId: string,
  locale: "ar" | "en",
): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/analyze`,
    { method: "POST", body: JSON.stringify({ locale }) },
  );
}

export function sendAgentMessage(
  requestId: string,
  content: string,
  locale: "ar" | "en",
): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/messages`,
    { method: "POST", body: JSON.stringify({ content, locale }) },
  );
}

export function executeOverdueInvoiceTool(
  requestId: string,
  locale: "ar" | "en",
  minimumDaysOverdue = 30,
): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/tools/execute`,
    {
      method: "POST",
      body: JSON.stringify({
        tool_key: "finance.get_overdue_customer_invoices",
        input: {
          minimum_days_overdue: minimumDaysOverdue,
          max_records: 100,
        },
        locale,
      }),
    },
  );
}

export function executeFinanceTool(
  requestId: string,
  locale: "ar" | "en",
  toolKey: FinanceToolKey,
  input: Record<string, unknown> = {},
): Promise<AgentSessionResponse> {
  return apiFetch<AgentSessionResponse>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/tools/execute`,
    {
      method: "POST",
      body: JSON.stringify({ tool_key: toolKey, input, locale }),
    },
  );
}

export function prepareWorkbenchAction(
  requestId: string,
  sourceToolCallId: string,
  locale: "ar" | "en",
): Promise<{ action: WorkbenchAction; session: AgentSessionResponse }> {
  return apiFetch<{ action: WorkbenchAction; session: AgentSessionResponse }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/prepare`,
    { method: "POST", body: JSON.stringify({ source_tool_call_id: sourceToolCallId, locale }) },
  );
}

export function updateWorkbenchAction(
  requestId: string,
  actionId: string,
  body: {
    expected_action_version: number;
    expected_proposal_hash: string;
    draft_message: string;
    internal_note: string;
    followup_type: WorkbenchFollowupType;
  },
): Promise<{ action: WorkbenchAction }> {
  return apiFetch<{ action: WorkbenchAction }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

function transitionWorkbenchAction(
  requestId: string,
  actionId: string,
  transition: "submit" | "approve" | "reject",
  body: { expected_action_version: number; expected_proposal_hash: string; rejection_reason?: string },
): Promise<{ action: WorkbenchAction }> {
  return apiFetch<{ action: WorkbenchAction }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}/${transition}`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export const submitWorkbenchAction = (
  requestId: string, actionId: string, expected_action_version: number, expected_proposal_hash: string,
) => transitionWorkbenchAction(requestId, actionId, "submit", { expected_action_version, expected_proposal_hash });

export const approveWorkbenchAction = (
  requestId: string, actionId: string, expected_action_version: number, expected_proposal_hash: string,
) => transitionWorkbenchAction(requestId, actionId, "approve", { expected_action_version, expected_proposal_hash });

export const rejectWorkbenchAction = (
  requestId: string, actionId: string, expected_action_version: number, expected_proposal_hash: string, rejection_reason: string,
) => transitionWorkbenchAction(requestId, actionId, "reject", { expected_action_version, expected_proposal_hash, rejection_reason });

export const queueWorkbenchAction = (
  requestId: string, actionId: string, expected_action_version: number, expected_proposal_hash: string,
) => apiFetch<{ action: WorkbenchAction }>(
  `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}/queue`,
  { method: "POST", body: JSON.stringify({ expected_action_version, expected_proposal_hash }) },
);

export const retryWorkbenchAction = (
  requestId: string, actionId: string, expected_action_version: number, expected_proposal_hash: string,
) => apiFetch<{ action: WorkbenchAction }>(
  `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}/retry`,
  { method: "POST", body: JSON.stringify({ expected_action_version, expected_proposal_hash }) },
);

export function fetchWorkbenchCommunications(
  requestId: string,
  actionId: string,
): Promise<{ messages: WorkbenchCommunication[] }> {
  return apiFetch<{ messages: WorkbenchCommunication[] }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}/communications`,
  );
}

export function prepareWorkbenchCommunications(
  requestId: string,
  actionId: string,
  locale: "ar" | "en",
): Promise<{ messages: WorkbenchCommunication[] }> {
  return apiFetch<{ messages: WorkbenchCommunication[] }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/actions/${encodeURIComponent(actionId)}/communications/prepare`,
    { method: "POST", body: JSON.stringify({ locale }) },
  );
}

export function updateWorkbenchCommunication(
  requestId: string,
  messageId: string,
  body: {
    expected_message_version: number;
    expected_draft_version: number;
    expected_draft_hash: string;
    expected_source_version: number;
    expected_source_hash: string;
    content: string;
  },
): Promise<{ message: WorkbenchCommunication }> {
  return apiFetch<{ message: WorkbenchCommunication }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/communications/${encodeURIComponent(messageId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export function submitWorkbenchCommunication(
  requestId: string,
  messageId: string,
  body: {
    expected_message_version: number;
    expected_draft_version: number;
    expected_draft_hash: string;
    expected_source_version: number;
    expected_source_hash: string;
  },
): Promise<{ message: WorkbenchCommunication }> {
  return apiFetch<{ message: WorkbenchCommunication }>(
    `/api/v1/service-requests/${encodeURIComponent(requestId)}/agent/communications/${encodeURIComponent(messageId)}/submit`,
    { method: "POST", body: JSON.stringify(body) },
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
  limit = 50,
  offset = 0,
): Promise<RequestModulePage> {
  const query = new URLSearchParams({
    tenant_id: tenantId,
    limit: String(limit),
    offset: String(offset),
  });
  if (search) query.set("search", search);
  return apiFetch<RequestModulePage>(
    `/api/v1/service-requests/modules?${query.toString()}`,
  );
}

export function fetchAllRequestModules(
  tenantId: string,
  search?: string,
): Promise<RequestModule[]> {
  return collectAllModulePages((offset) =>
    fetchRequestModules(tenantId, search, 50, offset),
  );
}

export function fetchModuleInventoryPage(
  tenantId: string,
  search?: string,
  limit = 50,
  offset = 0,
): Promise<ModuleInventoryPage> {
  const query = new URLSearchParams({
    tenant_id: tenantId,
    limit: String(limit),
    offset: String(offset),
  });
  if (search) query.set("search", search);
  return apiFetch<ModuleInventoryPage>(
    `/api/v1/service-requests/modules/inventory?${query.toString()}`,
  );
}

export async function fetchAllModuleInventory(
  tenantId: string,
  search?: string,
): Promise<ModuleInventory> {
  let metadata: Pick<ModuleInventory, "summary" | "connection"> | null = null;
  const records = await collectAllModulePages(async (offset) => {
    const page = await fetchModuleInventoryPage(tenantId, search, 50, offset);
    metadata ??= { summary: page.summary, connection: page.connection };
    return page;
  });
  if (!metadata) throw new Error("Module inventory metadata is missing");
  const resolvedMetadata = metadata as Pick<
    ModuleInventory,
    "summary" | "connection"
  >;
  return { records, ...resolvedMetadata };
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