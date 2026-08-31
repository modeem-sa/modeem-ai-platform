/**
 * Thin fetch wrapper for the Modeem API.
 *
 * Base URL for apiFetch (dashboard/list data). Resolution order:
 *  1. NEXT_PUBLIC_API_BASE_URL — set in .env.local for a stand-alone
 *     deployment where the API is on a different host.
 *  2. "/backend" — default; matched by the Next.js server-side rewrite
 *     /backend/:path* → FastAPI, so the user's browser never needs to
 *     reach localhost:8000 directly. Callers pass full "/api/v1/..." paths.
 */
const FETCH_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "/backend";

export class ApiError extends Error {
  public readonly status: number;
  constructor(
    status: number,
    message: string,
  ) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function apiErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const item = detail as { error_code?: unknown; message?: unknown };
    if (typeof item.error_code === "string") return item.error_code;
    if (typeof item.message === "string") return item.message;
  }
  if (!Array.isArray(detail)) return null;

  const messages = detail.flatMap((issue) => {
    if (!issue || typeof issue !== "object") return [];
    const item = issue as { loc?: unknown; msg?: unknown };
    if (typeof item.msg !== "string") return [];
    const location = Array.isArray(item.loc)
      ? item.loc.filter((part) => part !== "body").join(".")
      : "";
    return [location ? `${location}: ${item.msg}` : item.msg];
  });

  return messages.length ? messages.join("; ") : null;
}

function csrfHeader(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const match = document.cookie.match(/(?:^|;\s*)modeem_csrf=([^;]+)/);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    for (const [key, value] of Object.entries(csrfHeader())) headers.set(key, value);
  }

  const res = await fetch(`${FETCH_BASE}${path}`, {
    ...init,
    headers,
    credentials: init.credentials || "same-origin",
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const payload = (await res.json()) as { detail?: unknown };
      detail = apiErrorDetail(payload.detail) || detail;
    } catch {
      // Keep the safe status text when the upstream did not return JSON.
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = disposition.match(/filename="([a-zA-Z0-9._-]+)"/);
  return match?.[1] ?? null;
}
export interface ListResponse<T> {
  items: T[];
  total: number;
}

export interface Stats {
  active_workflows: number;
  successful_executions: number;
  failed_executions: number;
  connected_systems: number;
}

export type OperationsWorkType = "administrative" | "financial";
export interface ConnectionItem {
  id: string;
  name: string;
  system_type: string;
  is_active: boolean;
  created_at: string;
}

export interface ExecutionItem {
  id: string;
  workflow_id: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
}

export interface AuditLogItem {
  id: string;
  tenant_id: string | null;
  actor_type: string;
  actor_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  correlation_id: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface ContentDocumentListItem {
  id: string;
  title: string;
  document_type: string | null;
  status: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  revision_count: number;
}
export interface WorkflowItem {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export async function apiDownload(
  path: string,
  init: RequestInit = {},
): Promise<{ blob: Blob; filename: string | null }> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    for (const [key, value] of Object.entries(csrfHeader())) headers.set(key, value);
  }

  const res = await fetch(`${FETCH_BASE}${path}`, {
    ...init,
    headers,
    credentials: init.credentials || "same-origin",
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const payload = (await res.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep the safe status text when the upstream did not return JSON.
    }
    throw new ApiError(res.status, detail);
  }

  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res.headers.get("Content-Disposition")),
  };
}
export interface ContentDocumentDetail {
  id: string;
  original_request: string;
  current_document: string | null;
  document_type: string | null;
  latest_correction: string | null;
  status: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  conversation_messages: { role: "user" | "assistant"; content: string }[];
  ui: import("@/lib/content-manager-utils").UIForm | null;
  revisions: ContentDocumentRevision[];
}

export interface ContentDocumentRevision {
  id: string;
  revision_number: number;
  request_text: string;
  provided_fields: Record<string, string | number | boolean | null> | null;
  conversation_messages: { role: "user" | "assistant"; content: string }[];
  ui: import("@/lib/content-manager-utils").UIForm | null;
  document: string | null;
  document_type: string | null;
  document_action: string | null;
  response_status: string;
  created_by_user_id: string | null;
  created_at: string;
}

export type OperationsStatus =
  | "upcoming"
  | "overdue"
  | "awaiting_approval"
  | "needs_intervention"
  | "completed";

export interface OperationsTask {
  id: string;
  tenant_id: string;
  tenant_name: string;
  title: string;
  description: string | null;
  work_type: OperationsWorkType;
  status: OperationsStatus;
  priority: OperationsPriority;
  due_at: string;
  assignee_name: string;
  source: string;
  version: number;
  approval_state: "none" | "pending" | "approved" | "rejected";
  last_note: string | null;
  available_actions: OperationsTaskAction[];
}

export type OperationsPriority = "urgent" | "high" | "normal";

export type OperationsTaskAction =
  | "complete"
  | "submit_for_approval"
  | "approve"
  | "reject"
  | "record_intervention";
export interface OperationsBoardResponse {
  items: OperationsTask[];
  total: number;
  associations: { id: string; name: string; count: number }[];
  summary: {
    total_active: number;
    urgent: number;
    overdue: number;
    needs_intervention: number;
  };
}
