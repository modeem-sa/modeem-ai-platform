import { useState } from "react";
import { useLocale } from "@/components/locale-provider";
import {
  OperationTask,
  approveAction,
  approveCollectionMessage,
  generateAction,
  generateCollectionMessage,
  getCollectionDeliveryPresentation,
  rejectAction,
  rejectCollectionMessage,
  retryAction,
  retryCollectionMessage,
  submitAction,
  submitCollectionMessage,
} from "@/lib/operations";

export function OdooTaskCard({ task, onRefresh }: { task: OperationTask, onRefresh: () => void | Promise<void> }) {
  const { locale, t } = useLocale();
  const dateFmt = new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en", { dateStyle: "medium" });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const snapshot = (task.source_snapshot as Record<string, string | number | null | undefined>) || {};
  const amount = Number(snapshot.residual ?? snapshot.total ?? 0);
  const currency = String(snapshot.currency ?? "");
  
  const message = task.collection_message;
  const action = task.action;
  
  const handleGenerate = async () => {
    setLoading(true); setError(null);
    try {
      await generateCollectionMessage(task.id, task.version);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedGenerate"));
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!message) return;
    setLoading(true); setError(null);
    try {
      await submitCollectionMessage(task.id, task.version, message);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedSubmit"));
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!message) return;
    setLoading(true); setError(null);
    try {
      await approveCollectionMessage(task.id, task.version, message);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedApprove"));
    } finally {
      setLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!message) return;
    setLoading(true); setError(null);
    try {
      await retryCollectionMessage(task.id, task.version, message);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedRetry"));
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!message) return;
    setLoading(true); setError(null);
    try {
      await rejectCollectionMessage(task.id, task.version, message);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedReject"));
    } finally {
      setLoading(false);
    }
  };

  const handleActionGenerate = async () => {
    setLoading(true); setError(null);
    try {
      await generateAction(task.id, task.version);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opFailedGenerate"));
    } finally {
      setLoading(false);
    }
  };

  const handleActionTransition = async (
    transition: "submit" | "approve" | "reject" | "retry",
  ) => {
    if (!action) return;
    setLoading(true); setError(null);
    try {
      const args = [task.id, task.version, action.version, action.proposal_hash] as const;
      if (transition === "submit") await submitAction(...args);
      else if (transition === "approve") await approveAction(...args);
      else if (transition === "reject") await rejectAction(...args);
      else await retryAction(...args);
      await onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("connError"));
    } finally {
      setLoading(false);
    }
  };

  const delivery = message ? getCollectionDeliveryPresentation(message) : null;

  return (
    <div className="flex flex-col rounded-xl border border-sky-800/40 bg-slate-900/80 p-5 shadow-sm transition-shadow">
      {/* Header: Odoo Facts */}
      <div className="mb-4 border-b border-slate-800 pb-4">
        <div className="mb-3 text-[10px] font-bold uppercase tracking-widest text-sky-400">
          {t("opConfirmedOdooFacts")}
        </div>
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

      <div className="mb-4 rounded-xl border border-indigo-800/40 bg-indigo-950/20 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-bold text-indigo-300">{t("opAutomationWorkflow")}</h4>
            <p className="mt-1 text-xs text-slate-500">{t("opAutomationWorkflowDesc")}</p>
          </div>
          {action && (
            <span className="rounded-full bg-slate-800 px-2 py-1 text-[10px] font-semibold text-slate-300">
              {t(`opActionState_${action.status}`)}
            </span>
          )}
        </div>
        {action ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
              <div className="text-sm font-semibold text-slate-100">
                {String(action.proposal.title || t("opAiDraftProposal"))}
              </div>
              <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-indigo-400">
                {t("opAiGuidanceNotFact")}
              </div>
              {action.proposal.summary && (
                <p className="mt-2 text-xs leading-6 text-slate-300">
                  {String(action.proposal.summary)}
                </p>
              )}
              {action.proposal.priority_reason && (
                <p className="mt-2 text-xs text-amber-300">
                  {String(action.proposal.priority_reason)}
                </p>
              )}
              <div className="mt-2 text-[10px] text-slate-600" dir="ltr">
                SHA-256: {action.proposal_hash.slice(0, 12)}…
              </div>
            </div>
            {action.approved_hash && (
              <div className="rounded-lg border border-emerald-900/50 bg-emerald-950/20 p-3 text-xs">
                <div className="font-semibold text-emerald-300">{t("opExactApprovalEvidence")}</div>
                <div className="mt-2 grid gap-1 text-slate-400">
                  <span dir="ltr">SHA-256: {action.approved_hash.slice(0, 16)}…</span>
                  {action.approved_at && <span>{t("opApprovedAt")}: {new Date(action.approved_at).toLocaleString(locale === "ar" ? "ar" : "en")}</span>}
                  {action.approved_by_user_id && <span dir="ltr">{t("opApprovedBy")}: {action.approved_by_user_id}</span>}
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {action.status === "proposed" && (
                <>
                  <button onClick={() => void handleActionTransition("submit")} disabled={loading}
                    className="flex-1 rounded-lg bg-sky-600 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
                    {t("opSubmitApproval")}
                  </button>
                  <button onClick={() => void handleActionGenerate()} disabled={loading}
                    className="rounded-lg bg-slate-800 px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50">
                    {t("opRegenerate")}
                  </button>
                </>
              )}
              {action.status === "awaiting_approval" && (
                <>
                  <button onClick={() => void handleActionTransition("approve")} disabled={loading}
                    className="flex-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">
                    {t("opApproveAndExecute")}
                  </button>
                  <button onClick={() => void handleActionTransition("reject")} disabled={loading}
                    className="flex-1 rounded-lg bg-rose-900/50 px-3 py-2 text-xs font-semibold text-rose-300 hover:bg-rose-800 disabled:opacity-50">
                    {t("opReject")}
                  </button>
                </>
              )}
              {["queued", "executing", "verifying"].includes(action.status) && (
                <div className="flex-1 rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-2 text-center text-xs font-semibold text-amber-300">
                  {t("opExecuting")}
                </div>
              )}
              {action.status === "succeeded" && (
                <div className="flex-1 rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-3 py-2 text-xs font-semibold text-emerald-300">
                  {t("opVerifiedOdooReceipt")} · #{action.external_activity_id}
                </div>
              )}
              {action.status === "failed" && (
                <button onClick={() => void handleActionTransition("retry")} disabled={loading || action.approved_hash !== action.proposal_hash}
                  className="flex-1 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white hover:bg-amber-500 disabled:opacity-50">
                  {t("opRetryExact")}
                </button>
              )}
            </div>
          </div>
        ) : (
          <button onClick={() => void handleActionGenerate()} disabled={loading}
            className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            {loading ? t("opGenerating") : t("opGenerateAI")}
          </button>
        )}
      </div>

      {/* Arabic AI draft and the separately identified, hash-bound approved snapshot. */}
      {message && (
        <div className="mb-4 flex flex-col gap-3">
          <MessageCopy
            content={message.draft_content}
            label={t("opAiDraftProposal")}
            hash={message.draft_hash}
            version={message.draft_version}
            variant="draft"
          />
          {message.approved_content && message.approved_hash && (
            <MessageCopy
              content={message.approved_content}
              label={t("opApprovedImmutableCopy")}
              hash={message.approved_hash}
              version={message.approved_draft_version || message.draft_version}
              variant="approved"
            />
          )}
          {delivery && (
            <div className="rounded-lg border border-slate-700/70 bg-slate-950/50 p-3 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-300">{t("opDelivery")}</span>
                <span className={
                  delivery.tone === "success" ? "text-emerald-400"
                    : delivery.tone === "error" ? "text-rose-400"
                    : delivery.tone === "in_flight" ? "text-amber-400"
                    : "text-slate-500"
                }>
                  {t(delivery.labelKey)}
                </span>
              </div>
              {message.receipt_message_id !== null && (
                <div className="mt-2 break-all text-emerald-300" dir="ltr">
                  <span className="text-slate-500">{t("opDeliveryReceipt")}: </span>
                  {message.receipt_message_id}
                </div>
              )}
              {message.delivery_error && (
                <div className="mt-2 break-words text-rose-400">
                  <span className="text-slate-500">{t("opDeliveryError")}: </span>
                  {message.delivery_error}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg bg-rose-950/40 p-3 text-sm text-rose-300 border border-rose-900">
          {error}
        </div>
      )}

      {/* Execution Controls */}
      <div className="mt-auto pt-2">
        <div className="flex gap-2">
            {!message ? (
              <button onClick={handleGenerate} disabled={loading} className="flex-1 bg-indigo-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors">
                {loading ? t("opGenerating") : t("opGenerateCollectionMessage")}
              </button>
            ) : message.status === 'failed' ? (
              <button onClick={handleRetry} disabled={loading || message.attempt_count >= 3} className="flex-1 bg-amber-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-amber-500 disabled:opacity-50 transition-colors">
                {loading
                  ? t("opRetrying")
                  : message.attempt_count >= 3
                    ? t("opRetryLimitReached")
                    : t("opRetryApprovedMessage")}
              </button>
            ) : message.status === 'draft' ? (
              <>
                <button onClick={handleSubmit} disabled={loading} className="flex-1 bg-sky-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50 transition-colors">
                  {loading ? t("opSubmitting") : t("opSubmitApproval")}
                </button>
                <button onClick={handleGenerate} disabled={loading} className="px-3 bg-slate-800 text-slate-300 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors" title={t("opRegenerate")}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.59-9.21l5.67-5.67"/></svg>
                </button>
              </>
            ) : message.status === 'awaiting_approval' ? (
              <>
                <button onClick={handleApprove} disabled={loading} className="flex-1 bg-emerald-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50 transition-colors">
                  {loading ? t("opApproving") : t("opApproveHash")}
                </button>
                <button onClick={handleReject} disabled={loading} className="flex-1 bg-rose-900/50 text-rose-400 rounded-lg py-2 text-sm font-medium hover:bg-rose-800 hover:text-rose-200 disabled:opacity-50 transition-colors">
                  {t("opReject")}
                </button>
              </>
            ) : message.status === 'queued' || message.status === 'sending' || message.status === 'verifying' ? (
              <div className="flex-1 text-center py-2 text-sm font-medium text-amber-400 bg-amber-950/20 rounded-lg border border-amber-900/30">
                {t("opDeliveringMessage")}
              </div>
            ) : message.status === 'succeeded' ? (
              <div className="flex-1 text-center py-2 text-sm font-medium text-emerald-400 bg-emerald-950/20 rounded-lg border border-emerald-900/30">
                {t("opDeliveryVerified")}
              </div>
            ) : null}
        </div>
      </div>
    </div>
  );
}

function MessageCopy({
  content,
  label,
  hash,
  version,
  variant,
}: {
  content: string;
  label: string;
  hash: string;
  version: number;
  variant: "draft" | "approved";
}) {
  const approved = variant === "approved";
  return (
    <div className={`rounded-lg border p-4 ${
      approved
        ? "border-emerald-900/40 bg-emerald-950/20"
        : "border-indigo-900/30 bg-indigo-950/20"
    }`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className={`flex items-center gap-1.5 text-xs font-bold ${
          approved ? "text-emerald-400" : "text-indigo-400"
        }`}>
          {label}
        </span>
        <span className="text-[10px] text-slate-500" dir="ltr" title={hash}>
          v{version} · SHA-256: {hash.slice(0, 12)}…
        </span>
      </div>
      <p dir="rtl" lang="ar" className="whitespace-pre-wrap text-right text-sm leading-7 text-slate-200">
        {content}
      </p>
    </div>
  );
}