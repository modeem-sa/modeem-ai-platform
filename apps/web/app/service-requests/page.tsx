"use client";

import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";
import { useServiceRequests } from "@/hooks/use-service-requests";
import { ServiceRequestList } from "@/components/service-requests/request-list";
import { NewRequestForm } from "@/components/service-requests/new-request-form";
import { Header } from "@/components/header";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { IconPlus, IconArrowLeft } from "@/components/icons";

export default function ServiceRequestsPage() {
  const { user } = useAuth();
  const { t } = useLocale();
  const [isCreating, setIsCreating] = useState(false);
  const router = useRouter();
  const tenantId = user?.current_tenant?.id;
  const { requests, loading, error, reload } = useServiceRequests(tenantId, false);

  if (!user || !tenantId || user.current_tenant?.role !== "customer") {
    return (
      <div className="flex-1 flex flex-col h-screen">
        <Header titleKey="reqPortal" />
        <div className="p-6">
          <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl">
            {t("reqUnauthorizedCustomer")}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-[100dvh] overflow-hidden bg-slate-950">
      <Header titleKey="reqPortal" />
      
      <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {isCreating ? (
            <div className="space-y-6">
              {error && (
                <div data-testid="service-requests-error" className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
                  {t("reqLoadError")}
                </div>
              )}
              <button 
                onClick={() => setIsCreating(false)}
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
              >
                <IconArrowLeft className="w-4 h-4 rtl:rotate-180" />
                {t("reqPortal")}
              </button>
              
              <div>
                <h2 className="text-xl font-semibold text-white mb-2">{t("reqNew")}</h2>
                <p className="text-sm text-slate-400">{t("serviceWelcomeDesc")}</p>
              </div>

              <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/50">
                <NewRequestForm 
                  tenantId={tenantId}
                  onSuccess={(id) => {
                    setIsCreating(false);
                    void reload();
                    router.push(`/service-requests/${id}`);
                  }}
                  onCancel={() => setIsCreating(false)}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-white mb-1">{t("reqAssignedToMe")}</h2>
                  <p className="text-sm text-slate-400">{t("serviceTrackingTitle")}</p>
                </div>
                <button
                  onClick={() => setIsCreating(true)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors"
                >
                  <IconPlus className="w-4 h-4" />
                  <span className="hidden md:inline">{t("reqNew")}</span>
                </button>
              </div>
              
              <ServiceRequestList 
                requests={requests} 
                loading={loading} 
                basePath="/service-requests" 
              />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
