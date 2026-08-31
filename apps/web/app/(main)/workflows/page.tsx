"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import {
  type AutomationCatalogResponse,
  type AutomationMode,
  type AutomationStep,
  type AutomationWorkflow,
  fetchAutomationCatalog,
  resetAutomationWorkflow,
  updateAutomationWorkflow,
} from "@/lib/automation";
import { ApiError } from "@/lib/api";
import {
  type OperationsBootstrap,
  fetchOperationsBootstrap,
} from "@/lib/operations";

const MODES: AutomationMode[] = ["automatic", "approval_required", "manual"];

export default function WorkflowsPage() {
  const { t, locale } = useLocale();
  const [bootstrap, setBootstrap] = useState<OperationsBootstrap | null>(null);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [catalog, setCatalog] = useState<AutomationCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchOperationsBootstrap()
      .then((data) => {
        if (cancelled) return;
        setBootstrap(data);
        setSelectedTenantId((current) => current || data.tenants[0]?.id || "");
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadCatalog = useCallback(async (tenantId: string) => {
    if (!tenantId) {
      setCatalog(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setCatalog(await fetchAutomationCatalog(tenantId));
    } catch (cause: unknown) {
      setCatalog(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog(selectedTenantId);
  }, [loadCatalog, selectedTenantId]);

  const modules = useMemo(
    () => Array.from(new Set(catalog?.workflows.map((workflow) => workflow.module) ?? [])),
    [catalog],
  );

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-slate-950">
      <Header titleKey="workflows" />
      <main className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="mx-auto max-w-6xl space-y-6">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="max-w-2xl">
                <h2 className="text-lg font-bold text-slate-100">
                  {t("wfAutomationPaths")}
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-400">
                  {t("wfAutomationPathsDesc")}
                </p>
              </div>
              <label className="block min-w-64 text-xs font-semibold text-slate-400">
                {t("opSelectTenant")}
                <select
                  className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
                  value={selectedTenantId}
                  onChange={(event) => setSelectedTenantId(event.target.value)}
                  disabled={!bootstrap?.tenants.length}
                >
                  {!bootstrap?.tenants.length && <option value="">{t("noRecords")}</option>}
                  {bootstrap?.tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {catalog && (
              <div className="mt-4 flex items-center gap-2 border-t border-slate-800 pt-4 text-xs">
                <span
                  className={`h-2 w-2 rounded-full ${
                    catalog.can_manage ? "bg-emerald-400" : "bg-amber-400"
                  }`}
                />
                <span className="text-slate-400">
                  {catalog.can_manage ? t("wfCanManage") : t("wfReadOnly")}
                </span>
              </div>
            )}
          </section>

          {error && (
            <div className="flex items-start gap-3 rounded-xl border border-rose-900/50 bg-rose-950/30 p-4 text-sm text-rose-300">
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center text-slate-400">
              {t("loading")}
            </div>
          ) : catalog ? (
            <div className="space-y-9 pb-16">
              {modules.map((module) => (
                <section key={module} className="space-y-4">
                  <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400">
                    {t(`wfModule_${module}`)}
                  </h3>
                  {catalog.workflows
                    .filter((workflow) => workflow.module === module)
                    .map((workflow) => (
                      <WorkflowCard
                        key={`${catalog.tenant_id}:${workflow.key}:${workflow.version}`}
                        workflow={workflow}
                        tenantId={catalog.tenant_id}
                        canManage={catalog.can_manage}
                        locale={locale}
                        onRefresh={() => loadCatalog(catalog.tenant_id)}
                      />
                    ))}
                </section>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
              {t("wfSelectTenant")}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function WorkflowCard({
  workflow,
  tenantId,
  canManage,
  locale,
  onRefresh,
}: {
  workflow: AutomationWorkflow;
  tenantId: string;
  canManage: boolean;
  locale: string;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [enabled, setEnabled] = useState(workflow.enabled);
  const [stepModes, setStepModes] = useState(workflow.step_modes);
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const changed =
    enabled !== workflow.enabled ||
    JSON.stringify(stepModes) !== JSON.stringify(workflow.step_modes);
  const label = locale === "ar" ? workflow.label_ar : workflow.label_en;
  const description =
    locale === "ar" ? workflow.description_ar : workflow.description_en;

  async function save() {
    setBusy("save");
    setError(null);
    try {
      await updateAutomationWorkflow(workflow.key, {
        tenant_id: tenantId,
        enabled,
        step_modes: stepModes,
        expected_version: workflow.version,
      });
      await onRefresh();
    } catch (cause: unknown) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError(t("wfConflict"));
        await onRefresh();
      } else {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setBusy("reset");
    setError(null);
    try {
      await resetAutomationWorkflow(workflow.key, {
        tenant_id: tenantId,
        expected_version: workflow.version,
      });
      await onRefresh();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article
      className={`overflow-hidden rounded-xl border ${
        enabled ? "border-slate-700 bg-slate-900/80" : "border-slate-800 bg-slate-900/35"
      }`}
    >
      <div className="flex flex-col gap-4 border-b border-slate-800 p-5 md:flex-row md:items-start md:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-lg font-bold text-slate-100">{label}</h4>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
              workflow.customized
                ? "border-indigo-500/30 bg-indigo-500/10 text-indigo-300"
                : "border-slate-700 bg-slate-800 text-slate-400"
            }`}>
              {workflow.customized ? t("wfCustomized") : t("wfModeemDefault")}
            </span>
            <span className="font-mono text-[11px] text-slate-500">
              v{workflow.version}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
          {!workflow.steps.every((step) => step.executor_available) && (
            <p className="mt-2 text-xs font-medium text-amber-400">
              {t("wfProposedUnavailable")}
            </p>
          )}
        </div>
        <button
          type="button"
          disabled={!canManage}
          onClick={() => setEnabled((current) => !current)}
          className={`min-w-28 rounded-lg border px-4 py-2 text-sm font-bold transition ${
            enabled
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-slate-700 bg-slate-950 text-slate-500"
          } disabled:cursor-not-allowed disabled:opacity-60`}
        >
          {enabled ? t("wfEnabled") : t("wfDisabled")}
        </button>
      </div>

      {error && (
        <div className="border-b border-rose-900/40 bg-rose-950/20 px-5 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <div className="space-y-3 p-5">
        {workflow.steps.map((step, index) => (
          <StepRow
            key={step.key}
            step={step}
            index={index + 1}
            mode={stepModes[step.key] ?? step.default_mode}
            enabled={enabled}
            canManage={canManage}
            onChange={(mode) =>
              setStepModes((current) => ({ ...current, [step.key]: mode }))
            }
          />
        ))}
      </div>

      {(changed || workflow.customized) && canManage && (
        <footer className="flex flex-col gap-3 border-t border-slate-800 bg-slate-950/50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-xs text-slate-400">
            {changed ? t("wfUnsavedChanges") : t("wfCustomizedHint")}
          </span>
          <div className="flex gap-2">
            {workflow.customized && !changed && (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void reset()}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {t("wfRestoreDefault")}
              </button>
            )}
            {changed && (
              <>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => {
                    setEnabled(workflow.enabled);
                    setStepModes(workflow.step_modes);
                  }}
                  className="rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-800"
                >
                  {t("opCancel")}
                </button>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void save()}
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-400 disabled:opacity-50"
                >
                  {busy === "save" ? t("wfSaving") : t("wfSave")}
                </button>
              </>
            )}
          </div>
        </footer>
      )}
    </article>
  );
}

function StepRow({
  step,
  index,
  mode,
  enabled,
  canManage,
  onChange,
}: {
  step: AutomationStep;
  index: number;
  mode: AutomationMode;
  enabled: boolean;
  canManage: boolean;
  onChange: (mode: AutomationMode) => void;
}) {
  const { t } = useLocale();
  return (
    <div className={`flex flex-col gap-4 rounded-lg border p-4 lg:flex-row lg:items-center lg:justify-between ${
      step.executor_available ? "border-slate-800 bg-slate-950/50" : "border-amber-900/40 bg-amber-950/10"
    } ${enabled ? "" : "opacity-55"}`}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-800 font-mono text-xs text-slate-400">
          {index}
        </span>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-200">{t(`wfStep_${step.key}`)}</span>
            {step.type === "external_write" && (
              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">
                {t("wfExternalWrite")}
              </span>
            )}
            {step.type === "approval" && (
              <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-bold text-sky-300">
                {t("wfHumanApproval")}
              </span>
            )}
          </div>
          {!step.executor_available && (
            <p className="mt-1 text-xs text-amber-400">{t("wfNoExecutor")}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1 rounded-lg border border-slate-800 bg-slate-900 p-1">
        {MODES.map((candidate) => {
          const allowed = step.allowed_modes.includes(candidate);
          const selected = mode === candidate;
          return (
            <button
              key={candidate}
              type="button"
              disabled={!canManage || !enabled || !allowed || !step.executor_available}
              onClick={() => onChange(candidate)}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                selected
                  ? "bg-slate-700 text-white"
                  : allowed
                    ? "text-slate-400 hover:bg-slate-800"
                    : "cursor-not-allowed text-slate-700"
              } disabled:pointer-events-none`}
            >
              {selected && <span aria-hidden="true">✓</span>}
              {t(`wfMode_${candidate}`)}
            </button>
          );
        })}
      </div>
    </div>
  );
}