"use client";

import { useState } from "react";
import { useLocale } from "@/components/locale-provider";
import { useRequestWorkbench } from "@/hooks/use-service-requests";
import type { FinanceToolCall, RequestAnalysis } from "@/lib/service-requests";

function AnalysisList({ title, items }: { title: string; items: string[] }) {
  return items.length ? <div><h4 className="text-xs font-medium text-slate-400">{title}</h4><ul className="mt-1 list-disc space-y-1 ps-4 text-xs text-slate-300">{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div> : null;
}

function AnalysisCard({ analysis, ar }: { analysis: RequestAnalysis; ar: boolean }) {
  return <div className="mt-4 space-y-3 rounded-lg border border-slate-700 bg-slate-950/70 p-3">
    <div><h4 className="text-xs font-medium text-slate-400">{ar ? "ملخص الطلب" : "Request summary"}</h4><p className="mt-1 text-sm text-slate-200">{analysis.request_summary}</p></div>
    <div><h4 className="text-xs font-medium text-slate-400">{ar ? "هدف العميل" : "Customer goal"}</h4><p className="mt-1 text-sm text-slate-300">{analysis.customer_goal}</p></div>
    <div className="grid gap-3 sm:grid-cols-2">
      <AnalysisList title={ar ? "المعلومات المطلوبة" : "Required information"} items={analysis.required_information} />
      <AnalysisList title={ar ? "المعلومات الناقصة" : "Missing information"} items={analysis.missing_information} />
      <AnalysisList title={ar ? "الخطوات المقترحة" : "Suggested steps"} items={analysis.suggested_steps} />
      <AnalysisList title={ar ? "المخاطر المحتملة" : "Potential risks"} items={analysis.potential_risks} />
    </div>
    <p className="text-xs text-amber-300">{analysis.approval_likely_required ? (ar ? "قد تتطلب الخطوة موافقة." : "Approval may be required.") : (ar ? "لا تبدو موافقة مطلوبة في مرحلة التحليل." : "No approval appears necessary at analysis stage.")}</p>
  </div>;
}

function FinanceToolResult({ call, ar }: { call: FinanceToolCall; ar: boolean }) {
  const result = call.result;
  return <div className="rounded-lg border border-emerald-900/60 bg-emerald-950/15 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><p className="text-xs font-medium text-emerald-300">{ar ? "تحليل الفواتير المتأخرة" : "Overdue Customer Invoices"}</p><p className="font-mono text-[10px] text-slate-500">{call.tool_key} · {ar ? "قراءة فقط" : "read only"}</p></div>
      <span className={`rounded-full px-2 py-1 text-[10px] ${call.status === "completed" ? "bg-emerald-950 text-emerald-300" : call.status === "failed" ? "bg-rose-950 text-rose-300" : "bg-slate-800 text-slate-300"}`}>{call.status}</span>
    </div>
    {result && <div className="mt-3 space-y-3">
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><span className="block text-slate-500">{ar ? "المصدر" : "Source"}</span><span className="text-slate-200">{result.source}</span></div>
        <div><span className="block text-slate-500">{ar ? "الاتصال" : "Connection"}</span><span className="text-slate-200">{result.connection_name}</span></div>
        <div><span className="block text-slate-500">{ar ? "كما في" : "As of"}</span><span className="text-slate-200">{result.as_of}</span></div>
        <div><span className="block text-slate-500">{ar ? "عدد الفواتير" : "Invoices"}</span><span className="text-slate-200">{result.returned_count}</span></div>
      </div>
      {result.result_truncated && <p className="rounded border border-amber-800/60 bg-amber-950/20 p-2 text-xs text-amber-300">{ar ? "النتيجة غير مكتملة. ضيّق نطاق الطلب قبل الاعتماد على الإجماليات." : "Result incomplete. Narrow the request before relying on totals."}</p>}
      {result.totals_by_currency.length > 0 && <div className="grid gap-2 sm:grid-cols-2">{result.totals_by_currency.map((item) => <div key={item.currency_id} className="rounded border border-slate-800 bg-slate-950/60 p-2 text-xs"><p className="text-slate-400">{item.currency}</p><p className="mt-1 text-base font-semibold text-white">{item.outstanding_amount}</p><p className="text-slate-500">{item.invoice_count} {ar ? "فاتورة" : "invoices"}</p></div>)}</div>}
      <details className="rounded border border-slate-800 bg-slate-950/50 p-2">
        <summary className="cursor-pointer text-xs text-cyan-300">{ar ? "عرض البيانات المنظمة" : "View structured records"}</summary>
        <div className="mt-2 max-h-64 overflow-auto">
          {(result.invoices ?? []).length > 0 ? <table className="w-full min-w-[620px] text-start text-xs"><thead className="text-slate-500"><tr><th className="p-2">{ar ? "العميل" : "Customer"}</th><th className="p-2">{ar ? "الفاتورة" : "Invoice"}</th><th className="p-2">{ar ? "الاستحقاق" : "Due"}</th><th className="p-2">{ar ? "أيام التأخير" : "Days"}</th><th className="p-2">{ar ? "المتبقي" : "Remaining"}</th></tr></thead><tbody>{(result.invoices ?? []).map((invoice) => <tr key={invoice.id} className="border-t border-slate-800 text-slate-300"><td className="p-2">{invoice.customer}</td><td className="p-2 font-mono">{invoice.invoice_number}</td><td className="p-2">{invoice.due_date}</td><td className="p-2">{invoice.days_overdue}</td><td className="p-2">{invoice.remaining_amount} {invoice.currency}</td></tr>)}</tbody></table> : <p className="p-2 text-xs text-slate-500">{ar ? "تُعرض الصفوف التفصيلية عند التنفيذ فقط؛ يحتفظ النظام بالملخص الآمن." : "Detailed rows are shown only at execution time; the safe summary is retained."}</p>}
        </div>
      </details>
    </div>}
    {call.error_code && <p className="mt-2 text-xs text-rose-300">{ar ? "فشل تنفيذ أداة القراءة بأمان." : "The read tool failed safely."}</p>}
  </div>;
}

export function RequestWorkbench({ requestId }: { requestId: string }) {
  const { locale } = useLocale();
  const ar = locale === "ar";
  const { workbench, loading, error, start, analyze, send, runOverdueInvoices } = useRequestWorkbench(requestId, locale, true);
  const [instruction, setInstruction] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const session = workbench?.session;

  const perform = async (action: () => Promise<unknown>) => {
    setActionError(null);
    try { await action(); } catch (err) { setActionError(err instanceof Error ? err.message : (ar ? "تعذر الاتصال بالمساعد." : "The assistant request failed.")); }
  };

  return <section className="rounded-xl border border-cyan-900/40 bg-cyan-950/10 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="text-sm font-semibold text-cyan-300">{ar ? "مساعد تنفيذ الطلب" : "AI Workbench"}</h3><p className="mt-1 text-xs text-slate-400">{ar ? "مساحة داخلية مرتبطة بهذا الطلب فقط." : "Internal workspace bound to this request only."}</p></div>
      {session && <span className="rounded-full border border-slate-700 px-2 py-1 text-xs text-slate-400">{session.status}</span>}
    </div>
    {!session ? <div className="mt-4"><p className="text-sm text-slate-400">{ar ? "ابدأ جلسة داخلية لتحليل الطلب دون تنفيذ أي إجراء." : "Start an internal session to analyze the request without executing actions."}</p><button type="button" disabled={loading} onClick={() => void perform(start)} className="mt-3 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50">{ar ? "بدء العمل بالمساعد الذكي" : "Start AI Assistance"}</button></div> :
      <div className="mt-4 space-y-4">
        <div className="flex flex-wrap gap-2">{session.status === "failed" && <button type="button" disabled={loading} onClick={() => void perform(start)} className="rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-300 disabled:opacity-50">{ar ? "استئناف المساعد الذكي" : "Resume AI Assistance"}</button>}<button type="button" disabled={loading} onClick={() => void perform(analyze)} className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50">{loading ? (ar ? "جارٍ التحليل…" : "Analyzing…") : (ar ? "تحليل الطلب" : "Analyze Request")}</button><button type="button" disabled={loading} onClick={() => void perform(() => runOverdueInvoices(30))} className="rounded-lg border border-emerald-700 px-4 py-2 text-sm text-emerald-300 disabled:opacity-50">{loading ? (ar ? "جارٍ قراءة Odoo…" : "Reading Odoo…") : (ar ? "تحليل الفواتير المتأخرة +30 يومًا" : "Analyze invoices overdue 30+ days")}</button></div>
        {session.analysis && <AnalysisCard analysis={session.analysis} ar={ar} />}
        {(workbench.tool_calls ?? []).length > 0 && <div className="space-y-2">{workbench.tool_calls.map((call) => <FinanceToolResult key={call.id} call={call} ar={ar} />)}</div>}
        {workbench.messages.length > 0 && <div className="max-h-56 space-y-2 overflow-auto border-t border-slate-800 pt-3">{workbench.messages.map((message) => <div key={message.id} className={`rounded-lg p-3 text-sm ${message.role === "user" ? "bg-slate-800 text-slate-200" : "bg-cyan-950/40 text-cyan-100"}`}><span className="mb-1 block text-[10px] uppercase text-slate-500">{message.role}</span>{message.content}</div>)}</div>}
        <form onSubmit={(event) => { event.preventDefault(); if (instruction.trim()) { const value = instruction.trim(); setInstruction(""); void perform(() => send(value)); } }} className="flex gap-2 border-t border-slate-800 pt-3"><input value={instruction} onChange={(event) => setInstruction(event.target.value)} maxLength={4000} placeholder={ar ? "اكتب توجيهًا داخليًا للمساعد…" : "Write an internal instruction…"} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-200" /><button type="submit" disabled={loading || !instruction.trim()} className="rounded-lg border border-cyan-700 px-3 text-sm text-cyan-300 disabled:opacity-50">{ar ? "إرسال" : "Send"}</button></form>
      </div>}
    {(error || actionError || session?.last_error) && <p role="alert" className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 p-3 text-sm text-rose-300">{actionError || session?.last_error || error?.message}</p>}
  </section>;
}