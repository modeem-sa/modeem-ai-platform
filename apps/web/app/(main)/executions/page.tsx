"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/header";
import { DataTable, type Column } from "@/components/data-table";
import { apiFetch, type ExecutionItem, type ListResponse } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  success: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-rose-500/15 text-rose-300",
  running: "bg-sky-500/15 text-sky-300",
};

const columns: Column<ExecutionItem>[] = [
  {
    key: "status",
    labelKey: "status",
    render: (row) => (
      <span
        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
          STATUS_STYLES[row.status] ?? "bg-slate-700/60 text-slate-400"
        }`}
      >
        {row.status}
      </span>
    ),
  },
  {
    key: "workflow_id",
    labelKey: "workflowId",
    render: (row) => (
      <span className="font-mono text-xs text-slate-400">
        {row.workflow_id ? row.workflow_id.slice(0, 8) + "…" : "—"}
      </span>
    ),
  },
  {
    key: "started_at",
    labelKey: "startedAt",
    render: (row) => new Date(row.started_at).toLocaleString(),
  },
  {
    key: "finished_at",
    labelKey: "finishedAt",
    render: (row) =>
      row.finished_at ? new Date(row.finished_at).toLocaleString() : "—",
  },
];

export default function ExecutionsPage() {
  const [data, setData] = useState<ListResponse<ExecutionItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch<ListResponse<ExecutionItem>>("/api/v1/executions?limit=50&offset=0")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey="executions" />
      <main className="flex-1 p-6">
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(r) => r.id}
          loading={loading}
          error={error}
          onRetry={load}
          total={data?.total ?? 0}
        />
      </main>
    </div>
  );
}
