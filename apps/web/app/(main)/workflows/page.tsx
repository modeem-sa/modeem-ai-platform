"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/header";
import { DataTable, type Column } from "@/components/data-table";
import { apiFetch, type WorkflowItem, type ListResponse } from "@/lib/api";

const columns: Column<WorkflowItem>[] = [
  { key: "name", labelKey: "name" },
  {
    key: "description",
    labelKey: "description",
    render: (row) => (
      <span className="text-slate-400">{row.description ?? "—"}</span>
    ),
  },
  {
    key: "is_active",
    labelKey: "status",
    render: (row) => (
      <span
        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
          row.is_active
            ? "bg-emerald-500/15 text-emerald-300"
            : "bg-slate-700/60 text-slate-400"
        }`}
      >
        {row.is_active ? "active" : "inactive"}
      </span>
    ),
  },
  {
    key: "created_at",
    labelKey: "createdAt",
    render: (row) => new Date(row.created_at).toLocaleString(),
  },
];

export default function WorkflowsPage() {
  const [data, setData] = useState<ListResponse<WorkflowItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch<ListResponse<WorkflowItem>>("/api/v1/workflows?limit=50&offset=0")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey="workflows" />
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
