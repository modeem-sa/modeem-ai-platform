"use client";

import type {
  FinancialConnection,
  FinancialReadPage,
  FinancialRecord,
  FinancialResource,
} from "@/lib/operations";

type Association = { id: string; name: string; role: string };

type Props = {
  locale: "ar" | "en";
  associations: Association[];
  connections: FinancialConnection[];
  associationId: string;
  connectionId: string;
  resource: Exclude<FinancialResource, "journal_items">;
  page: FinancialReadPage | null;
  lines: FinancialRecord[];
  selectedEntry: FinancialRecord | null;
  search: string;
  status: string;
  dateFrom: string;
  dateTo: string;
  loading: boolean;
  linesLoading: boolean;
  error: string | null;
  onAssociationChange: (id: string) => void;
  onConnectionChange: (id: string) => void;
  onResourceChange: (resource: Exclude<FinancialResource, "journal_items">) => void;
  onSearchChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onSelectEntry: (record: FinancialRecord) => void;
  onPageChange: (offset: number) => void;
  onRefresh: () => void;
};

const copy = {
  ar: {
    title: "المراجعة المالية من Odoo",
    description: "ابحث في القيود والحركات وراجع تفاصيلها قبل أي إجراء لاحق.",
    association: "الجمعية",
    connection: "اتصال Odoo",
    entries: "القيود اليومية",
    payments: "الحركات المالية",
    search: "ابحث برقم القيد أو الحركة",
    all: "كل الحالات",
    posted: "مرحّل",
    draft: "مسودة",
    cancel: "ملغي",
    dateFrom: "من تاريخ",
    dateTo: "إلى تاريخ",
    source: "المصدر",
    readAt: "آخر قراءة",
    readOnly: "عرض للقراءة فقط — لا تعديل أو اعتماد أو دفع من هذه الصفحة",
    noConnection: "لا يوجد اتصال Odoo جاهز لهذه الجمعية.",
    noRecords: "لا توجد نتائج مطابقة.",
    chooseEntry: "اختر قيدًا لعرض سطوره المحاسبية.",
    details: "تفاصيل القيد",
    account: "الحساب",
    statement: "البيان",
    partner: "الجهة",
    debit: "مدين",
    credit: "دائن",
    balance: "الرصيد",
    date: "التاريخ",
    journal: "اليومية",
    reference: "المرجع",
    amount: "المبلغ",
    status: "الحالة",
    type: "النوع",
    retry: "إعادة المحاولة",
    previous: "السابق",
    next: "التالي",
    loading: "جارٍ القراءة من Odoo…",
  },
  en: {
    title: "Odoo financial review",
    description: "Search journal entries and transactions, then review details before any later action.",
    association: "Association",
    connection: "Odoo connection",
    entries: "Journal entries",
    payments: "Financial transactions",
    search: "Search by entry or transaction number",
    all: "All statuses",
    posted: "Posted",
    draft: "Draft",
    cancel: "Cancelled",
    dateFrom: "From date",
    dateTo: "To date",
    source: "Source",
    readAt: "Last read",
    readOnly: "Read-only view — no editing, approval, or payment on this page",
    noConnection: "No ready Odoo connection exists for this association.",
    noRecords: "No matching records.",
    chooseEntry: "Select an entry to review its ledger lines.",
    details: "Entry details",
    account: "Account",
    statement: "Label",
    partner: "Partner",
    debit: "Debit",
    credit: "Credit",
    balance: "Balance",
    date: "Date",
    journal: "Journal",
    reference: "Reference",
    amount: "Amount",
    status: "Status",
    type: "Type",
    retry: "Retry",
    previous: "Previous",
    next: "Next",
    loading: "Reading from Odoo…",
  },
};

function relationName(value: FinancialRecord["partner_id"]): string {
  return value?.[1] ?? "—";
}

function money(value: number | undefined, locale: "ar" | "en"): string {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value ?? 0);
}

export function FinancialReview(props: Props) {
  const t = copy[props.locale];
  const records = props.page?.records ?? [];
  const readyConnections = props.connections.filter(
    (item) =>
      item.is_active &&
      item.odoo_company_id !== null &&
      item.last_test_status === "success" &&
      (item.selected_transport === "xmlrpc" || item.selected_transport === "json2"),
  );

  return (
    <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50 shadow-xl">
      <div className="border-b border-slate-800 bg-slate-900 p-4 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-white">{t.title}</h2>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                Odoo
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-400">{t.description}</p>
            <p className="mt-2 text-xs text-amber-300/90">{t.readOnly}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-slate-400">
              {t.association}
              <select
                aria-label={t.association}
                value={props.associationId}
                onChange={(event) => props.onAssociationChange(event.target.value)}
                className="mt-1 block h-9 min-w-48 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200"
              >
                {props.associations.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-400">
              {t.connection}
              <select
                aria-label={t.connection}
                value={props.connectionId}
                onChange={(event) => props.onConnectionChange(event.target.value)}
                className="mt-1 block h-9 min-w-48 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200"
              >
                <option value="">{t.connection}</option>
                {readyConnections.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </div>

      <div className="border-b border-slate-800 p-3 sm:p-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex rounded-lg border border-slate-700 bg-slate-950 p-1">
            {(["journal_entries", "payments_summary"] as const).map((resource) => (
              <button
                key={resource}
                onClick={() => props.onResourceChange(resource)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  props.resource === resource
                    ? "bg-emerald-500 text-slate-950"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {resource === "journal_entries" ? t.entries : t.payments}
              </button>
            ))}
          </div>
          <input
            aria-label={t.search}
            value={props.search}
            onChange={(event) => props.onSearchChange(event.target.value)}
            placeholder={t.search}
            className="h-9 min-w-56 flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200 placeholder:text-slate-600"
          />
          <select
            aria-label={t.status}
            value={props.status}
            onChange={(event) => props.onStatusChange(event.target.value)}
            className="h-9 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200"
          >
            <option value="">{t.all}</option>
            <option value="posted">{t.posted}</option>
            <option value="draft">{t.draft}</option>
            <option value="cancel">{t.cancel}</option>
          </select>
          <label className="text-[11px] text-slate-500">
            {t.dateFrom}
            <input type="date" value={props.dateFrom} onChange={(e) => props.onDateFromChange(e.target.value)} className="mt-1 block h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-xs text-slate-300" />
          </label>
          <label className="text-[11px] text-slate-500">
            {t.dateTo}
            <input type="date" value={props.dateTo} onChange={(e) => props.onDateToChange(e.target.value)} className="mt-1 block h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-xs text-slate-300" />
          </label>
        </div>
      </div>

      {props.page && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 border-b border-slate-800 bg-slate-950/50 px-4 py-2 text-xs text-slate-500">
          <span>{t.source}: <b className="font-medium text-slate-300">{props.page.source_name}</b></span>
          <span>{t.readAt}: <b className="font-medium text-slate-300">{new Date(props.page.read_at).toLocaleString(props.locale === "ar" ? "ar-SA" : "en-US")}</b></span>
          <span className="font-mono">{props.page.transport}</span>
        </div>
      )}

      {props.error ? (
        <div className="p-8 text-center">
          <p className="text-sm text-rose-300">{props.error}</p>
          <button onClick={props.onRefresh} className="mt-3 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">{t.retry}</button>
        </div>
      ) : !props.connectionId ? (
        <div className="p-10 text-center text-sm text-slate-500">{t.noConnection}</div>
      ) : props.loading ? (
        <div className="p-10 text-center text-sm text-slate-400">{t.loading}</div>
      ) : records.length === 0 ? (
        <div className="p-10 text-center text-sm text-slate-500">{t.noRecords}</div>
      ) : (
        <div className={`grid min-h-[390px] ${props.resource === "journal_entries" ? "lg:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]" : ""}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-950 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-start font-medium">{t.reference}</th>
                  <th className="px-4 py-3 text-start font-medium">{t.date}</th>
                  <th className="px-4 py-3 text-start font-medium">{props.resource === "journal_entries" ? t.journal : t.partner}</th>
                  <th className="px-4 py-3 text-start font-medium">{t.status}</th>
                  <th className="px-4 py-3 text-end font-medium">{t.amount}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {records.map((record) => (
                  <tr
                    key={record.id}
                    onClick={() => props.resource === "journal_entries" && props.onSelectEntry(record)}
                    className={`transition hover:bg-slate-800/50 ${props.resource === "journal_entries" ? "cursor-pointer" : ""} ${props.selectedEntry?.id === record.id ? "bg-emerald-500/5" : ""}`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-200">{record.name || `#${record.id}`}</div>
                      <div className="max-w-52 truncate text-xs text-slate-500">{record.ref || "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-400" dir="ltr">{record.date || "—"}</td>
                    <td className="px-4 py-3 text-slate-300">{relationName(props.resource === "journal_entries" ? record.journal_id : record.partner_id)}</td>
                    <td className="px-4 py-3 text-slate-400">{record.state || record.parent_state || "—"}</td>
                    <td className="px-4 py-3 text-end font-mono text-slate-200" dir="ltr">
                      {money(record.amount_total_signed ?? record.amount, props.locale)} {relationName(record.currency_id) !== "—" ? relationName(record.currency_id) : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {props.resource === "journal_entries" && (
            <aside className="border-t border-slate-800 bg-slate-950/30 lg:border-s lg:border-t-0">
              {!props.selectedEntry ? (
                <div className="flex h-full min-h-64 items-center justify-center p-8 text-center text-sm text-slate-500">{t.chooseEntry}</div>
              ) : (
                <div>
                  <div className="border-b border-slate-800 p-4">
                    <div className="text-xs text-slate-500">{t.details}</div>
                    <div className="mt-1 font-semibold text-slate-100">{props.selectedEntry.name}</div>
                    <div className="mt-1 text-xs text-slate-400">{props.selectedEntry.ref || "—"}</div>
                  </div>
                  {props.linesLoading ? (
                    <div className="p-8 text-center text-sm text-slate-500">{t.loading}</div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="text-slate-500">
                          <tr>
                            <th className="px-3 py-2 text-start">{t.account}</th>
                            <th className="px-3 py-2 text-start">{t.statement}</th>
                            <th className="px-3 py-2 text-end">{t.debit}</th>
                            <th className="px-3 py-2 text-end">{t.credit}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800">
                          {props.lines.map((line) => (
                            <tr key={line.id}>
                              <td className="px-3 py-2 text-slate-300">{relationName(line.account_id)}</td>
                              <td className="max-w-40 truncate px-3 py-2 text-slate-400">{line.name || "—"}</td>
                              <td className="px-3 py-2 text-end font-mono text-slate-300">{money(line.debit, props.locale)}</td>
                              <td className="px-3 py-2 text-end font-mono text-slate-300">{money(line.credit, props.locale)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </aside>
          )}
        </div>
      )}

      {props.page && (
        <div className="flex items-center justify-between border-t border-slate-800 bg-slate-900 px-4 py-3">
          <button disabled={props.loading || props.page.offset === 0} onClick={() => props.onPageChange(Math.max(0, props.page!.offset - props.page!.limit))} className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 disabled:opacity-40">{t.previous}</button>
          <span className="text-xs text-slate-500">{props.page.offset + 1}–{props.page.offset + props.page.returned_count}</span>
          <button disabled={props.loading || !props.page.has_more} onClick={() => props.onPageChange(props.page!.next_offset ?? props.page!.offset + props.page!.limit)} className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 disabled:opacity-40">{t.next}</button>
        </div>
      )}
    </section>
  );
}