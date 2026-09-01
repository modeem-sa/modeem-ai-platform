"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import { useAuth } from "@/components/auth-provider";
import { FinancialReview } from "@/components/financial-review";
import {
  ApiError,
  apiFetch,
  type OperationsBoardResponse,
  type OperationsTask,
  type OperationsTaskAction,
} from "@/lib/api";
import {
  createTask,
  fetchOdooEmployees,
  fetchOperationsBootstrap,
  fetchTasks,
  fetchFinancialConnections,
  fetchFinancialPage,
  SERVICE_CATALOG,
  type FinancialConnection,
  type FinancialFilter,
  type FinancialReadPage,
  type FinancialRecord,
  type FinancialResource,
  type OdooEmployee,
  type OpCategory,
  type OperationTask,
  type OperationsBootstrap,
} from "@/lib/operations";

const Icons = {
  Filter: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h20l-8 9.5V21l-4-2v-6.5z" /></svg>,
  AlertCircle: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><path d="M12 8v4m0 4h.01" /></svg>,
  Clock: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>,
  CheckCircle2: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></svg>,
  AlertTriangle: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m12 3 10 18H2zM12 9v4m0 4h.01" /></svg>,
  Building2: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 22V4h12v18M2 22h20M10 8h4m-4 4h4m-4 4h4" /></svg>,
  Calendar: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4m8-4v4M3 10h18" /></svg>,
  Briefcase: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M8 7V5h8v2" /></svg>,
  User: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="7" r="4" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" /></svg>,
  Loader2: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.2-8.6" /></svg>,
  Inbox: ({ className }: { className?: string }) => <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16l2 10v6H2v-6zM2 14h6l2 3h4l2-3h6" /></svg>,
};

function OperationsBoardPage() {
  const { t, locale } = useLocale();
  const { user, selectTenant } = useAuth();

  const [data, setData] = useState<OperationsBoardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionTask, setActionTask] = useState<{
    task: OperationsTask;
    action: OperationsTaskAction;
  } | null>(null);
  const [financialConnections, setFinancialConnections] = useState<FinancialConnection[]>([]);
  const [financialConnectionId, setFinancialConnectionId] = useState("");
  const [financialResource, setFinancialResource] = useState<
    Exclude<FinancialResource, "journal_items">
  >("journal_entries");
  const [financialPage, setFinancialPage] = useState<FinancialReadPage | null>(null);
  const [financialLines, setFinancialLines] = useState<FinancialRecord[]>([]);
  const [selectedEntry, setSelectedEntry] = useState<FinancialRecord | null>(null);
  const [financialSearch, setFinancialSearch] = useState("");
  const [financialStatus, setFinancialStatus] = useState("");
  const [financialDateFrom, setFinancialDateFrom] = useState("");
  const [financialDateTo, setFinancialDateTo] = useState("");
  const [financialOffset, setFinancialOffset] = useState(0);
  const [financialLoading, setFinancialLoading] = useState(false);
  const [financialLinesLoading, setFinancialLinesLoading] = useState(false);
  const [financialError, setFinancialError] = useState<string | null>(null);
  const financialRequestGeneration = useRef(0);
  const financialLinesGeneration = useRef(0);

  // Filters
  const [filters, setFilters] = useState({
    association: "",
    work_type: "",
    status: "",
    priority: "",
  });

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    // Construct query params
    const params = new URLSearchParams();
    if (filters.association) params.set("tenant_id", filters.association);
    if (filters.work_type) params.set("work_type", filters.work_type);
    if (filters.status) params.set("status", filters.status);
    if (filters.priority) params.set("priority", filters.priority);

    apiFetch<OperationsBoardResponse>(`/api/v1/operations/board?${params.toString()}`)
      .then((res) => setData(res))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let cancelled = false;
    financialRequestGeneration.current += 1;
    financialLinesGeneration.current += 1;
    setFinancialPage(null);
    setSelectedEntry(null);
    setFinancialLines([]);
    setFinancialConnectionId("");
    fetchFinancialConnections()
      .then((connections) => {
        if (cancelled) return;
        setFinancialConnections(connections);
        const firstReady = connections.find(
          (item) =>
            item.is_active &&
            item.odoo_company_id !== null &&
            item.last_test_status === "success" &&
            (item.selected_transport === "xmlrpc" || item.selected_transport === "json2"),
        );
        setFinancialConnectionId(firstReady?.id ?? "");
      })
      .catch(() => {
        if (!cancelled) {
          setFinancialConnections([]);
          setFinancialError(
            locale === "ar"
              ? "تعذّر تحميل اتصالات Odoo لهذه الجمعية."
              : "Could not load Odoo connections for this association.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [user?.current_tenant?.id, locale]);

  const loadFinancial = useCallback(async (generation: number) => {
    if (!financialConnectionId) {
      if (generation === financialRequestGeneration.current) {
        setFinancialPage(null);
        setFinancialLoading(false);
      }
      return;
    }
    const filters: FinancialFilter[] = [];
    if (financialSearch.trim()) {
      filters.push({ field: "name", operator: "ilike", value: financialSearch.trim() });
    }
    if (financialStatus) {
      filters.push({ field: "state", operator: "=", value: financialStatus });
    }
    if (financialDateFrom) {
      filters.push({ field: "date", operator: ">=", value: financialDateFrom });
    }
    if (financialDateTo) {
      filters.push({ field: "date", operator: "<=", value: financialDateTo });
    }

    setFinancialLoading(true);
    setFinancialError(null);
    try {
      const page = await fetchFinancialPage(financialConnectionId, {
        resource: financialResource,
        filters,
        limit: 25,
        offset: financialOffset,
        order_by: "date",
        order_direction: "desc",
      });
      if (generation !== financialRequestGeneration.current) return;
      setFinancialPage(page);
      setSelectedEntry(null);
      setFinancialLines([]);
      financialLinesGeneration.current += 1;
    } catch (err: unknown) {
      if (generation !== financialRequestGeneration.current) return;
      setFinancialError(
        err instanceof Error
          ? err.message
          : locale === "ar"
            ? "تعذّرت قراءة البيانات المالية من Odoo."
            : "Could not read financial data from Odoo.",
      );
    } finally {
      if (generation === financialRequestGeneration.current) {
        setFinancialLoading(false);
      }
    }
  }, [
    financialConnectionId,
    financialDateFrom,
    financialDateTo,
    financialOffset,
    financialResource,
    financialSearch,
    financialStatus,
    locale,
  ]);

  useEffect(() => {
    const generation = ++financialRequestGeneration.current;
    const timer = window.setTimeout(() => void loadFinancial(generation), 300);
    return () => window.clearTimeout(timer);
  }, [loadFinancial]);

  const selectFinancialEntry = useCallback(async (record: FinancialRecord) => {
    if (!financialConnectionId) return;
    const generation = ++financialLinesGeneration.current;
    setSelectedEntry(record);
    setFinancialLinesLoading(true);
    setFinancialError(null);
    try {
      const page = await fetchFinancialPage(financialConnectionId, {
        resource: "journal_items",
        filters: [{ field: "move_id", operator: "=", value: record.id }],
        limit: 50,
        offset: 0,
        order_by: "id",
        order_direction: "asc",
      });
      if (generation !== financialLinesGeneration.current) return;
      setFinancialLines(page.records);
    } catch (err: unknown) {
      if (generation !== financialLinesGeneration.current) return;
      setFinancialLines([]);
      setFinancialError(
        err instanceof Error
          ? err.message
          : locale === "ar"
            ? "تعذّر تحميل سطور القيد."
            : "Could not load journal lines.",
      );
    } finally {
      if (generation === financialLinesGeneration.current) {
        setFinancialLinesLoading(false);
      }
    }
  }, [financialConnectionId, locale]);

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const clearFilters = () => {
    setFilters({
      association: "",
      work_type: "",
      status: "",
      priority: "",
    });
  };

  const hasActiveFilters = Object.values(filters).some(v => v !== "");

  // Formatting helpers
  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(d);
    } catch {
      return dateStr;
    }
  };

  // Determine direction
  const isRtl = locale === "ar";
  const msAutoClass = isRtl ? "mr-auto" : "ml-auto";

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-[#0b1120]">
      <Header titleKey="opsBoard" />

      <main className="flex-1 flex flex-col p-4 sm:p-6 overflow-hidden gap-6">

        {/* Summary Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
          <SummaryCard
            title={t("opsActive")}
            value={data?.summary?.total_active}
            loading={loading && !data}
            icon={<Icons.Briefcase className="w-4 h-4 text-emerald-400" />}
            color="border-emerald-500/20 bg-emerald-500/5"
            textColor="text-emerald-300"
          />
          <SummaryCard
            title={t("opsUrgent")}
            value={data?.summary?.urgent}
            loading={loading && !data}
            icon={<Icons.AlertCircle className="w-4 h-4 text-rose-400" />}
            color="border-rose-500/20 bg-rose-500/5"
            textColor="text-rose-300"
          />
          <SummaryCard
            title={t("opsOverdue")}
            value={data?.summary?.overdue}
            loading={loading && !data}
            icon={<Icons.Clock className="w-4 h-4 text-amber-400" />}
            color="border-amber-500/20 bg-amber-500/5"
            textColor="text-amber-300"
          />
          <SummaryCard
            title={t("opsNeedsIntervention")}
            value={data?.summary?.needs_intervention}
            loading={loading && !data}
            icon={<Icons.AlertTriangle className="w-4 h-4 text-purple-400" />}
            color="border-purple-500/20 bg-purple-500/5"
            textColor="text-purple-300"
          />
        </div>

        <FinancialReview
          locale={locale}
          associations={(user?.memberships ?? []).map((item) => ({
            id: item.tenant_id,
            name: item.tenant_name,
            role: item.role,
          }))}
          connections={financialConnections}
          associationId={user?.current_tenant?.id ?? ""}
          connectionId={financialConnectionId}
          resource={financialResource}
          page={financialPage}
          lines={financialLines}
          selectedEntry={selectedEntry}
          search={financialSearch}
          status={financialStatus}
          dateFrom={financialDateFrom}
          dateTo={financialDateTo}
          loading={financialLoading}
          linesLoading={financialLinesLoading}
          error={financialError}
          onAssociationChange={(id) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialConnections([]);
            setFinancialConnectionId("");
            setFinancialError(null);
            void selectTenant(id);
          }}
          onConnectionChange={(id) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialError(null);
            setFinancialConnectionId(id);
            setFinancialOffset(0);
          }}
          onResourceChange={(resource) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialError(null);
            setFinancialResource(resource);
            setFinancialStatus("");
            setFinancialOffset(0);
          }}
          onSearchChange={(value) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialSearch(value);
            setFinancialOffset(0);
          }}
          onStatusChange={(value) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialStatus(value);
            setFinancialOffset(0);
          }}
          onDateFromChange={(value) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialDateFrom(value);
            setFinancialOffset(0);
          }}
          onDateToChange={(value) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialDateTo(value);
            setFinancialOffset(0);
          }}
          onSelectEntry={(record) => void selectFinancialEntry(record)}
          onPageChange={(offset) => {
            financialRequestGeneration.current += 1;
            financialLinesGeneration.current += 1;
            setFinancialPage(null);
            setSelectedEntry(null);
            setFinancialLines([]);
            setFinancialOffset(offset);
          }}
          onRefresh={() => {
            const generation = ++financialRequestGeneration.current;
            void loadFinancial(generation);
          }}
        />

        {/* Main Content Area: Filters + Grid */}
        <div className="flex flex-col flex-1 overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 shadow-xl">

          {/* Filters Bar */}
          <div className="flex flex-wrap items-center gap-3 p-3 border-b border-slate-800 bg-slate-900/80">
            <div className={`flex items-center gap-2 text-slate-400 px-2 border-slate-800/50 ${isRtl ? "border-l" : "border-r"}`}>
              <Icons.Filter className="w-4 h-4" />
              <span className="text-sm font-medium">{t("opsSummary")}</span>
            </div>

            <SelectFilter
              value={filters.association}
              onChange={(v) => updateFilter("association", v)}
              options={data?.associations?.map(a => ({ value: a.id, label: a.name })) || []}
              placeholder={t("opsAssociation")}
              icon={<Icons.Building2 className="w-3.5 h-3.5" />}
              isRtl={isRtl}
            />

            <SelectFilter
              value={filters.work_type}
              onChange={(v) => updateFilter("work_type", v)}
              options={[
                { value: "administrative", label: t("opsAdministrative") },
                { value: "financial", label: t("opsFinancial") }
              ]}
              placeholder={t("opsWorkType")}
              icon={<Icons.Briefcase className="w-3.5 h-3.5" />}
              isRtl={isRtl}
            />

            <SelectFilter
              value={filters.status}
              onChange={(v) => updateFilter("status", v)}
              options={[
                { value: "upcoming", label: t("opsUpcoming") },
                { value: "overdue", label: t("opsOverdue") },
                { value: "awaiting_approval", label: t("opsAwaitingApproval") },
                { value: "needs_intervention", label: t("opsNeedsIntervention") },
                { value: "completed", label: t("opsCompleted") }
              ]}
              placeholder={t("opsStatus")}
              icon={<Icons.CheckCircle2 className="w-3.5 h-3.5" />}
              isRtl={isRtl}
            />

            <SelectFilter
              value={filters.priority}
              onChange={(v) => updateFilter("priority", v)}
              options={[
                { value: "urgent", label: t("opsUrgent") },
                { value: "high", label: t("opsHigh") },
                { value: "normal", label: t("opsNormal") }
              ]}
              placeholder={t("opsPriority")}
              icon={<Icons.AlertCircle className="w-3.5 h-3.5" />}
              isRtl={isRtl}
            />

            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className={`${msAutoClass} text-xs px-3 py-1.5 rounded-md bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white transition-colors`}
              >
                {t("opsClearFilters")}
              </button>
            )}
          </div>

          {/* Table Container */}
          <div className="flex-1 overflow-auto relative min-h-[300px]">
            {loading && !data?.items && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm z-10">
                <Icons.Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
              </div>
            )}

            {error ? (
              <div className="p-8 flex flex-col items-center justify-center text-center h-full">
                <div className="w-12 h-12 rounded-full bg-rose-500/10 flex items-center justify-center mb-4">
                  <Icons.AlertTriangle className="w-6 h-6 text-rose-500" />
                </div>
                <div className="text-rose-400 font-medium mb-1">{t("errorLoading")}</div>
                <div className="text-sm text-slate-500 mb-4">{error}</div>
                <button onClick={load} className="px-4 py-2 rounded-md bg-slate-800 text-white text-sm hover:bg-slate-700 transition-colors">
                  {t("retry")}
                </button>
              </div>
            ) : !data?.items?.length && !loading ? (
              <div className="p-12 flex flex-col items-center justify-center text-center h-full">
                <div className="w-16 h-16 rounded-2xl bg-slate-800/50 flex items-center justify-center mb-4 border border-slate-700">
                  <Icons.Inbox className="w-8 h-8 text-slate-500" />
                </div>
                <div className="text-slate-300 font-medium mb-1">{t("noRecords")}</div>
                <div className="text-sm text-slate-500 max-w-sm">
                  {hasActiveFilters ? (isRtl ? "جرب تعديل عوامل التصفية لرؤية المزيد." : "Try adjusting your filters to see more tasks.") : (isRtl ? "لا توجد مهام حالياً." : "There are no tasks available in the operations board right now.")}
                </div>
              </div>
            ) : (
              <table className={`w-full text-sm whitespace-nowrap ${isRtl ? "text-right" : "text-left"}`}>
                <thead className="sticky top-0 z-10 bg-slate-900 border-b border-slate-800 text-slate-400 text-xs tracking-wider">
                  <tr>
                    <th className="px-4 py-3 font-medium w-1">{/* Priority */}</th>
                    <th className="px-4 py-3 font-medium">{t("opsTitle")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsAssociation")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsWorkType")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsStatus")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsDueDate")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsAssignee")}</th>
                    <th className="px-4 py-3 font-medium">{t("opsActions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {data?.items.map((task) => (
                    <tr
                      key={task.id}
                      className="hover:bg-slate-800/40 transition-colors group cursor-pointer"
                    >
                      <td className="px-4 py-3">
                        <PriorityIndicator priority={task.priority} />
                      </td>
                      <td className="px-4 py-3 min-w-[280px] max-w-[400px]">
                        <div className="flex flex-col gap-1">
                          <span className="font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
                            {task.title}
                          </span>
                          {task.description && (
                            <span className="text-xs text-slate-500 truncate">
                              {task.description}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-6 h-6 rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] text-slate-400 font-medium shrink-0">
                            {task.tenant_name.substring(0, 2).toUpperCase()}
                          </div>
                          <span className="text-slate-300 truncate max-w-[150px]">{task.tenant_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          label={t(task.work_type === "administrative" ? "opsAdministrative" : "opsFinancial")}
                          variant={task.work_type === "administrative" ? "blue" : "emerald"}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={task.status} t={t} />
                      </td>
                      <td className="px-4 py-3">
                        <div className={`flex items-center gap-1.5 text-slate-400 font-mono text-xs ${isRtl ? "flex-row-reverse justify-end" : ""}`}>
                          <Icons.Calendar className="w-3.5 h-3.5 opacity-70" />
                          {formatDate(task.due_at)}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 text-slate-300">
                          <div className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center shrink-0">
                            <Icons.User className="w-3 h-3 text-slate-400" />
                          </div>
                          <span className="truncate max-w-[120px]">{task.assignee_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {task.available_actions.map((action) => (
                            <button
                              key={action}
                              type="button"
                              onClick={() => setActionTask({ task, action })}
                              className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
                                action === "reject" || action === "record_intervention"
                                  ? "border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
                                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                              }`}
                            >
                              {taskActionLabel(action, t)}
                            </button>
                          ))}
                          {!task.available_actions.length && (
                            <span className="text-xs text-slate-600">—</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Loading Overlay for background updates */}
            {loading && data?.items && (
              <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-[1px] flex items-start justify-center pt-8 z-20">
                <div className="bg-slate-800 border border-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-full shadow-lg flex items-center gap-2">
                  <Icons.Loader2 className="w-3 h-3 animate-spin" />
                  {t("loading")}
                </div>
              </div>
            )}
          </div>

          {/* Pagination/Footer Info */}
          {data && data.items.length > 0 && (
            <div className="border-t border-slate-800 bg-slate-900/80 px-4 py-3 text-xs text-slate-500 flex justify-between items-center">
              <div>
                {isRtl ? `عرض ${data.items.length} من ${data.total} مهمة` : `Showing ${data.items.length} of ${data.total} tasks`}
              </div>
              <div className="flex gap-4">
                <span className="flex items-center gap-1.5"><PriorityIndicator priority="urgent" /> {t("opsUrgent")}</span>
                <span className="flex items-center gap-1.5"><PriorityIndicator priority="high" /> {t("opsHigh")}</span>
                <span className="flex items-center gap-1.5"><PriorityIndicator priority="normal" /> {t("opsNormal")}</span>
              </div>
            </div>
          )}
        </div>
      </main>
      {actionTask && (
        <TaskActionDialog
          task={actionTask.task}
          action={actionTask.action}
          onClose={() => setActionTask(null)}
          onSuccess={() => {
            setActionTask(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function taskActionLabel(action: OperationsTaskAction, t: (key: string) => string): string {
  const labels: Record<OperationsTaskAction, string> = {
    complete: "opsComplete",
    submit_for_approval: "opsSubmitApproval",
    approve: "opsApprove",
    reject: "opsReject",
    record_intervention: "opsRecordIntervention",
  };
  return t(labels[action]);
}

function TaskActionDialog({
  task,
  action,
  onClose,
  onSuccess,
}: {
  task: OperationsTask;
  action: OperationsTaskAction;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useLocale();
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noteRequired = action === "reject" || action === "record_intervention";

  const submit = async () => {
    if (noteRequired && !note.trim()) {
      setError(t("opsActionNoteRequired"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiFetch<OperationsTask>(
        `/api/v1/operations/board/tasks/${task.id}/${action}`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_version: task.version,
            note: note.trim() || null,
          }),
        },
      );
      onSuccess();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opsActionFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="operations-task-action-title"
        className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
      >
        <h2 id="operations-task-action-title" className="text-lg font-semibold text-slate-100">
          {taskActionLabel(action, t)}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          {task.tenant_name} · {task.title}
        </p>
        <label className="mt-4 block text-sm text-slate-300">
          {t("opsActionNote")}
          {noteRequired && <span className="text-rose-400"> *</span>}
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={4}
            maxLength={2000}
            className="mt-2 w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
          />
        </label>
        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {t("opsCancelAction")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving}
            className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            {saving ? t("loading") : t("opsConfirmAction")}
          </button>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ title, value, loading, icon, color, textColor }: {
  title: string;
  value?: number;
  loading: boolean;
  icon: React.ReactNode;
  color: string;
  textColor: string;
}) {
  return (
    <div className={`relative flex flex-col gap-3 overflow-hidden rounded-xl border p-4 ${color}`}>
      <div className="z-10 flex items-center justify-between">
        <span className="text-sm font-medium text-slate-300">{title}</span>
        <div className="rounded-md bg-white/5 p-1.5 shadow-sm">{icon}</div>
      </div>
      {loading ? (
        <div className="h-9 w-16 animate-pulse rounded bg-white/10" />
      ) : (
        <div className={`z-10 font-mono text-3xl font-bold tracking-tight ${textColor}`}>
          {value ?? 0}
        </div>
      )}
    </div>
  );
}

function SelectFilter({ value, onChange, options, placeholder, icon, isRtl }: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  icon?: React.ReactNode;
  isRtl?: boolean;
}) {
  return (
    <div className="group relative">
      <div className={`pointer-events-none absolute top-1/2 -translate-y-1/2 text-slate-500 ${isRtl ? "right-2.5" : "left-2.5"}`}>
        {icon}
      </div>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 min-w-[130px] appearance-none rounded-md border border-slate-700 bg-slate-950 py-1 pl-8 pr-8 text-xs text-slate-300 outline-none focus:border-emerald-500/50"
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
  );
}

function PriorityIndicator({ priority }: { priority: OperationsTask["priority"] }) {
  const style = priority === "urgent"
    ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]"
    : priority === "high"
      ? "bg-amber-500"
      : "bg-slate-600";
  return <span className={`block h-2.5 w-2.5 rounded-full ${style}`} />;
}

function Badge({ label, variant }: { label: string; variant: "emerald" | "blue" | "slate" }) {
  const styles = {
    emerald: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
    blue: "border-sky-500/20 bg-sky-500/10 text-sky-400",
    slate: "border-slate-500/20 bg-slate-500/10 text-slate-400",
  };
  return (
    <span className={`rounded border px-2 py-0.5 text-[11px] font-medium ${styles[variant]}`}>
      {label}
    </span>
  );
}

function StatusBadge({ status, t }: {
  status: OperationsTask["status"];
  t: (key: string) => string;
}) {
  const map: Record<OperationsTask["status"], { labelKey: string; style: string }> = {
    upcoming: { labelKey: "opsUpcoming", style: "border-slate-500/30 bg-slate-500/10 text-slate-300" },
    overdue: { labelKey: "opsOverdue", style: "border-rose-500/30 bg-rose-500/10 text-rose-400" },
    awaiting_approval: { labelKey: "opsAwaitingApproval", style: "border-amber-500/30 bg-amber-500/10 text-amber-400" },
    needs_intervention: { labelKey: "opsNeedsIntervention", style: "border-purple-500/30 bg-purple-500/10 text-purple-400" },
    completed: { labelKey: "opsCompleted", style: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
  };
  return (
    <span className={`rounded-md border px-2 py-1 text-[11px] font-medium ${map[status].style}`}>
      {t(map[status].labelKey)}
    </span>
  );
}

const statusStyles: Record<OperationTask["status"], string> = {
  pending: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  in_progress: "border-sky-400/30 bg-sky-400/10 text-sky-300",
  completed: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  submitted_for_approval: "border-violet-400/30 bg-violet-400/10 text-violet-300",
  approved: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  rejected: "border-rose-400/30 bg-rose-400/10 text-rose-300",
};

function StepHeading({ number, title, hint }: { number: string; title: string; hint: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="rounded-lg bg-emerald-400/10 px-2 py-1 text-xs font-bold tracking-widest text-emerald-300">
        {number}
      </span>
      <div>
        <h2 className="font-semibold text-white">{title}</h2>
        <p className="mt-1 text-xs text-slate-500">{hint}</p>
      </div>
    </div>
  );
}

function TrackingPanel({
  tasks,
  activeTasks,
  locale,
  t,
}: {
  tasks: OperationTask[];
  activeTasks: number;
  locale: string;
  t: (key: string) => string;
}) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:p-6">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
            {t("serviceTrackingEyebrow")}
          </p>
          <h2 className="mt-1 text-xl font-bold text-white">{t("serviceTrackingTitle")}</h2>
        </div>
        <div className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-300">
          {activeTasks} {t("serviceActiveRequests")}
        </div>
      </div>
      {tasks.length === 0 ? (
        <div className="mt-5 rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-500">
          {t("serviceNoRequests")}
        </div>
      ) : (
        <div className="mt-5 divide-y divide-slate-800">
          {tasks.slice(0, 6).map((task) => (
            <div
              key={task.id}
              className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="truncate font-medium text-slate-200">{task.title}</h3>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] ${statusStyles[task.status]}`}>
                    {t(statusKeys[task.status])}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {task.tenant_name} ·{" "}
                  {new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en-US", {
                    dateStyle: "medium",
                  }).format(new Date(task.created_at))}
                </p>
              </div>
              <span className="shrink-0 text-xs text-slate-500">
                {task.category === "financial"
                  ? t("serviceFinancial")
                  : task.category === "human_resources"
                    ? t("serviceHumanResources")
                    : t("serviceAdministrative")}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const statusKeys: Record<OperationTask["status"], string> = {
  pending: "opStatusPending",
  in_progress: "opStatusInProgress",
  completed: "opStatusCompleted",
  submitted_for_approval: "opStatusSubmittedForApproval",
  approved: "opStatusApproved",
  rejected: "opStatusRejected",
};

const domainStyles: Record<OpCategory, { selected: string; icon: string }> = {
  financial: {
    selected: "border-emerald-400/70 bg-emerald-400/10",
    icon: "bg-emerald-400/20 text-emerald-300",
  },
  human_resources: {
    selected: "border-sky-400/70 bg-sky-400/10",
    icon: "bg-sky-400/20 text-sky-300",
  },
  administrative: {
    selected: "border-violet-400/70 bg-violet-400/10",
    icon: "bg-violet-400/20 text-violet-300",
  },
};

export default function WorkspacePage() {
  const { t } = useLocale();
  const [view, setView] = useState<"services" | "data">("services");

  return (
    <>
      {view === "services" ? <ServicesWorkspacePage /> : <OperationsBoardPage />}
      <div className="fixed bottom-5 end-5 z-50 flex rounded-xl border border-slate-700 bg-slate-950/95 p-1 shadow-2xl backdrop-blur">
        <button
          type="button"
          onClick={() => setView("services")}
          className={`rounded-lg px-4 py-2 text-xs font-semibold transition ${
            view === "services"
              ? "bg-emerald-400 text-slate-950"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          {t("serviceWorkspace")}
        </button>
        <button
          type="button"
          onClick={() => setView("data")}
          className={`rounded-lg px-4 py-2 text-xs font-semibold transition ${
            view === "data"
              ? "bg-emerald-400 text-slate-950"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          {t("operations")}
        </button>
      </div>
    </>
  );
}

function ServicesWorkspacePage() {
  const { user } = useAuth();
  const { t, locale } = useLocale();
  const [bootstrap, setBootstrap] = useState<OperationsBootstrap | null>(null);
  const [tasks, setTasks] = useState<OperationTask[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<OpCategory>("financial");
  const [selectedProcedureId, setSelectedProcedureId] = useState<string>("");
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [employeeOptions, setEmployeeOptions] = useState<OdooEmployee[]>([]);
  const [employeesLoading, setEmployeesLoading] = useState(false);
  const [employeesError, setEmployeesError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const employeeRequestGeneration = useRef(0);

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [bootstrapResponse, taskResponse] = await Promise.all([
        fetchOperationsBootstrap(),
        fetchTasks({}),
      ]);
      setBootstrap(bootstrapResponse);
      setTasks(taskResponse.items);
      setSelectedTenantId((current) => {
        if (current && bootstrapResponse.tenants.some((tenant) => tenant.id === current)) {
          return current;
        }
        const currentTenant = user?.current_tenant?.id;
        return currentTenant
          && bootstrapResponse.tenants.some((tenant) => tenant.id === currentTenant)
          ? currentTenant
          : bootstrapResponse.tenants[0]?.id ?? "";
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errorLoading"));
    } finally {
      setLoading(false);
    }
  }, [t, user?.current_tenant?.id]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const service = SERVICE_CATALOG.find((item) => item.id === selectedCategory)
    ?? SERVICE_CATALOG[0];
  const procedure = service.procedures.find((item) => item.id === selectedProcedureId)
    ?? service.procedures[0];
  const eligibleTenants = bootstrap?.tenants ?? [];

  useEffect(() => {
    setSelectedProcedureId((current) =>
      service.procedures.some((item) => item.id === current)
        ? current
        : service.procedures[0]?.id ?? "",
    );
  }, [service]);

  const needsEmployeeOptions = Boolean(
    selectedCategory === "human_resources"
    && procedure?.fields.some((field) => field.key === "employee"),
  );

  useEffect(() => {
    const generation = employeeRequestGeneration.current + 1;
    employeeRequestGeneration.current = generation;
    let cancelled = false;

    if (!needsEmployeeOptions || !selectedTenantId) {
      setEmployeeOptions([]);
      setEmployeesError(null);
      setEmployeesLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setEmployeeOptions([]);
    setEmployeesError(null);
    setEmployeesLoading(true);

    const loadEmployees = async () => {
      try {
        const employees = await fetchOdooEmployees(selectedTenantId);

        if (cancelled || employeeRequestGeneration.current !== generation) return;
        setEmployeeOptions(employees);
        setFormData((current) => {
          if (
            !current.employee
            || employees.some((employee) => String(employee.id) === current.employee)
          ) {
            return current;
          }
          const next = { ...current };
          delete next.employee;
          return next;
        });
      } catch (err: unknown) {
        if (cancelled || employeeRequestGeneration.current !== generation) return;
        if (err instanceof ApiError && err.status === 403) {
          setEmployeesError(t("serviceEmployeePermissionError"));
        } else if (err instanceof ApiError && err.status === 409) {
          setEmployeesError(t("serviceEmployeeConnectionError"));
        } else {
          setEmployeesError(t("serviceEmployeeLoadError"));
        }
      } finally {
        if (!cancelled && employeeRequestGeneration.current === generation) {
          setEmployeesLoading(false);
        }
      }
    };

    void loadEmployees();
    return () => {
      cancelled = true;
    };
  }, [
    needsEmployeeOptions,
    selectedTenantId,
    t,
  ]);

  const activeTasks = useMemo(
    () => tasks.filter((task) => !["approved", "rejected"].includes(task.status)).length,
    [tasks],
  );

  const selectCategory = (category: OpCategory) => {
    const firstProcedure = SERVICE_CATALOG.find((item) => item.id === category)?.procedures[0];
    setSelectedCategory(category);
    setSelectedProcedureId(firstProcedure?.id ?? "");
    setFormData({});
    setSuccess(false);
  };

  const selectProcedure = (procedureId: string) => {
    setSelectedProcedureId(procedureId);
    setFormData({});
    setSuccess(false);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!procedure || !selectedTenantId || !user) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    const requestData = Object.fromEntries(
      procedure.fields
        .map((field) => [field.key, (formData[field.key] ?? "").trim()] as const)
        .filter(([, value]) => value),
    );
    try {
      const created = await createTask({
        tenant_id: selectedTenantId,
        title: t(procedure.titleKey),
        description: requestData.details || t(procedure.descriptionKey),
        category: selectedCategory,
        procedure_type: procedure.id,
        request_data: requestData,
        priority: "medium",
        assigned_user_id: user.id,
      });
      setTasks((current) => [created, ...current]);
      setFormData({});
      setSuccess(true);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 422) {
        setError(`${t("serviceInvalidRequest")} ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : t("serviceCreateError"));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <Header titleKey="serviceWorkspace" />
      <main className="min-w-0 flex-1 bg-[#0b1120] p-4 md:p-7">
        <div className="mx-auto max-w-7xl space-y-6">
          <section className="relative overflow-hidden rounded-2xl border border-emerald-400/20 bg-gradient-to-br from-emerald-500/10 via-slate-900 to-slate-900 p-6 md:p-8">
            <div className="relative z-10 max-w-2xl">
              <p className="mb-3 text-sm font-medium text-emerald-300">{t("serviceEyebrow")}</p>
              <h1 className="text-2xl font-bold tracking-tight text-white md:text-4xl">
                {t("serviceWelcome")}
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-7 text-slate-300 md:text-base">
                {t("serviceWelcomeDesc")}
              </p>
            </div>
            <div className="absolute -end-10 -top-16 h-56 w-56 rounded-full bg-emerald-400/10 blur-3xl" />
            <div className="absolute bottom-0 end-12 h-24 w-24 rounded-full border border-emerald-300/10" />
          </section>

          {error && (
            <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-400/30 bg-rose-950/30 p-4 text-sm text-rose-200">
              <span>{error}</span>
              <button
                onClick={() => void loadWorkspace()}
                className="shrink-0 font-medium text-rose-100 underline underline-offset-4"
              >
                {t("retry")}
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:p-6">
              <StepHeading
                number="01"
                title={t("serviceChooseAssociation")}
                hint={t("serviceAssociationHint")}
              />
              <select
                required
                value={selectedTenantId}
                 onChange={(event) => {
                   setSelectedTenantId(event.target.value);
                   setFormData({});
                   setSuccess(false);
                 }}
                disabled={loading || eligibleTenants.length === 0}
                className="mt-5 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none transition focus:border-emerald-400 md:max-w-xl"
                aria-label={t("opTenant")}
              >
                <option value="" disabled>{t("opSelectTenant")}</option>
                {eligibleTenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                ))}
              </select>
              {!loading && eligibleTenants.length === 0 && (
                <p className="mt-3 text-sm text-amber-300">{t("serviceNoAssociations")}</p>
              )}
            </section>

            <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:p-6">
              <StepHeading
                number="02"
                title={t("serviceChooseDomain")}
                hint={t("serviceDomainHint")}
              />
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                {SERVICE_CATALOG.map((item) => {
                  const selected = item.id === selectedCategory;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => selectCategory(item.id)}
                      className={`rounded-xl border p-4 text-start transition ${
                        selected
                          ? domainStyles[item.id].selected
                          : "border-slate-700 bg-slate-950/50 hover:border-slate-500"
                      }`}
                      aria-pressed={selected}
                    >
                      <span className={`mb-4 flex h-10 w-10 items-center justify-center rounded-lg text-lg ${
                        selected ? domainStyles[item.id].icon : "bg-slate-800 text-slate-400"
                      }`}>
                        {item.id === "financial" ? "ر.س" : item.id === "human_resources" ? "أ" : "إ"}
                      </span>
                      <span className="block font-semibold text-white">{t(item.titleKey)}</span>
                      <span className="mt-1 block text-xs leading-5 text-slate-400">
                        {t(item.descriptionKey)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:p-6">
              <StepHeading
                number="03"
                title={t("serviceChooseProcedure")}
                hint={t("serviceProcedureHint")}
              />
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                {service.procedures.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => selectProcedure(item.id)}
                    className={`rounded-xl border p-4 text-start transition ${
                      item.id === procedure?.id
                        ? "border-emerald-400/70 bg-emerald-400/10"
                        : "border-slate-700 bg-slate-950/50 hover:border-slate-500"
                    }`}
                    aria-pressed={item.id === procedure?.id}
                  >
                    <span className="block font-semibold text-white">{t(item.titleKey)}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-400">
                      {t(item.descriptionKey)}
                    </span>
                  </button>
                ))}
              </div>
            </section>

            {procedure && (
              <section className="rounded-2xl border border-emerald-400/20 bg-slate-900 p-5 md:p-6">
                <div className="flex flex-col justify-between gap-2 md:flex-row md:items-center">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
                      {t("serviceRequestDetails")}
                    </p>
                    <h2 className="mt-1 text-xl font-bold text-white">{t(procedure.titleKey)}</h2>
                  </div>
                  <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-400">
                    {t("serviceNoOdooWrite")}
                  </span>
                </div>
                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  {procedure.fields.map((field) => (
                    <label
                      key={field.key}
                      className={`flex flex-col gap-2 text-sm text-slate-300 ${
                        field.type === "textarea" ? "md:col-span-2" : ""
                      }`}
                    >
                      <span>
                        {t(field.labelKey)}
                        {field.required && <span className="ms-1 text-rose-300">*</span>}
                      </span>
                      {field.key === "employee" && needsEmployeeOptions ? (
                        <>
                          <select
                            required={field.required}
                            value={formData[field.key] ?? ""}
                            onChange={(event) => setFormData((current) => ({
                              ...current,
                              [field.key]: event.target.value,
                            }))}
                            disabled={employeesLoading || employeeOptions.length === 0}
                            className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <option value="">
                              {employeesLoading
                                ? t("serviceEmployeeLoading")
                                : t("serviceEmployeeSelect")}
                            </option>
                            {employeeOptions.map((employee) => (
                              <option key={employee.id} value={employee.id}>
                                {employee.name}
                              </option>
                            ))}
                          </select>
                          {employeesError && (
                            <span className="text-xs text-rose-300">{employeesError}</span>
                          )}
                        </>
                      ) : field.type === "textarea" ? (
                        <textarea
                          required={field.required}
                          rows={4}
                          value={formData[field.key] ?? ""}
                          onChange={(event) => setFormData((current) => ({
                            ...current,
                            [field.key]: event.target.value,
                          }))}
                          placeholder={t(field.placeholderKey)}
                          className="resize-y rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none placeholder:text-slate-600 focus:border-emerald-400"
                        />
                      ) : (
                        <input
                          required={field.required}
                          type={field.type ?? "text"}
                          value={formData[field.key] ?? ""}
                          onChange={(event) => setFormData((current) => ({
                            ...current,
                            [field.key]: event.target.value,
                          }))}
                          placeholder={t(field.placeholderKey)}
                          className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none placeholder:text-slate-600 focus:border-emerald-400"
                        />
                      )}
                    </label>
                  ))}
                </div>
                <div className="mt-6 flex flex-col items-stretch justify-between gap-3 border-t border-slate-800 pt-5 sm:flex-row sm:items-center">
                  <p className="text-xs text-slate-500">{t("serviceRequestNotice")}</p>
                  <button
                    type="submit"
                    disabled={saving || loading || !selectedTenantId}
                    className="rounded-xl bg-emerald-400 px-5 py-3 text-sm font-bold text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saving ? t("serviceSubmitting") : t("serviceSubmit")}
                  </button>
                </div>
                {success && (
                  <p className="mt-4 rounded-lg bg-emerald-400/10 p-3 text-sm text-emerald-300">
                    {t("serviceCreated")}
                  </p>
                )}
              </section>
            )}
          </form>

          <TrackingPanel tasks={tasks} activeTasks={activeTasks} locale={locale} t={t} />
          <div className="flex justify-center pb-4">
            <Link
              href="/operations"
              className="text-sm text-slate-400 underline-offset-4 hover:text-emerald-300 hover:underline"
            >
              {t("serviceOpenBoard")}
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
