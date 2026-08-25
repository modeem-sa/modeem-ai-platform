"use client";

import { useLocale } from "@/components/locale-provider";

export interface Column<T> {
  key: string;
  labelKey: string;
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  total: number;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  total,
}: DataTableProps<T>) {
  const { t } = useLocale();

  if (error) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
        <span>{t("errorLoading")}</span>
        <button
          onClick={onRetry}
          className="ml-auto rounded border border-rose-500/40 px-2 py-0.5 text-xs hover:bg-rose-500/20"
        >
          {t("retry")}
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-10 animate-pulse rounded bg-slate-800/60" />
        ))}
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
        <p className="text-slate-400">{t("noRecords")}</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-sm text-slate-300">
        <thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {columns.map((col) => (
              <th key={col.key} className="px-4 py-3 text-start font-medium">
                {t(col.labelKey)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {rows.map((row) => (
            <tr key={rowKey(row)} className="hover:bg-slate-800/30 transition-colors">
              {columns.map((col) => (
                <td key={col.key} className="px-4 py-3 align-top">
                  {col.render
                    ? col.render(row)
                    : String((row as Record<string, unknown>)[col.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-slate-800 px-4 py-2 text-xs text-slate-500">
        {total} {total === 1 ? "record" : "records"}
      </div>
    </div>
  );
}
