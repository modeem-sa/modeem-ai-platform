"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import {
  fetchTasks,
  fetchOperationsBootstrap,
  createTask,
  performTaskAction,
  OperationTask,
  OperationsBootstrap,
  TasksSummary,
  TaskFilters,
  CreateTaskPayload,
  OpStatus,
  OpCategory,
  OpPriority,
  OpAction,
  OpSourceType,
  getCollectionDeliveryPresentation,
  isActionDeliveryInFlight,
  toTaskDueAt,
} from "@/lib/operations";
import { ApiError } from "@/lib/api";
import { OdooTaskCard } from "./odoo-task-card";
import { ManualTaskCard } from "./manual-task-card";
import { RecurringTemplates } from "./recurring-templates";

export default function OperationsPage() {
  const { t } = useLocale();

  const [bootstrap, setBootstrap] = useState<OperationsBootstrap | null>(null);
  const [tasks, setTasks] = useState<OperationTask[] | null>(null);
  const [summary, setSummary] = useState<TasksSummary>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<"tasks" | "templates">("tasks");
  const [sourceFilter, setSourceFilter] = useState<OpSourceType | "">("");

  const [filters, setFilters] = useState<TaskFilters>({
    tenant_id: "",
    status: "",
    category: "",
    priority: "",
  });

  const activeFilters = useMemo(() => ({
    ...filters,
    source_type: sourceFilter
  }), [filters, sourceFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (!bootstrap) {
        const [tasksRes, bootstrapRes] = await Promise.all([
          fetchTasks(activeFilters),
          fetchOperationsBootstrap()
        ]);
        setTasks(tasksRes.items);
        setSummary(tasksRes.summary);
        setBootstrap(bootstrapRes);
      } else {
        const res = await fetchTasks(activeFilters);
        setTasks(res.items);
        setSummary(res.summary);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errorLoading"));
    } finally {
      setLoading(false);
    }
  }, [activeFilters, t, bootstrap]);

  useEffect(() => {
    if (activeTab === "tasks") {
      void load();
    }
  }, [load, activeTab]);

  useEffect(() => {
    const executionInProgress = tasks?.some((task) =>
      (task.collection_message
        ? getCollectionDeliveryPresentation(task.collection_message).tone === "in_flight"
        : isActionDeliveryInFlight(task.action))
    ) ?? false;
    if (activeTab !== "tasks" || !executionInProgress) return;

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetchTasks(activeFilters);
        if (!cancelled) {
          setTasks(response.items);
          setSummary(response.summary);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t("errorLoading"));
        }
      }
    }, 5000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeFilters, activeTab, tasks, t]);

  const canCreate = bootstrap?.tenants.some(t => t.can_create) ?? false;
  const [showCreate, setShowCreate] = useState(false);
  const [actionTask, setActionTask] = useState<{ task: OperationTask; action: OpAction } | null>(null);

  const handleActionComplete = useCallback(() => {
    setActionTask(null);
    void load();
  }, [load]);

  const handleCreateComplete = useCallback(() => {
    setShowCreate(false);
    void load();
  }, [load]);

  const stats = [
    { key: "pending", label: t("opStatusPending"), count: summary["pending"] || 0 },
    { key: "in_progress", label: t("opStatusInProgress"), count: summary["in_progress"] || 0 },
    { key: "submitted_for_approval", label: t("opStatusSubmittedForApproval"), count: summary["submitted_for_approval"] || 0 },
  ];

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <Header titleKey="operations" />
      <main className="min-w-0 flex-1 p-4 md:p-6 flex flex-col gap-6">

        {/* Top Tabs */}
        <div className="flex gap-4 border-b border-slate-800 pb-2 overflow-x-auto whitespace-nowrap hide-scrollbar">
          <button
            onClick={() => setActiveTab("tasks")}
            className={`px-4 py-2 text-sm font-semibold transition-colors ${activeTab === "tasks" ? "text-indigo-400 border-b-2 border-indigo-400" : "text-slate-500 hover:text-slate-300"}`}
          >
            {t("opActiveTasks")}
          </button>
          <button
            onClick={() => setActiveTab("templates")}
            className={`px-4 py-2 text-sm font-semibold transition-colors ${activeTab === "templates" ? "text-indigo-400 border-b-2 border-indigo-400" : "text-slate-500 hover:text-slate-300"}`}
          >
            {t("opTemplatesTitle")}
          </button>
        </div>

        {activeTab === "templates" && bootstrap ? (
          <RecurringTemplates bootstrap={bootstrap} />
        ) : (
          <>
            {/* Summary Row */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {stats.map((stat) => (
                <div key={stat.key} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                  <div className="text-sm font-medium text-slate-400">{stat.label}</div>
                  <div className="mt-2 text-3xl font-bold text-slate-100">{stat.count}</div>
                </div>
              ))}
            </div>

            {/* Filters & Actions */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div className="flex flex-col md:flex-row md:flex-wrap md:items-center gap-3 w-full md:w-auto">
                <select
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value as OpSourceType | "")}
                  className="w-full md:w-auto rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
                >
                  <option value="">{t("opAllSources")}</option>
                  <option value="odoo">{t("opOdooOperations")}</option>
                  <option value="manual">{t("opManualTasks")}</option>
                  <option value="recurring">{t("opRecurringTasks")}</option>
                </select>

                <select
                  value={filters.tenant_id}
                  onChange={(e) => setFilters(f => ({ ...f, tenant_id: e.target.value }))}
                  className="w-full md:w-auto rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
                >
                  <option value="">{t("opSelectTenant")}</option>
                  {bootstrap?.tenants.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>

                <select
                  value={filters.status}
                  onChange={(e) => setFilters(f => ({ ...f, status: e.target.value as OpStatus | "" }))}
                  className="w-full md:w-auto rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
                >
                  <option value="">{t("status")}</option>
                  {["pending", "in_progress", "completed", "submitted_for_approval", "approved", "rejected"].map((s) => {
                    const sKey = `opStatus${s.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('')}`;
                    return <option key={s} value={s}>{t(sKey)}</option>;
                  })}
                </select>
              </div>

              {canCreate && (
                <button
                  onClick={() => setShowCreate(true)}
                  className="w-full md:w-auto rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 focus:ring-offset-slate-950"
                >
                  {t("opNewTask")}
                </button>
              )}
            </div>

            {/* Task Grid */}
            {error && (
              <div className="rounded-xl border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-300">
                {error}
              </div>
            )}

            {loading ? (
              <div className="py-12 text-center text-slate-400">{t("loading")}</div>
            ) : !tasks || tasks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-12 text-center">
                <p className="text-slate-300">{t("opEmpty")}</p>
                <p className="mt-2 text-sm text-slate-500">{t("opEmptyHint")}</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {tasks.map((task) => (
                  task.source_type === 'odoo' ? (
                    <OdooTaskCard
                      key={task.id}
                      task={task}
                      onRefresh={load}
                    />
                  ) : (
                    <ManualTaskCard
                      key={task.id}
                      task={task}
                      onAction={(action) => setActionTask({ task, action })}
                    />
                  )
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {showCreate && bootstrap && (
        <CreateTaskModal
          bootstrap={bootstrap}
          onClose={() => setShowCreate(false)}
          onSuccess={handleCreateComplete}
        />
      )}

      {actionTask && (
        <ActionTaskModal
          task={actionTask.task}
          action={actionTask.action}
          onClose={() => setActionTask(null)}
          onSuccess={handleActionComplete}
        />
      )}
    </div>
  );
}

function CreateTaskModal({ bootstrap, onClose, onSuccess }: { bootstrap: OperationsBootstrap, onClose: () => void, onSuccess: () => void }) {
  const { t } = useLocale();
  const { user } = useAuth();

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligibleTenants = useMemo(() => {
    return bootstrap.tenants.filter(t => t.can_create);
  }, [bootstrap]);

  const defaultTenantId = useMemo(() => {
    if (!user) return "";
    const current = user.current_tenant?.id;
    if (current && eligibleTenants.some(t => t.id === current)) {
      return current;
    }
    return eligibleTenants[0]?.id ?? "";
  }, [user, eligibleTenants]);

  const [form, setForm] = useState<CreateTaskPayload>({
    tenant_id: defaultTenantId,
    title: "",
    description: "",
    category: "administrative",
    priority: "medium",
    due_at: "",
    assigned_user_id: "",
  });

  const selectedTenant = useMemo(() => {
    return eligibleTenants.find(t => t.id === form.tenant_id);
  }, [eligibleTenants, form.tenant_id]);

  useEffect(() => {
    if (selectedTenant && user) {
      const isMember = selectedTenant.members.some(m => m.id === user.id);
      setForm(f => ({ ...f, assigned_user_id: isMember ? user.id : "" }));
    }
  }, [selectedTenant, user]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || !form.tenant_id) return;

    setSaving(true);
    setError(null);
    try {
      await createTask({
        ...form,
        due_at: toTaskDueAt(form.due_at),
        assigned_user_id: form.assigned_user_id || undefined,
        description: form.description?.trim() || undefined,
      });
      onSuccess();
    } catch (err: unknown) {
      if (err instanceof Error && err.message === "INVALID_DUE_DATE") {
        setError(t("opInvalidDueDate"));
      } else if (
        err instanceof ApiError
        && err.message.includes("Assigned user must have an active membership")
      ) {
        setError(t("opInvalidAssignee"));
      } else if (err instanceof ApiError && err.status === 422) {
        setError(`${t("opInvalidTaskData")} ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : t("cmError"));
      }
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
        <h2 className="mb-5 text-lg font-bold text-slate-100">{t("opNewTask")}</h2>

        {error && (
          <div className="mb-4 rounded-lg bg-rose-950/50 p-3 text-sm text-rose-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTenant")}
            <select
              required
              value={form.tenant_id}
              onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
            >
              <option value="" disabled>{t("opSelectTenant")}</option>
              {eligibleTenants.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskTitle")}
            <input
              required
              type="text"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskDesc")}
            <textarea
              rows={3}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="resize-none rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
            />
          </label>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opCategory")}
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as OpCategory })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
              >
                <option value="administrative">{t("opCatAdministrative")}</option>
                <option value="financial">{t("opCatFinancial")}</option>
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opPriority")}
              <select
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value as OpPriority })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
              >
                <option value="low">{t("opPrioLow")}</option>
                <option value="medium">{t("opPrioMedium")}</option>
                <option value="high">{t("opPrioHigh")}</option>
                <option value="urgent">{t("opPrioUrgent")}</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opDueDate")}
              <input
                type="date"
                min="2000-01-01"
                max="2100-12-31"
                value={form.due_at}
                onChange={(e) => setForm({ ...form, due_at: e.target.value })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
              />
            </label>

            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opAssignee")}
              <select
                value={form.assigned_user_id}
                onChange={(e) => setForm({ ...form, assigned_user_id: e.target.value })}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
              >
                <option value="">{t("opUnassigned")}</option>
                {selectedTenant?.members.map(member => (
                  <option key={member.id} value={member.id}>
                    {member.full_name || member.email} {user?.id === member.id ? `(${t("opMe")})` : ""}
                  </option>
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
              className="rounded-lg bg-emerald-500 px-6 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
            >
              {saving ? t("saving") : t("opSave")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ActionTaskModal({ task, action, onClose, onSuccess }: { task: OperationTask, action: OpAction, onClose: () => void, onSuccess: () => void }) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const isReject = action === 'reject';
  const actionKey = `opAction${action.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('')}`;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isReject && !note.trim()) {
      setError(t("opRejectReasonRequired"));
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await performTaskAction(task.id, action, task.version, note.trim() || undefined);
      onSuccess();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("cmError"));
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
        <h2 className="mb-2 text-lg font-bold text-slate-100">
          {t(actionKey) || action}
        </h2>
        <p className="mb-5 text-sm text-slate-400">{task.title}</p>

        {error && (
          <div className="mb-4 rounded-lg bg-rose-950/50 p-3 text-sm text-rose-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opActionNote")} {isReject && <span className="text-rose-400">*</span>}
            <textarea
              required={isReject}
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("opActionNotePlaceholder")}
              className="resize-none rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
            />
          </label>

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
              className={`rounded-lg px-6 py-2 text-sm font-medium transition-colors disabled:opacity-50 ${
                isReject
                  ? "bg-rose-500 text-white hover:bg-rose-400"
                  : "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
              }`}
            >
              {saving ? t("saving") : (t(actionKey) || action)}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
