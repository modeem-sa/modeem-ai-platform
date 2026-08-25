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
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
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
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep the safe status text when the upstream did not return JSON.
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
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

export interface WorkflowItem {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}
