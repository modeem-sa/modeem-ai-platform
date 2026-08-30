import { apiFetch } from "./api.ts";

export type OpStatus = 'pending' | 'in_progress' | 'completed' | 'submitted_for_approval' | 'approved' | 'rejected';
export type OpCategory = 'administrative' | 'financial';
export type OpPriority = 'low' | 'medium' | 'high' | 'urgent';
export type OpAction = 'start' | 'complete' | 'submit_for_approval' | 'approve' | 'reject';

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

export function buildOperationsUrl(filters: TaskFilters, limit = 200, offset = 0): string {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString()
  });

  if (filters.tenant_id) params.append("tenant_id", filters.tenant_id);
  if (filters.status) params.append("status", filters.status);
  if (filters.category) params.append("category", filters.category);
  if (filters.priority) params.append("priority", filters.priority);

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
