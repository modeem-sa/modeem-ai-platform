"use client";

import { useState, type FormEvent } from "react";
import { useLocale } from "@/components/locale-provider";
import { useRequestWorkbench } from "@/hooks/use-service-requests";
import type { FinanceResult, FinanceToolCall, FinanceToolKey, RequestAnalysis, WorkbenchAction } from "@/lib/service-requests";

const labels: Record<FinanceToolKey, { en: string; ar: string; short: string }> = {
  "finance.get_overdue_customer_invoices": { en: "Overdue receivables", ar: "الذمم المتأخرة", short: "overdue" },
  "finance.get_customer_invoices": { en: "Customer invoices", ar: "فواتير العملاء", short: "invoices" },
  "finance.get_receivables_summary": { en: "Receivables summary", ar: "ملخص الذمم", short: "receivables" },
  "finance.get_vendor_bills": { en: "Vendor bills", ar: "فواتير الموردين", short: "bills" },
  "finance.get_recent_payments": { en: "Recent payments", ar: "الدفعات الأخيرة", short: "payments" },
};

function AnalysisList({ title, items }: { title: string; items: string[] }) {
  return items.length ? <div><h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{title}</h4><ul className="mt-1 list-disc space-y-1 ps-4 text-xs text-slate-300">{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div> : null;
}

function AnalysisCard({ analysis, ar }: { analysis: RequestAnalysis; ar: boolean }) {
  return <div className="mt-4 space-y-3 rounded-lg border border-slate-700/80 bg-slate-950/70 p-3">
    <div><h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{ar ? "ملخص الطلب" : "Request summary"}</h4><p className="mt-1 text-sm text-slate-200">{analysis.request_summary}</p></div>
    <div><h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{ar ? "هدف العميل" : "Customer goal"}</h4><p className="mt-1 text-sm text-slate-300">{analysis.customer_goal}</p></div>
    <div className="grid gap-3 sm:grid-cols-2"><AnalysisList title={ar ? "المعلومات المطلوبة" : "Required information"} items={analysis.required_information} /><AnalysisList title={ar ? "المعلومات الناقصة" : "Missing information"} items={analysis.missing_information} /><AnalysisList title={ar ? "الخطوات المقترحة" : "Suggested steps"} items={analysis.suggested_steps} /><AnalysisList title={ar ? "المخاطر المحتملة" : "Potential risks"} items={analysis.potential_risks} /></div>
    <p className="text-xs text-amber-300">{analysis.approval_likely_required ? (ar ? "قد تتطلب الخطوة موافقة." : "Approval may be required.") : (ar ? "لا تبدو موافقة مطلوبة في مرحلة التحليل." : "No approval appears necessary at analysis stage.")}</p>
  </div>;
}

function valueOf(row: Record<string, unknown>, keys: string[]) {
  const value = keys.map((key) => row[key]).find((candidate) => candidate !== undefined && candidate !== null);
  return value === undefined ? "—" : String(value);
}

function DetailTable({ result, tool, ar }: { result: FinanceResult; tool: FinanceToolKey; ar: boolean }) {
  const records = result.invoices ?? result.bills ?? result.payments ?? [];
  if (!records.length) return <p className="p-3 text-xs text-slate-500">{ar ? "لا توجد صفوف تفصيلية في هذه الاستجابة؛ تم الاحتفاظ بالملخص." : "No detail rows were returned; the safe summary is retained."}</p>;
  const columns = tool.includes("payments")
    ? [{ label: ar ? "الطرف" : "Partner", keys: ["customer", "vendor", "partner"] }, { label: ar ? "المرجع" : "Reference", keys: ["payment_number", "reference", "name"] }, { label: ar ? "التاريخ" : "Date", keys: ["payment_date", "date"] }, { label: ar ? "المبلغ" : "Amount", keys: ["amount", "payment_amount", "total_amount"] }]
    : tool.includes("bills")
      ? [{ label: ar ? "المورد" : "Vendor", keys: ["vendor", "supplier", "partner"] }, { label: ar ? "الفاتورة" : "Bill", keys: ["bill_number", "invoice_number", "name"] }, { label: ar ? "الاستحقاق" : "Due", keys: ["due_date"] }, { label: ar ? "المتبقي" : "Remaining", keys: ["remaining_amount", "amount_total", "total_amount"] }]
      : [{ label: ar ? "العميل" : "Customer", keys: ["customer", "partner"] }, { label: ar ? "الفاتورة" : "Invoice", keys: ["invoice_number", "name"] }, { label: ar ? "الاستحقاق" : "Due", keys: ["due_date"] }, { label: ar ? "التأخير" : "Days", keys: ["days_overdue"] }, { label: ar ? "المتبقي" : "Remaining", keys: ["remaining_amount", "amount_residual", "total_amount"] }];
  return <div className="max-h-72 overflow-auto"><table className="w-full min-w-[610px] text-start text-xs"><thead className="sticky top-0 bg-slate-950 text-[10px] uppercase tracking-wider text-slate-500"><tr>{columns.map((column) => <th key={column.label} className="p-2 font-medium">{column.label}</th>)}</tr></thead><tbody>{records.map((row, index) => <tr key={`${valueOf(row, ["id", "name"])}-${index}`} className="border-t border-slate-800/80 text-slate-300 transition-colors hover:bg-cyan-950/20">{columns.map((column) => <td key={column.label} className="p-2">{valueOf(row, column.keys)}</td>)}</tr>)}</tbody></table></div>;
}

function CurrencyCards({ totals, ar }: { totals: NonNullable<FinanceResult["totals_by_currency"]>; ar: boolean }) {
  return <div className="grid gap-2 sm:grid-cols-2">{totals.map((item, index) => <div key={`${item.currency}-${index}`} className="rounded border border-slate-800 bg-slate-950/60 p-2.5 transition-colors hover:border-cyan-900">
    <div className="flex items-baseline justify-between gap-2"><p className="text-xs font-semibold text-slate-300">{item.currency}</p><span className="text-[10px] text-slate-500">{item.invoice_count ?? item.bill_count ?? item.payment_count ?? 0} {ar ? "سجل" : "records"}</span></div>
    <p className="mt-1 font-mono text-base font-semibold text-cyan-200">{item.open_receivables_total ?? item.outstanding_amount ?? item.total_amount ?? item.amount ?? "—"}</p>
    {item.overdue_receivables_total !== undefined && <p className="text-[10px] text-amber-300">{ar ? "المتأخر" : "Overdue"}: {item.overdue_receivables_total}</p>}
    {item.aging && <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-800 pt-2 text-[10px] text-slate-500">{Object.entries(item.aging).map(([key, value]) => <span key={key} className="flex justify-between gap-2"><span>{key.replaceAll("_", " ")}</span><b className="font-mono font-normal text-slate-300">{value}</b></span>)}</div>}
  </div>)}</div>;
}

function FinanceToolResult({ call, ar, onPrepare, preparing }: { call: FinanceToolCall; ar: boolean; onPrepare: (id: string) => void; preparing: boolean }) {
  const result = call.result;
  const [expanded, setExpanded] = useState(false);
  const tool = labels[call.tool_key];
  return <article className="rounded-lg border border-emerald-900/60 bg-emerald-950/15 p-3 transition-colors hover:border-emerald-700/70">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="text-xs font-semibold text-emerald-300">{ar ? tool.ar : tool.en}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{call.tool_key} · {ar ? "قراءة فقط" : "read only"}</p></div>
      <span data-testid={`status-tool-${call.id}`} className={`rounded-full px-2 py-1 text-[10px] ${call.status === "completed" ? "bg-emerald-950 text-emerald-300" : call.status === "failed" ? "bg-rose-950 text-rose-300" : "bg-slate-800 text-slate-300"}`}>{call.status}</span>
    </div>
    {result && <div className="mt-3 space-y-3">
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 border-y border-slate-800/80 py-2 text-xs sm:grid-cols-4">
        <div><span className="block text-[10px] uppercase text-slate-500">{ar ? "المصدر" : "Source"}</span><span className="text-slate-200">{result.source}</span></div>
        <div><span className="block text-[10px] uppercase text-slate-500">{ar ? "الاتصال" : "Connection"}</span><span className="text-slate-200">{result.connection_name}</span></div>
        <div><span className="block text-[10px] uppercase text-slate-500">{ar ? "كما في" : "As of"}</span><span className="text-slate-200">{result.as_of}</span></div>
        <div><span className="block text-[10px] uppercase text-slate-500">{ar ? "السجلات" : "Records"}</span><span className="text-slate-200">{result.returned_count ?? "—"}{result.returned_customer_count !== undefined ? ` · ${result.returned_customer_count} ${ar ? "عميل" : "customers"}` : ""}</span></div>
      </div>
       {result.filters_used?.length ? <div className="flex flex-wrap items-center gap-1.5 text-[10px]"><span className="text-slate-500">{ar ? "الفلاتر" : "Filters"}:</span>{result.filters_used.map((filter, index) => <span key={`${filter.field}-${index}`} className="rounded border border-slate-700 bg-slate-900/70 px-1.5 py-0.5 font-mono text-slate-300">{filter.field}{filter.operator}{filter.value === undefined ? "" : String(filter.value)}</span>)}</div> : null}
      {(result.result_truncated || result.needs_narrower_filter || result.complete === false) && <p className="rounded border border-amber-800/60 bg-amber-950/20 p-2 text-xs text-amber-300">{ar ? "النتيجة غير مكتملة. ضيّق الفلتر قبل الاعتماد على الإجماليات." : "Result is incomplete. Narrow the filter before relying on totals."}</p>}
      {result.totals_by_currency?.length ? <CurrencyCards totals={result.totals_by_currency} ar={ar} /> : null}
       {call.tool_key === "finance.get_overdue_customer_invoices" && call.status === "completed" && result && !result.result_truncated && <button type="button" onClick={() => onPrepare(call.id)} disabled={preparing} className="w-full rounded border border-amber-700/80 bg-amber-950/30 px-2.5 py-2 text-start text-xs font-semibold text-amber-200 transition-colors hover:bg-amber-950/60 disabled:opacity-50">{preparing ? (ar ? "جارٍ تجهيز المقترح…" : "Preparing proposal…") : (ar ? "تجهيز متابعة للمراجعة" : "Prepare Follow-up")}</button>}
       <button type="button" data-testid={`button-toggle-detail-${call.id}`} onClick={() => setExpanded((value) => !value)} className="flex w-full items-center justify-between rounded border border-slate-800 bg-slate-950/50 px-2.5 py-2 text-start text-xs text-cyan-300 transition-colors hover:border-cyan-800 hover:bg-cyan-950/20"><span>{expanded ? (ar ? "إخفاء التفاصيل" : "Hide detail rows") : (ar ? "عرض صفوف التفاصيل" : "Expand detail rows")}</span><span className="font-mono text-slate-500">{expanded ? "−" : "+"}</span></button>
      {expanded && <div className="rounded border border-slate-800 bg-slate-950/50"><DetailTable result={result} tool={call.tool_key} ar={ar} /></div>}
    </div>}
    {call.error_code && <p className="mt-2 text-xs text-rose-300">{ar ? "فشل تنفيذ أداة القراءة بأمان." : "The read tool failed safely."}</p>}
  </article>;
}

function ActionCard({ action, ar, busy, onEdit, onSubmit, onApprove, onReject }: {
  action: WorkbenchAction; ar: boolean; busy: boolean;
  onEdit: (action: WorkbenchAction) => void; onSubmit: (action: WorkbenchAction) => void;
  onApprove: (action: WorkbenchAction) => void; onReject: (action: WorkbenchAction) => void;
}) {
  const proposal = action.proposal;
  return <article className="overflow-hidden rounded-xl border border-amber-800/60 bg-[#151713] shadow-[0_12px_30px_rgba(12,20,12,.22)]">
    <div className="border-b border-amber-900/50 bg-amber-950/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[.18em] text-amber-400">{proposal.action_key}</p><h4 className="mt-1 text-base font-semibold text-stone-100">{ar ? "مقترح متابعة تحصيل" : "Collection follow-up proposal"}</h4></div>
        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${action.status === "approved" ? "border-emerald-700 bg-emerald-950/50 text-emerald-300" : action.status === "awaiting_approval" ? "border-sky-700 bg-sky-950/40 text-sky-300" : "border-amber-700 bg-amber-950/50 text-amber-200"}`}>{action.status.replace("_", " ")}</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div><span className="block text-[10px] uppercase text-stone-500">{ar ? "العملاء" : "Customers"}</span><b className="font-mono text-lg text-stone-100">{new Set(proposal.target_records.map((row) => row.customer_id)).size}</b></div>
        <div><span className="block text-[10px] uppercase text-stone-500">{ar ? "الفواتير" : "Invoices"}</span><b className="font-mono text-lg text-stone-100">{proposal.target_records.length}</b></div>
        <div className="col-span-2"><span className="block text-[10px] uppercase text-stone-500">{ar ? "المتبقي حسب العملة" : "Outstanding by currency"}</span><div className="mt-1 flex flex-wrap gap-2">{proposal.totals_by_currency.map((total, index) => <b key={`${total.currency}-${index}`} className="rounded border border-amber-900/70 bg-amber-950/30 px-2 py-1 font-mono text-sm text-amber-200">{total.outstanding_amount ?? total.open_receivables_total ?? total.total_amount ?? total.amount ?? "—"} {total.currency}</b>)}</div></div>
      </div>
    </div>
    <div className="space-y-4 p-4">
      <div className="grid gap-3 text-xs sm:grid-cols-2"><div><span className="text-stone-500">{ar ? "المصدر المحدث / المطلوب" : "Refreshed source / requested"}</span><p className="mt-1 font-mono text-stone-300">{proposal.source_tool_call_id.slice(0, 12)} · {proposal.requested_source_tool_call_id.slice(0, 12)}</p><p className="mt-1 text-[10px] text-stone-500">{ar ? "لقطة المصدر" : "Snapshot"} <span className="font-mono text-stone-400">{proposal.source_snapshot_hash.slice(0, 12)}</span> · {proposal.source_as_of}</p></div><div><span className="text-stone-500">{ar ? "أُعد بواسطة / في" : "Prepared by / at"}</span><p className="mt-1 font-mono text-stone-300">{action.prepared_by_user_id.slice(0, 12)} · {action.prepared_at}</p></div></div>
      <div className="rounded-lg border border-stone-800 bg-stone-950/40 p-3"><span className="text-[10px] uppercase tracking-wider text-stone-500">{ar ? "الرسالة المقترحة" : "Draft message"} · {proposal.followup_type}</span><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-200">{proposal.draft_message}</p></div>
      {proposal.internal_note && <div className="rounded-lg border border-stone-800/80 bg-stone-900/40 p-3 text-xs text-stone-400"><span className="text-[10px] uppercase text-stone-500">{ar ? "ملاحظة داخلية" : "Internal note"}</span><p className="mt-1 whitespace-pre-wrap">{proposal.internal_note}</p></div>}
      {action.rejection_reason && <div className="mb-3 rounded border border-rose-800/70 bg-rose-950/25 p-2 text-xs text-rose-300"><span className="font-semibold">{ar ? "سبب الرفض" : "Rejection reason"}:</span> {action.rejection_reason}</div>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-stone-800 pt-3"><span className="font-mono text-[10px] text-stone-500">hash {action.proposal_hash_short} · v{action.version}</span>
        <div className="flex flex-wrap gap-2">{action.can_edit && <button type="button" onClick={() => onEdit(action)} disabled={busy} className="rounded border border-stone-600 px-3 py-1.5 text-xs text-stone-200 hover:border-amber-600">{ar ? "تعديل المسودة" : "Edit Draft"}</button>}{action.can_submit && <button type="button" onClick={() => onSubmit(action)} disabled={busy} className="rounded bg-amber-500 px-3 py-1.5 text-xs font-semibold text-stone-950 hover:bg-amber-400">{ar ? "إرسال للموافقة" : "Submit for approval"}</button>}{action.can_approve && <button type="button" onClick={() => onApprove(action)} disabled={busy} className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-stone-50 hover:bg-emerald-500">{ar ? "موافقة" : "Approve"}</button>}{action.can_reject && <button type="button" onClick={() => onReject(action)} disabled={busy} className="rounded border border-rose-700 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-950/40">{ar ? "رفض" : "Reject"}</button>}</div>
      </div>
      {action.status === "approved" && <div className="rounded-lg border border-emerald-800/70 bg-emerald-950/30 p-3 text-sm text-emerald-200"><b>Approved — not executed</b><span className="mx-2 text-emerald-700">/</span><b>تمت الموافقة — لم يتم التنفيذ بعد</b><p className="mt-2 text-xs text-amber-300">{ar ? "يجب إعادة التحقق من البيانات قبل أي تنفيذ لاحق." : "Re-verify the source evidence before any later execution."}</p></div>}
    </div>
  </article>;
}

export function RequestWorkbench({ requestId }: { requestId: string }) {
  const { locale } = useLocale();
  const ar = locale === "ar";
  const { workbench, loading, error, start, analyze, send, runOverdueInvoices, runFinanceTool, prepareAction, updateAction, submitAction, approveAction, rejectAction } = useRequestWorkbench(requestId, locale, true);
  const [instruction, setInstruction] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [preparingCall, setPreparingCall] = useState<string | null>(null);
  const [editingAction, setEditingAction] = useState<WorkbenchAction | null>(null);
  const [draftMessage, setDraftMessage] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [followupType, setFollowupType] = useState<WorkbenchAction["proposal"]["followup_type"]>("email");
  const session = workbench?.session;
  const perform = async (action: () => Promise<unknown>) => { setActionError(null); try { await action(); } catch (err) { setActionError(err instanceof Error ? err.message : (ar ? "تعذر الاتصال بالمساعد." : "The assistant request failed.")); } };
  const edit = (action: WorkbenchAction) => { setEditingAction(action); setDraftMessage(action.proposal.draft_message); setInternalNote(action.proposal.internal_note); setFollowupType(action.proposal.followup_type); };
  const prepare = async (id: string) => { setPreparingCall(id); await perform(() => prepareAction(id)); setPreparingCall(null); };
  const saveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingAction) return;
    await perform(() => updateAction(editingAction, { draft_message: draftMessage, internal_note: internalNote, followup_type: followupType }));
    setEditingAction(null);
  };
  const actions = workbench?.actions ?? [];
  const toolActions: Array<[FinanceToolKey, Record<string, unknown>]> = [
    ["finance.get_customer_invoices", { max_records: 100 }],
    ["finance.get_receivables_summary", {}],
    ["finance.get_vendor_bills", { max_records: 100 }],
    ["finance.get_recent_payments", { max_records: 100 }],
  ];
  return <section dir={ar ? "rtl" : "ltr"} className="rounded-xl border border-cyan-900/40 bg-cyan-950/10 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-cyan-300">{ar ? "مساعد تنفيذ الطلب" : "AI Workbench"}</h3><p className="mt-1 text-xs text-slate-400">{ar ? "أدلة مالية داخلية مرتبطة بهذا الطلب فقط." : "Request-bound financial evidence, kept inside this workspace."}</p></div>{session && <span className="rounded-full border border-slate-700 px-2 py-1 text-xs text-slate-400">{session.status}</span>}</div>
    {!session ? <div className="mt-4"><p className="text-sm text-slate-400">{ar ? "ابدأ جلسة داخلية لتحليل الطلب دون تنفيذ أي إجراء." : "Start an internal session to analyze the request without executing actions."}</p><button type="button" data-testid="button-start-workbench" disabled={loading} onClick={() => void perform(start)} className="mt-3 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:opacity-50">{ar ? "بدء العمل بالمساعد الذكي" : "Start AI Assistance"}</button></div> :
      <div className="mt-4 space-y-4">
        <div className="flex flex-wrap gap-2"><button type="button" data-testid="button-analyze-request" disabled={loading} onClick={() => void perform(analyze)} className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50">{loading ? (ar ? "جارٍ التنفيذ…" : "Running…") : (ar ? "تحليل الطلب" : "Analyze request")}</button><button type="button" data-testid="button-overdue-invoices" disabled={loading} onClick={() => void perform(() => runOverdueInvoices(30))} className="rounded-lg border border-emerald-700 px-3 py-2 text-sm text-emerald-300 transition-colors hover:bg-emerald-950/50 disabled:opacity-50">{ar ? "المتأخرة +30 يومًا" : "Overdue 30+ days"}</button>{toolActions.map(([key, input]) => <button key={key} type="button" data-testid={`button-tool-${labels[key].short}`} disabled={loading} onClick={() => void perform(() => runFinanceTool(key, input))} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 transition-colors hover:border-cyan-800 hover:bg-cyan-950/30 disabled:opacity-50">{ar ? labels[key].ar : labels[key].en}</button>)}</div>
        {session.analysis && <AnalysisCard analysis={session.analysis} ar={ar} />}
         {(workbench.tool_calls ?? []).length > 0 && <div className="space-y-2">{workbench.tool_calls.map((call) => <FinanceToolResult key={call.id} call={call} ar={ar} onPrepare={(id) => void prepare(id)} preparing={preparingCall === call.id || loading} />)}</div>}
         {actions.length > 0 && <div className="space-y-3 border-t border-cyan-900/40 pt-4"><div className="flex items-center justify-between"><div><p className="text-[10px] font-semibold uppercase tracking-[.18em] text-amber-400">{ar ? "مقترحات المراجعة" : "Review proposals"}</p><p className="mt-1 text-xs text-slate-500">{ar ? "مقترحات محكومة، لا تنفذ أي شيء." : "Controlled proposals. Nothing is executed from this surface."}</p></div><span className="font-mono text-xs text-slate-500">{actions.length.toString().padStart(2, "0")}</span></div>{actions.map((action) => <ActionCard key={action.id} action={action} ar={ar} busy={loading} onEdit={edit} onSubmit={(item) => void perform(() => submitAction(item))} onApprove={(item) => void perform(() => approveAction(item))} onReject={(item) => { const reason = window.prompt(ar ? "سبب الرفض" : "Rejection reason"); if (reason?.trim()) void perform(() => rejectAction(item, reason.trim())); }} />)}</div>}
         {editingAction && <form onSubmit={(event) => void saveEdit(event)} className="rounded-xl border border-cyan-700/70 bg-slate-950/80 p-4 shadow-xl"><div className="flex items-center justify-between gap-3"><div><h4 className="text-sm font-semibold text-cyan-200">{ar ? "تعديل المسودة" : "Edit Draft"}</h4><p className="mt-1 text-xs text-slate-500">{ar ? "يمكن تعديل الرسالة والملاحظة ونوع المتابعة فقط." : "Only the message, internal note, and follow-up type can be changed."}</p></div><button type="button" onClick={() => setEditingAction(null)} className="text-xs text-slate-500 hover:text-slate-200">{ar ? "إلغاء" : "Cancel"}</button></div><div className="mt-3 grid gap-3"><label className="text-xs text-slate-400">{ar ? "نوع المتابعة" : "Follow-up type"}<select value={followupType} onChange={(event) => setFollowupType(event.target.value as WorkbenchAction["proposal"]["followup_type"])} className="mt-1 block w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-200"><option value="email">Email</option><option value="phone">Phone</option><option value="message">Message</option><option value="review">Review</option></select></label><label className="text-xs text-slate-400">{ar ? "الرسالة" : "Draft message"}<textarea required maxLength={2000} value={draftMessage} onChange={(event) => setDraftMessage(event.target.value)} className="mt-1 block min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-200" /></label><label className="text-xs text-slate-400">{ar ? "ملاحظة داخلية" : "Internal note"}<textarea maxLength={2000} value={internalNote} onChange={(event) => setInternalNote(event.target.value)} className="mt-1 block min-h-16 w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-200" /></label></div><button type="submit" disabled={loading || !draftMessage.trim()} className="mt-3 rounded bg-cyan-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">{ar ? "حفظ التعديلات" : "Save changes"}</button></form>}
        {workbench.messages.length > 0 && <div className="max-h-56 space-y-2 overflow-auto border-t border-slate-800 pt-3">{workbench.messages.map((message) => <div key={message.id} data-testid={`message-${message.id}`} className={`rounded-lg p-3 text-sm ${message.role === "user" ? "bg-slate-800 text-slate-200" : "bg-cyan-950/40 text-cyan-100"}`}><span className="mb-1 block text-[10px] uppercase text-slate-500">{message.role}</span>{message.content}</div>)}</div>}
        <form onSubmit={(event) => { event.preventDefault(); if (instruction.trim()) { const value = instruction.trim(); setInstruction(""); void perform(() => send(value)); } }} className="flex gap-2 border-t border-slate-800 pt-3"><input data-testid="input-workbench-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} maxLength={4000} placeholder={ar ? "اكتب توجيهًا داخليًا للمساعد…" : "Ask about this request or its finance evidence…"} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-200 outline-none transition-colors focus:border-cyan-700" /><button type="submit" data-testid="button-send-instruction" disabled={loading || !instruction.trim()} className="rounded-lg border border-cyan-700 px-3 text-sm text-cyan-300 transition-colors hover:bg-cyan-950/40 disabled:opacity-50">{ar ? "إرسال" : "Send"}</button></form>
      </div>}
    {(error || actionError || session?.last_error) && <p role="alert" data-testid="status-workbench-error" className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 p-3 text-sm text-rose-300">{actionError || session?.last_error || error?.message}</p>}
  </section>;
}