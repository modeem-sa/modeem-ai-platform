"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/header";
import { DataTable, type Column } from "@/components/data-table";
import { apiFetch, type AuditLogItem, type ListResponse } from "@/lib/api";

const columns: Column<AuditLogItem>[] = [
  {
    key: "created_at",
    labelKey: "createdAt",
    render: (row) => new Date(row.created_at).toLocaleString(),
  },
  { key: "action", labelKey: "action" },
  {
    key: "actor_type",
    labelKey: "actor",
    render: (row) => (
      <span>
        {row.actor_type}
        {row.actor_id ? (
          <span className="ml-1 font-mono text-xs text-slate-500">
            ({row.actor_id})
          </span>
        ) : null}
      </span>
    ),
  },
  {
    key: "resource_type",
    labelKey: "resource",
    render: (row) => (
      <span>
        {row.resource_type}
        {row.resource_id ? (
          <span className="ml-1 font-mono text-xs text-slate-500">
            #{row.resource_id.slice(0, 8)}
          </span>
        ) : null}
      </span>
    ),
  },
];

export default function AuditLogsPage() {
  const [data, setData] = useState<ListResponse<AuditLogItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch<ListResponse<AuditLogItem>>("/api/v1/audit-logs?limit=50&offset=0")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey="auditLogs" />
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
