import { apiFetch } from "./api";

export type AutomationMode = "automatic" | "approval_required" | "manual";

export interface AutomationStep {
  key: string;
  type: string;
  default_mode: AutomationMode;
  allowed_modes: AutomationMode[];
  executor_available: boolean;
}

export interface AutomationWorkflow {
  key: string;
  module: string;
  service: string;
  label_ar: string;
  label_en: string;
  description_ar: string;
  description_en: string;
  definition_version: number;
  enabled_default: boolean;
  enabled: boolean;
  step_modes: Record<string, AutomationMode>;
  version: number;
  customized: boolean;
  updated_by_user_id: string | null;
  updated_at: string | null;
  steps: AutomationStep[];
}

export interface AutomationCatalogResponse {
  tenant_id: string;
  role: string;
  can_manage: boolean;
  workflows: AutomationWorkflow[];
}

export function fetchAutomationCatalog(tenantId: string): Promise<AutomationCatalogResponse> {
  const query = new URLSearchParams({ tenant_id: tenantId });
  return apiFetch<AutomationCatalogResponse>(
    `/api/v1/operations/automation/catalog?${query.toString()}`,
  );
}

export function updateAutomationWorkflow(
  workflowKey: string,
  payload: {
    tenant_id: string;
    enabled: boolean;
    step_modes: Record<string, AutomationMode>;
    expected_version: number;
  },
): Promise<AutomationWorkflow> {
  return apiFetch<AutomationWorkflow>(
    `/api/v1/operations/automation/workflows/${encodeURIComponent(workflowKey)}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function resetAutomationWorkflow(
  workflowKey: string,
  payload: { tenant_id: string; expected_version: number },
): Promise<AutomationWorkflow> {
  return apiFetch<AutomationWorkflow>(
    `/api/v1/operations/automation/workflows/${encodeURIComponent(workflowKey)}/reset`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}