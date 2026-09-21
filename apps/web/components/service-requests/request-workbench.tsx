"use client";

import { useState } from "react";
import { useLocale } from "@/components/locale-provider";
import { useRequestWorkbench } from "@/hooks/use-service-requests";
import type { RequestAnalysis } from "@/lib/service-requests";

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

export function RequestWorkbench({ requestId }: { requestId: string }) {
  const { locale } = useLocale();
  const ar = locale === "ar";
  const { workbench, loading, error, start, analyze, send } = useRequestWorkbench(requestId, locale, true);
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
        <div className="flex flex-wrap gap-2">{session.status === "failed" && <button type="button" disabled={loading} onClick={() => void perform(start)} className="rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-300 disabled:opacity-50">{ar ? "استئناف المساعد الذكي" : "Resume AI Assistance"}</button>}<button type="button" disabled={loading} onClick={() => void perform(analyze)} className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50">{loading ? (ar ? "جارٍ التحليل…" : "Analyzing…") : (ar ? "تحليل الطلب" : "Analyze Request")}</button></div>
        {session.analysis && <AnalysisCard analysis={session.analysis} ar={ar} />}
        {workbench.messages.length > 0 && <div className="max-h-56 space-y-2 overflow-auto border-t border-slate-800 pt-3">{workbench.messages.map((message) => <div key={message.id} className={`rounded-lg p-3 text-sm ${message.role === "user" ? "bg-slate-800 text-slate-200" : "bg-cyan-950/40 text-cyan-100"}`}><span className="mb-1 block text-[10px] uppercase text-slate-500">{message.role}</span>{message.content}</div>)}</div>}
        <form onSubmit={(event) => { event.preventDefault(); if (instruction.trim()) { const value = instruction.trim(); setInstruction(""); void perform(() => send(value)); } }} className="flex gap-2 border-t border-slate-800 pt-3"><input value={instruction} onChange={(event) => setInstruction(event.target.value)} maxLength={4000} placeholder={ar ? "اكتب توجيهًا داخليًا للمساعد…" : "Write an internal instruction…"} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-200" /><button type="submit" disabled={loading || !instruction.trim()} className="rounded-lg border border-cyan-700 px-3 text-sm text-cyan-300 disabled:opacity-50">{ar ? "إرسال" : "Send"}</button></form>
      </div>}
    {(error || actionError || session?.last_error) && <p role="alert" className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 p-3 text-sm text-rose-300">{actionError || session?.last_error || error?.message}</p>}
  </section>;
}