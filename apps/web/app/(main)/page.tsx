"use client";

import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import { useAuth } from "@/components/auth-provider";
import { useEffect, useState } from "react";
import { apiFetch, type Stats } from "@/lib/api";

export default function DashboardPage() {
  const { t } = useLocale();
  const { user, loading: authLoading } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch<Stats>("/api/v1/stats")
      .then((data) => setStats(data))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey="dashboard" />
      <main className="flex-1 p-6">
        {!authLoading && user && (
          <div className="mb-4 rounded-lg border border-emerald-800/40 bg-emerald-900/10 px-4 py-2 text-sm text-emerald-300">
            {t("signedInAs")} <span className="font-medium">{user.email}</span>{" "}
            · {user.current_tenant?.name}
          </div>
        )}
        {error && (
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            <span>{t("errorLoading")}</span>
            <button
              onClick={load}
              className="ml-auto rounded border border-rose-500/40 px-2 py-0.5 text-xs hover:bg-rose-500/20"
            >
              {t("retry")}
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {cardConfig.map((card) => (
            <div
              key={card.key}
              className="rounded-lg border border-slate-800 bg-slate-900/60 p-5"
            >
              <div className="text-sm text-slate-400">{t(card.key)}</div>
              {loading ? (
                <div className="mt-2 h-9 w-16 animate-pulse rounded bg-slate-800" />
              ) : (
                <div className={`mt-2 text-3xl font-bold ${card.accent}`}>
                  {stats?.[card.stat] ?? "—"}
                </div>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

const cardConfig = [
  { key: "activeWorkflows", stat: "active_workflows" as keyof Stats, accent: "text-emerald-400" },
  { key: "successfulExecutions", stat: "successful_executions" as keyof Stats, accent: "text-sky-400" },
  { key: "failedExecutions", stat: "failed_executions" as keyof Stats, accent: "text-rose-400" },
  { key: "connectedSystems", stat: "connected_systems" as keyof Stats, accent: "text-amber-400" },
];
