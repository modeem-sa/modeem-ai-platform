"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/header";
import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";
import { apiFetch } from "@/lib/api";
import {
  type BootstrapTenant,
  type OperationTask,
  type OperationsBootstrap,
  type OpPriority,
  createHrReviewTask,
} from "@/lib/operations";

type ConnectionOut = {
  id: string;
  name: string;
  provider: string;
  status: string;
  is_active: boolean;
  odoo_company_id: number | null;
};

type PreviewPage = {
  resource: string;
  fields: string[];
  records: PreviewRecord[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
};

type PreviewRecord = Record<string, unknown> & {
  id?: number;
  name?: string;
};

type HrResource =
  | "employees_summary"
  | "attendance_summary"
  | "leaves_summary"
  | "payroll_summary";

type ReadFilter = {
  field: string;
  operator: "=" | ">=" | "<=";
  value: string | number;
};

type ReviewContext = {
  recordId: number | null;
  resource: HrResource;
  connectionId: string;
  connectionName: string;
  employeeId: string;
  dateFrom: string;
  dateTo: string;
};

const RESOURCE_OPTIONS: { value: HrResource; labelKey: string }[] = [
  { value: "employees_summary", labelKey: "hrResourceEmployees" },
  { value: "attendance_summary", labelKey: "hrResourceAttendance" },
  { value: "leaves_summary", labelKey: "hrResourceLeaves" },
  { value: "payroll_summary", labelKey: "hrResourcePayroll" },
];

export default function HrReviewPage() {
  const { t } = useLocale();
  const { user, selectTenant } = useAuth();

  const [bootstrap, setBootstrap] = useState<OperationsBootstrap | null>(null);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [loadingContext, setLoadingContext] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  
  const [tenantId, setTenantId] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [resource, setResource] = useState<HrResource>("employees_summary");
  const [empId, setEmpId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [page, setPage] = useState<PreviewPage | null>(null);
  const [createdTask, setCreatedTask] = useState<OperationTask | null>(null);

  const loadContext = useCallback(async () => {
    setLoadingContext(true);
    setContextError(null);
    try {
      const [boot, conns] = await Promise.all([
        apiFetch<OperationsBootstrap>("/api/v1/operations/bootstrap"),
        apiFetch<ConnectionOut[]>("/api/v1/connections")
      ]);
      setBootstrap(boot);
      const odooConns = conns.filter(
        c => c.provider === "odoo" && c.status === "configured" && c.is_active
      );
      setConnections(odooConns);
      setTenantId(user?.current_tenant?.id ?? "");
      setConnectionId(current => (
        odooConns.some(connection => connection.id === current) ? current : ""
      ));
    } catch (error: unknown) {
      setContextError(error instanceof Error ? error.message : t("hrContextError"));
    } finally {
      setLoadingContext(false);
    }
  }, [t, user?.current_tenant?.id]);

  useEffect(() => {
    void loadContext();
  }, [loadContext]);

  const handleTenantChange = async (nextTenantId: string) => {
    setTenantId(nextTenantId);
    setConnectionId("");
    setPage(null);
    setDataError(null);
    await selectTenant(nextTenantId);
  };

  const loadData = async (offset = 0) => {
    if (!connectionId) return;

    setDataLoading(true);
    setDataError(null);
    try {
      const conn = connections.find(c => c.id === connectionId);
      const companyId = conn?.odoo_company_id;
      if (!companyId) {
        setDataError(t("hrMissingCompany"));
        return;
      }

      const filters: ReadFilter[] = [];
      if (empId.trim()) {
        const employeeId = Number(empId);
        if (!Number.isSafeInteger(employeeId) || employeeId < 1) {
          setDataError(t("hrInvalidEmployee"));
          return;
        }
        filters.push({
          field: resource === "employees_summary" ? "id" : "employee_id",
          operator: "=",
          value: employeeId,
        });
      }
      if (dateFrom && resource !== "employees_summary") {
        filters.push({
          field: resource === "attendance_summary"
            ? "check_in"
            : resource === "leaves_summary"
              ? "request_date_from"
              : "date_from",
          operator: ">=",
          value: resource === "attendance_summary"
            ? `${dateFrom} 00:00:00`
            : dateFrom,
        });
      }
      if (dateTo && resource !== "employees_summary") {
        filters.push({
          field: resource === "attendance_summary"
            ? "check_in"
            : resource === "leaves_summary"
              ? "request_date_to"
              : "date_to",
          operator: "<=",
          value: resource === "attendance_summary"
            ? `${dateTo} 23:59:59`
            : dateTo,
        });
      }

      const res = await apiFetch<PreviewPage>(`/api/v1/connections/${connectionId}/read-preview`, {
        method: "POST",
        body: JSON.stringify({
          resource,
          company_id: companyId,
          filters: filters.length ? filters : undefined,
          limit: 25,
          offset,
          order_by: "id",
          order_direction: "desc"
        })
      });
      setPage(res);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "";
      if (message.includes("not installed")) setDataError(t("previewModuleUnavailable"));
      else if (message.includes("access_denied")) setDataError(t("previewAccessDenied"));
      else if (message.includes("authentication_failed")) setDataError(t("hrOdooAuthError"));
      else if (
        message.includes("connection_failed")
        || message.includes("timeout")
        || message.includes("upstream")
      ) setDataError(t("hrConnectionError"));
      else if (message.includes("Insufficient role")) setDataError(t("hrPermissionError"));
      else setDataError(t("previewError"));
    } finally {
      setDataLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(null);
    void loadData(0);
  };

  const [taskContext, setTaskContext] = useState<ReviewContext | null>(null);

  const selectedTenant = bootstrap?.tenants.find(t => t.id === tenantId);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <Header titleKey="hrReview" />
      <main className="min-w-0 flex-1 p-4 md:p-6 flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <p className="text-sm text-slate-400">{t("hrReviewDesc")}</p>
        </div>

        {loadingContext ? (
          <div className="py-12 text-center text-slate-400">{t("loading")}</div>
        ) : (
          <form onSubmit={handleSearch} className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("opTenant")}
                <select
                  required
                  value={tenantId}
                  onChange={(e) => void handleTenantChange(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                >
                  <option value="" disabled>{t("opSelectTenant")}</option>
                  {bootstrap?.tenants.map(t => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("hrSelectConnection")}
                <select
                  required
                  value={connectionId}
                  onChange={(e) => {
                    setConnectionId(e.target.value);
                    setPage(null);
                  }}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                >
                  <option value="" disabled>{t("hrSelectConnection")}</option>
                  {connections.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("resource")}
                <select
                  value={resource}
                  onChange={(e) => {
                    setResource(e.target.value as HrResource);
                    setPage(null);
                  }}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                >
                  {RESOURCE_OPTIONS.map(option => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("hrFilterEmpId")}
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={empId}
                  onChange={(e) => setEmpId(e.target.value)}
                  placeholder="123"
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                />
              </label>

              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("hrFilterDateFrom")}
                <input
                  type="date"
                  disabled={resource === "employees_summary"}
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                />
              </label>

              <label className="flex flex-col gap-1.5 text-sm text-slate-300">
                {t("hrFilterDateTo")}
                <input
                  type="date"
                  min={dateFrom || undefined}
                  disabled={resource === "employees_summary"}
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
                />
              </label>
            </div>
            
            <div className="flex justify-end pt-2 border-t border-slate-800/50">
              <button
                type="submit"
                disabled={!connectionId || !tenantId || dataLoading}
                className="rounded-lg bg-indigo-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-400 disabled:opacity-50"
              >
                {dataLoading ? t("loading") : t("hrLoadData")}
              </button>
            </div>
          </form>
        )}

        {/* Data Area */}
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200">
            {t("hrProvenanceNotice")}
          </div>

          {contextError && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-300">
              {contextError}
            </div>
          )}

          {!loadingContext && !contextError && connections.length === 0 && (
            <div className="rounded-lg border border-amber-800 bg-amber-950/30 p-4 text-sm text-amber-200">
              {t("hrNoConnection")}
            </div>
          )}

          {dataError && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-300">
              {dataError}
            </div>
          )}

          {createdTask && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-800 bg-emerald-950/40 p-4 text-sm text-emerald-200">
              <span>{t("hrTaskCreated")}</span>
              <a
                href="/operations"
                className="font-medium underline underline-offset-4 hover:text-white"
              >
                {t("hrOpenTaskBoard")}
              </a>
            </div>
          )}

          {dataLoading && !page ? (
            <div className="py-12 text-center text-slate-400">{t("loading")}</div>
          ) : page && page.records.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-12 text-center">
              <p className="text-slate-300">{t("previewEmpty")}</p>
            </div>
          ) : page && page.records.length > 0 ? (
            <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-900 text-slate-400 border-b border-slate-800">
                    <tr>
                      {page.fields.filter(key => key !== "id").map(key => (
                        <th key={key} className="px-4 py-3 text-start font-medium capitalize">
                          {key.replace(/_/g, ' ')}
                        </th>
                      ))}
                      <th className="px-4 py-3 text-start font-medium w-32">{t("action")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {page.records.map((row, idx) => (
                      <tr key={row.id ?? idx} className="text-slate-200 hover:bg-slate-800/20 transition-colors">
                        {page.fields.filter(key => key !== "id").map(key => (
                          <td key={key} className="px-4 py-3">
                            {formatValue(row[key], t)}
                          </td>
                        ))}
                        <td className="px-4 py-3">
                          {selectedTenant?.can_create ? (
                            <button
                              onClick={() => setTaskContext({
                                recordId: typeof row.id === "number" ? row.id : null,
                                resource,
                                connectionId,
                                connectionName: connections.find(
                                  connection => connection.id === connectionId
                                )?.name ?? "",
                                employeeId: empId,
                                dateFrom,
                                dateTo,
                              })}
                              className="text-xs font-medium text-indigo-400 hover:text-indigo-300"
                            >
                              {t("hrCreateTask")}
                            </button>
                          ) : (
                            <span className="text-xs text-slate-500">
                              {t("hrTaskRequiresManager")}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between border-t border-slate-800 p-4">
                <div className="text-sm text-slate-400">
                  {page.offset + 1} - {page.offset + page.returned_count}
                </div>
                <div className="flex gap-2">
                  <button
                    disabled={page.offset === 0 || dataLoading}
                    onClick={() => loadData(Math.max(0, page.offset - page.limit))}
                    className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                  >
                    {t("previewPrev")}
                  </button>
                  <button
                    disabled={!page.has_more || dataLoading}
                    onClick={() => loadData(page.next_offset || page.offset + page.limit)}
                    className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                  >
                    {t("previewNext")}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </main>

      {taskContext && selectedTenant && (
        <CreateTaskModal
          tenantId={tenantId}
          tenant={selectedTenant}
          context={taskContext}
          onClose={() => setTaskContext(null)}
          onSuccess={(task) => {
            setCreatedTask(task);
            setTaskContext(null);
          }}
        />
      )}
    </div>
  );
}

function formatValue(value: unknown, t: (key: string) => string): string {
  if (value === null || value === undefined || value === false) return "—";
  if (value === true) return t("previewYes");
  if (
    Array.isArray(value)
    && value.length === 2
    && typeof value[1] === "string"
  ) return value[1];
  if (typeof value === "number" || typeof value === "string") return String(value);
  return "—";
}

function CreateTaskModal({
  tenantId,
  tenant,
  context,
  onClose,
  onSuccess
}: {
  tenantId: string;
  tenant: BootstrapTenant;
  context: ReviewContext;
  onClose: () => void;
  onSuccess: (task: OperationTask) => void;
}) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resourceLabel = t(
    RESOURCE_OPTIONS.find(option => option.value === context.resource)?.labelKey
      ?? "hrReview"
  );
  const initialTitle = `${t("hrTaskFor")} ${resourceLabel}${
    context.recordId ? ` #${context.recordId}` : ""
  }`;
  const initialDesc = [
    t("hrTaskReferenceOnly"),
    `${t("opTenant")}: ${tenant.name}`,
    `${t("hrSelectConnection")}: ${context.connectionName}`,
    `${t("resource")}: ${resourceLabel}`,
    context.recordId ? `${t("previewId")}: ${context.recordId}` : "",
    context.employeeId ? `${t("hrFilterEmpId")}: ${context.employeeId}` : "",
    context.dateFrom ? `${t("hrFilterDateFrom")}: ${context.dateFrom}` : "",
    context.dateTo ? `${t("hrFilterDateTo")}: ${context.dateTo}` : "",
  ].filter(Boolean).join("\n");

  const [form, setForm] = useState<{
    priority: OpPriority;
    assigned_user_id: string;
  }>({
    priority: "medium" as const,
    assigned_user_id: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setSaving(true);
    setError(null);
    try {
      if (context.recordId === null) {
        setError(t("previewError"));
        return;
      }
      const employeeId = context.employeeId ? Number(context.employeeId) : undefined;
      const task = await createHrReviewTask({
        tenant_id: tenantId,
        connection_id: context.connectionId,
        resource: context.resource,
        record_id: context.recordId,
        employee_id: employeeId,
        date_from: context.dateFrom || undefined,
        date_to: context.dateTo || undefined,
        priority: form.priority,
        assigned_user_id: form.assigned_user_id || undefined,
      });
      onSuccess(task);
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : t("cmError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="mb-5 text-lg font-bold text-slate-100">{t("hrCreateTask")}</h2>

        {error && (
          <div className="mb-4 rounded-lg bg-rose-950/50 p-3 text-sm text-rose-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskTitle")}
            <div className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white">
              {initialTitle}
            </div>
          </div>

          <div className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskDesc")}
            <div className="whitespace-pre-wrap rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-300">
              {initialDesc}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opPriority")}
              <select
                value={form.priority}
                onChange={(e) => setForm({
                  ...form,
                  priority: e.target.value as OpPriority,
                })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
              >
                <option value="low">{t("opPrioLow")}</option>
                <option value="medium">{t("opPrioMedium")}</option>
                <option value="high">{t("opPrioHigh")}</option>
                <option value="urgent">{t("opPrioUrgent")}</option>
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opAssignee")}
              <select
                value={form.assigned_user_id}
                onChange={(e) => setForm({ ...form, assigned_user_id: e.target.value })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500"
              >
                <option value="">{t("opUnassigned")}</option>
                {tenant.members.map((m) => (
                  <option key={m.id} value={m.id}>{m.full_name || m.email}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-4 flex justify-end gap-3 border-t border-slate-800 pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-lg px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200"
            >
              {t("opCancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-indigo-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-400 disabled:opacity-50"
            >
              {saving ? t("saving") : t("opSave")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
