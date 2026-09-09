"use client";

import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";
import { useServiceRequests } from "@/hooks/use-service-requests";
import { ServiceRequestList } from "@/components/service-requests/request-list";
import { Header } from "@/components/header";
import { useState } from "react";

export default function ServiceInboxPage() {
  const { user } = useAuth();
  const { t } = useLocale();
  const [includeAll, setIncludeAll] = useState(false);
  const tenantId = user?.current_tenant?.id;
  const { requests, loading, error } = useServiceRequests(tenantId, true, includeAll);
  const role = user?.current_tenant?.role;
  const canViewAll = role === "owner" || role === "admin" || role === "manager";

  if (!user || user.current_tenant?.role === "customer") {
    return (
      <div className="flex-1 flex flex-col h-screen">
        <Header titleKey="reqInbox" />
        <div className="p-6">
          <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl">
            {t("reqUnauthorizedEmployee")}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-[100dvh] overflow-hidden bg-slate-950">
      <Header titleKey="reqInbox" />
      
      <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
        <div className="max-w-4xl mx-auto space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-white mb-1">
                {includeAll ? t("reqIncludeAll") : t("reqAssignedToMe")}
              </h2>
              <p className="text-sm text-slate-400">{t("reqInboxDescription")}</p>
            </div>
            
            {canViewAll && <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 cursor-pointer bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 hover:bg-slate-800/80 transition-colors">
                <input
                  type="checkbox"
                  checked={includeAll}
                  onChange={(e) => setIncludeAll(e.target.checked)}
                  className="rounded border-slate-700 text-emerald-500 focus:ring-emerald-500 bg-slate-950"
                />
                <span className="text-sm text-slate-300">{t("reqIncludeAll")}</span>
              </label>
            </div>}
          </div>
          {error && (
            <div data-testid="service-inbox-error" className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
              {t("reqLoadError")}
            </div>
          )}
          
          <ServiceRequestList 
            requests={requests} 
            loading={loading} 
            basePath="/service-inbox" 
          />
        </div>
      </main>
    </div>
  );
}
