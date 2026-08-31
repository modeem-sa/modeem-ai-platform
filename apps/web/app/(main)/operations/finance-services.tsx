"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale } from "@/components/locale-provider";
import {
  buildFinanceReadPayload,
  assistFinanceService,
  fetchOperationsCatalog,
  readFinanceService,
  resetFinanceSelectionForModule,
  resetFinanceSelectionForTenant,
  type BootstrapTenant,
  type FinanceReadRecord,
  type FinanceAssistantResult,
  type FinanceServiceKey,
  type OperationsCatalog,
} from "@/lib/operations";

const PAGE_SIZE = 50;

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function rowKey(row: FinanceReadRecord, index: number): string {
  return typeof row.id === "number" || typeof row.id === "string"
    ? String(row.id)
    : String(index);
}

export function FinanceServices({
  tenants,
  bootstrapLoading,
  bootstrapError,
}: {
  tenants: BootstrapTenant[];
  bootstrapLoading: boolean;
  bootstrapError: string | null;
}) {
  const { t, locale } = useLocale();
  const [selection, setSelection] = useState(() => resetFinanceSelectionForTenant(""));
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [readLoading, setReadLoading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [assistant, setAssistant] = useState<FinanceAssistantResult | null>(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);

  useEffect(() => {
    if (!selection.tenant_id) {
      setCatalog(null);
      setCatalogLoading(false);
      return;
    }

    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError(null);
    void fetchOperationsCatalog(selection.tenant_id)
      .then((nextCatalog) => {
        if (!cancelled) setCatalog(nextCatalog);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCatalog(null);
          setCatalogError(err instanceof Error ? err.message : t("errorLoading"));
        }
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, [selection.tenant_id, t]);

  const selectedModule = useMemo(
    () => catalog?.modules.find((module) => module.key === selection.module_key) ?? null,
    [catalog, selection.module_key],
  );
  const columns = useMemo(() => {
    const keys = new Set<string>();
    selection.page?.records.forEach((row) => Object.keys(row).forEach((key) => keys.add(key)));
    return [...keys];
  }, [selection.page]);

  const read = useCallback(async (offset: number) => {
    if (!selection.tenant_id || !selection.service) return;
    setReadLoading(true);
    setReadError(null);
    try {
      const page = await readFinanceService(buildFinanceReadPayload(
        selection.tenant_id, selection.service, PAGE_SIZE, offset,
      ));
      setSelection((current) => (
        current.tenant_id === selection.tenant_id
          && current.module_key === selection.module_key
          && current.service === selection.service
          ? { ...current, page }
          : current
      ));
      setAssistant(null);
      setAssistantError(null);
    } catch (err: unknown) {
      setReadError(err instanceof Error ? err.message : t("errorLoading"));
    } finally {
      setReadLoading(false);
    }
  }, [selection.module_key, selection.service, selection.tenant_id, t]);

  const analyze = useCallback(async () => {
    if (!selection.tenant_id || !selection.service || !selection.page) return;
    setAssistantLoading(true);
    setAssistantError(null);
    try {
      const result = await assistFinanceService(
        buildFinanceReadPayload(
          selection.tenant_id,
          selection.service,
          selection.page.limit,
          selection.page.offset,
        ),
        locale,
      );
      setAssistant(result);
    } catch (err: unknown) {
      setAssistantError(err instanceof Error ? err.message : t("opAssistantFailed"));
    } finally {
      setAssistantLoading(false);
    }
  }, [locale, selection.page, selection.service, selection.tenant_id, t]);

  const chooseTenant = (tenantId: string) => {
    setSelection(resetFinanceSelectionForTenant(tenantId));
    setCatalog(null);
    setCatalogError(null);
    setReadError(null);
    setAssistant(null);
    setAssistantError(null);
  };
  const chooseModule = (moduleKey: string) => {
    setSelection((current) => resetFinanceSelectionForModule(current, moduleKey));
    setReadError(null);
    setAssistant(null);
    setAssistantError(null);
  };
  const chooseService = (service: FinanceServiceKey | "") => {
    setSelection((current) => ({ ...current, service, page: null }));
    setReadError(null);
    setAssistant(null);
    setAssistantError(null);
  };

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 md:p-6">
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-slate-100">{t("opFinanceServices")}</h2>
        <p className="mt-1 text-sm text-slate-400">{t("opFinanceServicesDesc")}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <label className="flex flex-col gap-1.5 text-sm text-slate-300">
          {t("opTenant")}
          <select value={selection.tenant_id} onChange={(event) => chooseTenant(event.target.value)}
            disabled={bootstrapLoading}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-200 outline-none focus:border-indigo-500 disabled:opacity-50">
            <option value="">{bootstrapLoading ? t("loading") : t("opSelectTenant")}</option>
            {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-slate-300">
          {t("opOdooModule")}
          <select value={selection.module_key} onChange={(event) => chooseModule(event.target.value)}
            disabled={!selection.tenant_id || catalogLoading || !!catalogError}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-200 outline-none focus:border-indigo-500 disabled:opacity-50">
            <option value="">{catalogLoading ? t("opLoadingModules") : t("opSelectModule")}</option>
            {catalog?.modules.map((module) => <option key={module.key} value={module.key}>{module.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-slate-300">
          {t("opService")}
          <select value={selection.service} onChange={(event) => chooseService(event.target.value as FinanceServiceKey | "")}
            disabled={!selectedModule}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-200 outline-none focus:border-indigo-500 disabled:opacity-50">
            <option value="">{t("opSelectService")}</option>
            {selectedModule?.services.map((service) => <option key={service.key} value={service.key}>{service.label}</option>)}
          </select>
        </label>
      </div>

      {(bootstrapError || catalogError) && (
        <div className="mt-4 rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">
          {bootstrapError || catalogError}
        </div>
      )}

      {selection.service && (
        <div className="mt-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <p className="text-sm text-slate-400">{t("opFinanceReadyToRead")}</p>
            <button onClick={() => void read(0)} disabled={readLoading}
              className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50">
              {readLoading ? t("loading") : t("opReadService")}
            </button>
          </div>
          {readError && <div className="mb-4 rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">{readError}</div>}
          {readLoading ? <div className="py-10 text-center text-slate-400">{t("loading")}</div>
            : selection.page && selection.page.records.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-700 p-10 text-center text-slate-400">{t("noRecords")}</div>
            ) : selection.page ? (
              <>
                <div className="mb-4 rounded-xl border border-indigo-800/50 bg-indigo-950/20 p-4">
                  <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                    <div>
                      <h3 className="font-semibold text-indigo-200">{t("opAssistantTitle")}</h3>
                      <p className="mt-1 text-sm text-slate-400">{t("opAssistantDesc")}</p>
                    </div>
                    <button
                      onClick={() => void analyze()}
                      disabled={assistantLoading || selection.page.records.length === 0}
                      className="shrink-0 rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
                    >
                      {assistantLoading ? t("opAssistantAnalyzing") : t("opAssistantAnalyze")}
                    </button>
                  </div>
                  {assistantError && (
                    <div className="mt-3 rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">
                      {assistantError}
                    </div>
                  )}
                  {assistant && <AssistantResult result={assistant} t={t} />}
                </div>
                <div className="overflow-x-auto rounded-lg border border-slate-800">
                  <table className="w-full text-sm text-slate-300">
                    <thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-500"><tr>
                      {columns.map((column) => <th key={column} className="px-4 py-3 text-start font-medium">{column}</th>)}
                    </tr></thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {selection.page.records.map((row, index) => <tr key={rowKey(row, index)} className="hover:bg-slate-800/30">
                        {columns.map((column) => <td key={column} className="px-4 py-3 align-top">{displayValue(row[column])}</td>)}
                      </tr>)}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 flex items-center justify-between text-sm">
                  <button disabled={readLoading || selection.page.offset === 0} onClick={() => void read(Math.max(0, selection.page!.offset - PAGE_SIZE))}
                    className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800 disabled:opacity-50">{t("previewPrev")}</button>
                  <span className="text-slate-500">{selection.page.offset + 1}–{selection.page.offset + selection.page.returned_count}</span>
                  <button disabled={readLoading || !selection.page.has_more} onClick={() => void read(selection.page!.next_offset ?? selection.page!.offset + PAGE_SIZE)}
                    className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800 disabled:opacity-50">{t("previewNext")}</button>
                </div>
              </>
            ) : null}
        </div>
      )}
    </section>
  );
}

function AssistantResult({
  result,
  t,
}: {
  result: FinanceAssistantResult;
  t: (key: string) => string;
}) {
  const severityClass = {
    info: "border-sky-800/50 bg-sky-950/20",
    attention: "border-amber-800/50 bg-amber-950/20",
    risk: "border-rose-800/50 bg-rose-950/20",
  };
  const modeClass = {
    automatic: "bg-emerald-500/15 text-emerald-300",
    approval_required: "bg-amber-500/15 text-amber-300",
    manual: "bg-slate-500/15 text-slate-300",
  };
  return (
    <div className="mt-4 space-y-4 border-t border-indigo-900/40 pt-4">
      <div>
        <h4 className="text-base font-semibold text-slate-100">{result.headline}</h4>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-300">{result.summary}</p>
      </div>
      {result.findings.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            {t("opAssistantFindings")}
          </h4>
          <div className="grid gap-2 md:grid-cols-2">
            {result.findings.map((finding, index) => (
              <div key={`${finding.title}-${index}`} className={`rounded-lg border p-3 ${severityClass[finding.severity]}`}>
                <div className="text-sm font-semibold text-slate-200">{finding.title}</div>
                <p className="mt-1 text-xs leading-6 text-slate-400">{finding.evidence}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {result.automation_opportunities.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            {t("opAssistantAutomations")}
          </h4>
          <div className="space-y-2">
            {result.automation_opportunities.map((opportunity, index) => (
              <div key={`${opportunity.workflow_key}-${index}`} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-slate-200">{opportunity.title}</span>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${modeClass[opportunity.mode]}`}>
                    {t(`opAssistantMode_${opportunity.mode}`)}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-6 text-slate-400">{opportunity.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
        <span className="text-xs font-semibold text-slate-500">{t("opAssistantNextStep")}</span>
        <p className="mt-1 text-sm text-slate-200">{result.next_step}</p>
      </div>
      <p className="text-[10px] text-slate-600">
        {t("opAssistantDisclaimer")} · {Math.round(result.confidence * 100)}%
      </p>
    </div>
  );
}