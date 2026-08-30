import { apiFetch } from "./api.ts";

export type OpStatus = 'pending' | 'in_progress' | 'completed' | 'submitted_for_approval' | 'approved' | 'rejected';
export type OpCategory = 'administrative' | 'financial';
export type OpPriority = 'low' | 'medium' | 'high' | 'urgent';
export type OpAction = 'start' | 'complete' | 'submit_for_approval' | 'approve' | 'reject';

export type OpSourceType = 'manual' | 'odoo' | 'recurring';

export interface TaskAction {
  id: string;
  status: string;
  version: number;
  proposal: Record<string, unknown>;
  proposal_hash: string;
  approved_hash: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  attempt_count: number;
  error: string | null;
  external_activity_id: number | null;
  verified_at: string | null;
}

export interface OperationTask {
  id: string;
  tenant_id: string;
  tenant_name: string;
  title: string;
  description: string | null;
  category: OpCategory;
  priority: OpPriority;
  status: OpStatus;
  assigned_user_id: string | null;
  assignee_name: string | null;
  created_by_user_id: string;
  version: number;
  due_at: string | null;
  completed_at: string | null;
  submitted_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  updated_at: string;
  available_actions: OpAction[];

  source_type: OpSourceType;
  source_connection_id: string | null;
  source_record_id: number | null;
  source_signal: string | null;
  source_reference: string | null;
  source_snapshot: Record<string, unknown> | null;
  source_sync_state: string | null;
  source_synced_at: string | null;
  action: TaskAction | null;
}

export interface TasksSummary {
  [status: string]: number;
}

export interface TasksResponse {
  items: OperationTask[];
  total: number;
  summary: TasksSummary;
}

export interface TaskFilters {
  tenant_id?: string;
  status?: OpStatus | "";
  category?: OpCategory | "";
  priority?: OpPriority | "";
  source_type?: OpSourceType | "";
}

export interface CreateTaskPayload {
  tenant_id: string;
  title: string;
  description?: string;
  category: OpCategory;
  priority: OpPriority;
  due_at?: string;
  assigned_user_id?: string;
}

export function toTaskDueAt(date: string | undefined): string | undefined {
  if (!date) return undefined;
  if (!/^(?:20\d{2}|2100)-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/.test(date)) {
    throw new Error("INVALID_DUE_DATE");
  }

  const parsed = new Date(`${date}T12:00:00.000Z`);
  if (
    Number.isNaN(parsed.getTime())
    || parsed.toISOString().slice(0, 10) !== date
  ) {
    throw new Error("INVALID_DUE_DATE");
  }
  return parsed.toISOString();
}

export function buildOperationsUrl(filters: TaskFilters, limit = 200, offset = 0): string {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString()
  });

  if (filters.tenant_id) params.append("tenant_id", filters.tenant_id);
  if (filters.status) params.append("status", filters.status);
  if (filters.category) params.append("category", filters.category);
  if (filters.priority) params.append("priority", filters.priority);
  if (filters.source_type) params.append("source_type", filters.source_type);

  return `/api/v1/operations/tasks?${params.toString()}`;
}

export interface BootstrapMember {
  id: string;
  full_name: string;
  email: string;
  role: string;
}

export interface BootstrapTenant {
  id: string;
  name: string;
  role: string;
  can_create: boolean;
  members: BootstrapMember[];
}

export interface OperationsBootstrap {
  tenants: BootstrapTenant[];
}

export async function fetchOperationsBootstrap(): Promise<OperationsBootstrap> {
  return apiFetch<OperationsBootstrap>("/api/v1/operations/bootstrap");
}

export async function fetchTasks(filters: TaskFilters): Promise<TasksResponse> {
  return apiFetch<TasksResponse>(buildOperationsUrl(filters));
}

export async function createTask(payload: CreateTaskPayload): Promise<OperationTask> {
  return apiFetch<OperationTask>("/api/v1/operations/tasks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function performTaskAction(
  id: string,
  action: OpAction,
  expectedVersion: number,
  note?: string
): Promise<OperationTask> {
  const endpoint = action.replace(/_/g, "-");
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/${endpoint}`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      note: note || undefined
    })
  });
}

export async function generateAction(id: string, expectedVersion: number): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/generate`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion })
  });
}

export async function submitAction(id: string, expectedVersion: number): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/submit`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion })
  });
}

export async function approveAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/approve`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      expected_action_version: expectedActionVersion,
      expected_proposal_hash: expectedProposalHash
    })
  });
}

export async function rejectAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/reject`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      expected_action_version: expectedActionVersion,
      expected_proposal_hash: expectedProposalHash
    })
  });
}

export async function retryAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/retry`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      expected_action_version: expectedActionVersion,
      expected_proposal_hash: expectedProposalHash
    })
  });
}

export interface RecurringTemplate {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  category: string;
  priority: string;
  frequency: string;
  timezone: string;
  enabled: boolean;
}

export interface CreateRecurringTemplatePayload {
  tenant_id: string;
  title: string;
  description?: string;
  category: string;
  priority: string;
  frequency: string;
  timezone: string;
}

export async function fetchRecurringTemplates(): Promise<RecurringTemplate[]> {
  return apiFetch<RecurringTemplate[]>("/api/v1/operations/recurring-templates");
}

export async function createRecurringTemplate(payload: CreateRecurringTemplatePayload): Promise<RecurringTemplate> {
  return apiFetch<RecurringTemplate>("/api/v1/operations/recurring-templates", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function enableRecurringTemplate(id: string, enabled: boolean): Promise<RecurringTemplate> {
  return apiFetch<RecurringTemplate>(`/api/v1/operations/recurring-templates/${id}/enable?enabled=${enabled}`, {
    method: "POST"
  });
}

export async function syncOverdueInvoices(connectionId: string): Promise<{ created: number }> {
  return apiFetch<{ created: number }>(`/api/v1/connections/${connectionId}/sync-overdue-invoices`, {
    method: "POST"
  });
}
