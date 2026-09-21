"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { IconRefreshCw } from "@/components/icons";
import { useLocale } from "@/components/locale-provider";
import {
  fetchAllModuleInventory,
  type ModuleInventory,
} from "@/lib/service-requests";

export function ModuleInventory({ tenantId }: { tenantId: string }) {
  const { locale } = useLocale();
  const ar = locale === "ar";
  const [inventory, setInventory] = useState<ModuleInventory | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setInventory(await fetchAllModuleInventory(tenantId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const records = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(locale);
    if (!needle) return inventory?.records ?? [];
    return (inventory?.records ?? []).filter(
      (record) =>
        record.name.toLocaleLowerCase(locale).includes(needle)
        || record.shortdesc.toLocaleLowerCase(locale).includes(needle),
    );
  }, [inventory, locale, search]);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-white">
            {ar ? "مخزون موديولات Odoo المثبتة" : "Installed Odoo Module Inventory"}
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            {ar
              ? "قراءة تقنية مباشرة دون تثبيت أو ترقية أو حذف."
              : "Live technical read only; no install, upgrade, or removal."}
          </p>
          {inventory && (
            <p className="mt-1 text-xs text-slate-500">
              {ar ? "الاتصال:" : "Connection:"} {inventory.connection.name}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-emerald-700 px-3 py-2 text-xs text-emerald-300 disabled:opacity-50"
        >
          <IconRefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          {ar ? "تحديث الموديولات" : "Refresh Modules"}
        </button>
      </div>

      {inventory && (
        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
          {[
            [ar ? "المثبتة" : "Installed", inventory.summary.installed],
            [ar ? "التطبيقات" : "Applications", inventory.summary.applications],
            [ar ? "تقنية/مساندة" : "Technical", inventory.summary.technical],
            [ar ? "مصرح بها" : "Authorized", inventory.summary.visible_to_user],
            [ar ? "دعم القراءة" : "AI Read", inventory.summary.read_supported],
            [ar ? "دعم التنفيذ" : "AI Execute", inventory.summary.execution_supported],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="text-lg font-semibold text-white">{value}</div>
              <div className="text-[11px] text-slate-500">{label}</div>
            </div>
          ))}
        </div>
      )}

      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={ar ? "ابحث بالاسم التقني أو الوصف" : "Search technical name or description"}
        className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none"
      />

      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      {!error && (
        <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-slate-800">
          {records.map((module) => (
            <div
              key={`${module.name}:${module.id}`}
              className="grid gap-2 border-b border-slate-800 p-3 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto]"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-slate-200">{module.shortdesc || module.name}</div>
                <div className="font-mono text-xs text-slate-500">{module.name}</div>
              </div>
              <div className="flex flex-wrap items-center gap-1 text-[10px]">
                <span className="rounded bg-slate-800 px-2 py-1 text-slate-300">
                  {module.application ? (ar ? "تطبيق" : "App") : (ar ? "تقني" : "Technical")}
                </span>
                <span className={`rounded px-2 py-1 ${module.authorized ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-500"}`}>
                  {ar ? "مصرح" : "Authorized"}
                </span>
                <span className={`rounded px-2 py-1 ${module.capabilities.read_supported ? "bg-cyan-950 text-cyan-300" : "bg-slate-800 text-slate-500"}`}>
                  {ar ? "قراءة AI" : "AI Read"}
                </span>
                <span className={`rounded px-2 py-1 ${module.capabilities.execution_supported ? "bg-amber-950 text-amber-300" : "bg-slate-800 text-slate-500"}`}>
                  {ar ? "تنفيذ AI" : "AI Execute"}
                </span>
              </div>
            </div>
          ))}
          {!loading && records.length === 0 && (
            <p className="p-4 text-center text-sm text-slate-500">
              {ar ? "لا توجد موديولات مطابقة." : "No matching modules."}
            </p>
          )}
        </div>
      )}
    </section>
  );
}