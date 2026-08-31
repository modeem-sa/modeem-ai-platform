"use client";

import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import { useAuth } from "@/components/auth-provider";
import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  type OperationsBoardResponse,
  type OperationsTask,
} from "@/lib/api";

const Icons = {
  Filter: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
  ),
  AlertCircle: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
  ),
  Clock: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
  ),
  CheckCircle2: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
  ),
  AlertTriangle: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
  ),
  Building2: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/></svg>
  ),
  Calendar: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
  ),
  Briefcase: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
  ),
  User: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
  ),
  Loader2: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
  ),
  Inbox: ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
  )
};

export default function OperationsBoardPage() {
  const { t, locale } = useLocale();
  useAuth();

  const [data, setData] = useState<OperationsBoardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
    </div>
  );
}

// Subcomponents

function SummaryCard({ title, value, loading, icon, color, textColor }: { title: string; value?: number; loading: boolean; icon: React.ReactNode; color: string; textColor: string; }) {
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-3 relative overflow-hidden ${color}`}>
      <div className="flex items-center justify-between z-10">
        <span className="text-sm font-medium text-slate-300">{title}</span>
        <div className="p-1.5 rounded-md bg-white/5 backdrop-blur-sm shadow-sm">{icon}</div>
      </div>
      <div className="z-10">
        {loading ? (
          <div className="h-9 w-16 animate-pulse rounded bg-white/10" />
        ) : (
          <div className={`text-3xl font-bold font-mono tracking-tight ${textColor}`}>
            {value ?? 0}
          </div>
        )}
      </div>
      {/* Decorative gradient orb */}
      <div className="absolute -bottom-6 -right-6 w-24 h-24 bg-white/5 rounded-full blur-2xl pointer-events-none" />
    </div>
  );
}

function SelectFilter({
  value,
  onChange,
  options,
  placeholder,
  icon,
  isRtl
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  icon?: React.ReactNode;
  isRtl?: boolean;
}) {
  return (
    <div className="relative group">
      <div className={`absolute top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none group-focus-within:text-emerald-400 transition-colors ${isRtl ? "right-2.5" : "left-2.5"}`}>
        {icon}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`h-8 py-1 rounded-md bg-slate-950 border border-slate-700 text-xs text-slate-300 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/50 appearance-none min-w-[130px] hover:border-slate-600 transition-colors ${isRtl ? "pr-8 pl-8" : "pl-8 pr-8"}`}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {/* Custom arrow */}
      <div className={`absolute top-1/2 -translate-y-1/2 pointer-events-none opacity-50 ${isRtl ? "left-2.5" : "right-2.5"}`}>
        <svg width="10" height="6" viewBox="0 0 10 6" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </div>
    </div>
  );
}

function PriorityIndicator({ priority }: { priority: OperationsTask["priority"] }) {
  if (priority === "urgent") {
    return (
      <div className="flex items-center justify-center group-hover:scale-110 transition-transform" title="Urgent">
        <div className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)] animate-pulse" />
      </div>
    );
  }
  if (priority === "high") {
    return (
      <div className="flex items-center justify-center group-hover:scale-110 transition-transform" title="High">
        <div className="w-2.5 h-2.5 rounded-full bg-amber-500" />
      </div>
    );
  }
  return (
    <div className="flex items-center justify-center" title="Normal">
      <div className="w-2.5 h-2.5 rounded-full bg-slate-600" />
    </div>
  );
}

function Badge({ label, variant }: { label: string; variant: "emerald" | "blue" | "slate" }) {
  const styles = {
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    blue: "bg-sky-500/10 text-sky-400 border-sky-500/20",
    slate: "bg-slate-500/10 text-slate-400 border-slate-500/20",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${styles[variant]}`}>
      {label}
    </span>
  );
}

function StatusBadge({ status, t }: { status: OperationsTask["status"]; t: (k: string) => string }) {
  const map: Record<OperationsTask["status"], { labelKey: string; style: string }> = {
    upcoming: { labelKey: "opsUpcoming", style: "bg-slate-500/10 text-slate-300 border-slate-500/30" },
    overdue: { labelKey: "opsOverdue", style: "bg-rose-500/10 text-rose-400 border-rose-500/30" },
    awaiting_approval: { labelKey: "opsAwaitingApproval", style: "bg-amber-500/10 text-amber-400 border-amber-500/30" },
    needs_intervention: { labelKey: "opsNeedsIntervention", style: "bg-purple-500/10 text-purple-400 border-purple-500/30" },
    completed: { labelKey: "opsCompleted", style: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
  };

  const config = map[status];

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium border ${config.style}`}>
      {status === "completed" && <Icons.CheckCircle2 className="w-3 h-3 opacity-70" />}
      {status === "overdue" && <Icons.Clock className="w-3 h-3 opacity-70" />}
      {status === "needs_intervention" && <Icons.AlertTriangle className="w-3 h-3 opacity-70" />}
      {t(config.labelKey)}
    </span>
  );
}
