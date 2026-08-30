import { useState } from "react";
import { useLocale } from "@/components/locale-provider";
import { OperationTask, generateAction, submitAction, approveAction, rejectAction, retryAction } from "@/lib/operations";

export function OdooTaskCard({ task, onRefresh }: { task: OperationTask, onRefresh: () => void }) {
  const { locale, t } = useLocale();
  const dateFmt = new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en", { dateStyle: "medium" });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showRejectReason, setShowRejectReason] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const snapshot = (task.source_snapshot as Record<string, string | number | null | undefined>) || {};
  const amount = Number(snapshot.residual ?? snapshot.total ?? 0);
  const currency = String(snapshot.currency ?? "");
  
  const action = task.action;
  
  const handleGenerate = async () => {
    setLoading(true); setError(null);
    try {
      await generateAction(task.id, task.version);
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedGenerate"));
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    setLoading(true); setError(null);
    try {
      await submitAction(task.id, task.version);
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedSubmit"));
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!action) return;
    setLoading(true); setError(null);
    try {
      await approveAction(task.id, task.version, action.version, action.proposal_hash);
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedApprove"));
    } finally {
      setLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!action) return;
    setLoading(true); setError(null);
    try {
      await retryAction(task.id, task.version, action.version, action.proposal_hash);
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedRetry"));
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!action || !rejectReason.trim()) return;
    setLoading(true); setError(null);
    try {
      await rejectAction(task.id, task.version, action.version, action.proposal_hash);
      setShowRejectReason(false);
      setRejectReason("");
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedReject"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col rounded-xl border border-sky-800/40 bg-slate-900/80 p-5 shadow-sm transition-shadow">
      {/* Header: Odoo Facts */}
      <div className="mb-4 border-b border-slate-800 pb-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-sky-400/80">
              {task.tenant_name}
            </span>
            <h3 className="mt-1 text-lg font-bold text-slate-100">
              {snapshot.partner_display_name || t("opUnknownCustomer")}
            </h3>
            <p className="text-sm font-medium text-slate-400" dir="ltr">
              #{snapshot.invoice_number || t("opDraftInvoice")}
            </p>
          </div>
          <div className="text-right">
            <div className="text-xl font-bold text-slate-100" dir="ltr">
              {new Intl.NumberFormat(locale === "ar" ? "ar" : "en", { style: "currency", currency: currency || "USD" }).format(amount)}
            </div>
            <div className="text-xs font-medium text-slate-500">
              {snapshot.payment_state === 'not_paid' ? t("opUnpaid") : snapshot.payment_state}
            </div>
          </div>
        </div>
        <div className="mt-4 flex gap-4 text-xs text-slate-400">
          <div>
            <span className="block text-[10px] uppercase text-slate-500">{t("opDueDate")}</span>
            <span className={snapshot.due_date && new Date(snapshot.due_date) < new Date() ? "text-rose-400 font-semibold" : ""}>
              {snapshot.due_date ? dateFmt.format(new Date(snapshot.due_date)) : "—"}
            </span>
          </div>
          <div>
            <span className="block text-[10px] uppercase text-slate-500">{t("opSynced")}</span>
            {task.source_synced_at ? dateFmt.format(new Date(task.source_synced_at)) : "—"}
          </div>
        </div>
      </div>

      {/* AI Draft Area */}
      {action && action.proposal && (
        <div className="mb-4 rounded-lg bg-indigo-950/20 p-4 border border-indigo-900/30">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-bold text-indigo-400 flex items-center gap-1.5">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              {t("opAiDraftProposal")}
            </span>
            <span className="text-[10px] text-indigo-500/70">
              {t("opModel")}: {String((action.proposal.metadata as Record<string, unknown> | undefined)?.model || t("opUnknown"))} ({t("opConf")}: {String(action.proposal.confidence || t("opNA"))})
            </span>
          </div>
          
          <h4 className="font-medium text-slate-200 mb-1">{String(action.proposal.title || action.proposal.summary || t("opActionProposed"))}</h4>
          {typeof action.proposal.note === "string" && action.proposal.note && (
            <p className="text-sm text-slate-400 mb-2 italic">&quot;{action.proposal.note}&quot;</p>
          )}
          {typeof action.proposal.priority_reason === "string" && action.proposal.priority_reason && (
            <p className="text-xs text-indigo-300/80">{t("opReasoning")}: {action.proposal.priority_reason}</p>
          )}

          <div className="mt-3 flex items-center justify-between border-t border-indigo-900/30 pt-3 text-xs">
            <span className="text-slate-500">{t("status")}: {action.status}</span>
            {action.status === 'succeeded' && action.external_activity_id && (
              <span className="text-emerald-400">{t("opVerifiedActivity")}: {action.external_activity_id}</span>
            )}
            {action.status === 'failed' && (
              <span className="text-rose-400">{t("opError")}: {action.error || t("opFailedVerifyExecution")}</span>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg bg-rose-950/40 p-3 text-sm text-rose-300 border border-rose-900">
          {error}
        </div>
      )}

      {/* Execution Controls */}
      <div className="mt-auto pt-2">
        {showRejectReason ? (
          <form onSubmit={handleReject} className="flex flex-col gap-2">
            <input 
              type="text" 
              required
              placeholder={t("opRejectReasonPlaceholder")}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-white outline-none focus:border-rose-500"
            />
            <div className="flex gap-2">
              <button type="submit" disabled={loading} className="flex-1 bg-rose-500 text-white rounded py-1.5 text-xs font-medium hover:bg-rose-400 disabled:opacity-50">
                {t("opConfirmReject")}
              </button>
              <button type="button" onClick={() => setShowRejectReason(false)} disabled={loading} className="px-3 text-xs text-slate-400 hover:text-white">
                {t("opCancel")}
              </button>
            </div>
          </form>
        ) : (
          <div className="flex gap-2">
            {!action ? (
              <button onClick={handleGenerate} disabled={loading} className="flex-1 bg-indigo-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors">
                {loading ? t("opGenerating") : t("opGenerateAI")}
              </button>
            ) : action.status === 'failed' ? (
              <button onClick={handleRetry} disabled={loading} className="flex-1 bg-amber-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-amber-500 disabled:opacity-50 transition-colors">
                {loading ? t("opRetrying") : t("opRetryExact")}
              </button>
            ) : action.status === 'proposed' ? (
              <>
                <button onClick={handleSubmit} disabled={loading} className="flex-1 bg-sky-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50 transition-colors">
                  {loading ? t("opSubmitting") : t("opSubmitApproval")}
                </button>
                <button onClick={handleGenerate} disabled={loading} className="px-3 bg-slate-800 text-slate-300 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors" title={t("opRegenerate")}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.59-9.21l5.67-5.67"/></svg>
                </button>
              </>
            ) : action.status === 'awaiting_approval' ? (
              <>
                <button onClick={handleApprove} disabled={loading} className="flex-1 bg-emerald-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50 transition-colors">
                  {loading ? t("opApproving") : t("opApproveHash")}
                </button>
                <button onClick={() => setShowRejectReason(true)} disabled={loading} className="flex-1 bg-rose-900/50 text-rose-400 rounded-lg py-2 text-sm font-medium hover:bg-rose-800 hover:text-rose-200 disabled:opacity-50 transition-colors">
                  {t("opReject")}
                </button>
              </>
            ) : action.status === 'queued' || action.status === 'executing' || action.status === 'verifying' ? (
              <div className="flex-1 text-center py-2 text-sm font-medium text-amber-400 bg-amber-950/20 rounded-lg border border-amber-900/30">
                {t("opExecuting")}
              </div>
            ) : action.status === 'succeeded' ? (
              <div className="flex-1 text-center py-2 text-sm font-medium text-emerald-400 bg-emerald-950/20 rounded-lg border border-emerald-900/30">
                {t("opVerified")}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}