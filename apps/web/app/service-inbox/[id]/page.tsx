"use client";

import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";
import { useServiceRequest, useRequestMutations, useRequestAssignees, useRequestModules } from "@/hooks/use-service-requests";
import { Header } from "@/components/header";
import { IconArrowLeft, IconRefreshCw } from "@/components/icons";
import Link from "next/link";
import { useParams } from "next/navigation";
import { RequestConversation } from "@/components/service-requests/request-conversation";
import { RequestDetails } from "@/components/service-requests/request-details";
import { useState, useEffect } from "react";
import { AutomationWorkflow, fetchAutomationCatalog } from "@/lib/automation";

export default function EmployeeInboxDetailPage() {
  const { id } = useParams() as { id: string };
  const { t } = useLocale();
  const { user } = useAuth();
  const tenantId = user?.current_tenant?.id;
  const role = user?.current_tenant?.role;
  const canAssign = role === "owner" || role === "admin" || role === "manager";
  
  const { request, loading, error, reload } = useServiceRequest(id);
  const { assignees } = useRequestAssignees(tenantId, canAssign);
  const { modules } = useRequestModules(tenantId);
  const [workflows, setWorkflows] = useState<AutomationWorkflow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  
  const mut = useRequestMutations(id, request?.version || 0, reload);

  useEffect(() => {
    if (!tenantId) return;
    fetchAutomationCatalog(tenantId)
      .then(res => setWorkflows(res.workflows))
      .catch(console.error);
  }, [tenantId]);

  if (!user || user.current_tenant?.role === "customer") {
    return (
      <div className="flex-1 flex flex-col h-screen">
        <Header titleKey="reqDetails" />
        <div className="p-6">
          <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl">
            {t("reqUnauthorizedEmployee")}
          </div>
        </div>
      </div>
    );
  }

  const handleSend = async (body: string) => {
    setSubmitting(true);
    try {
      await mut.sendMessage(body);
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpload = async (file: File) => {
    setSubmitting(true);
    try {
      await mut.uploadAttachment(file);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-[100dvh] bg-slate-950">
      <Header titleKey="reqDetails" />
      
      <main className="flex-1 overflow-hidden flex flex-col p-4 md:p-6 lg:p-8">
        <div className="max-w-7xl mx-auto w-full h-full flex flex-col">
          <div className="mb-6 shrink-0 flex items-center justify-between">
            <Link 
              href="/service-inbox"
              className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
            >
              <IconArrowLeft className="w-4 h-4 rtl:rotate-180" />
              {t("reqInbox")}
            </Link>
            
            <button 
              onClick={reload}
              className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
              title={t("reqRefresh")}
            >
              <IconRefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
          
          {loading && !request ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="w-8 h-8 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin"></div>
            </div>
          ) : !request ? (
            <div className="p-6 text-center text-slate-400 border border-slate-800 rounded-xl bg-slate-900/30">
              {error ? t("reqLoadError") : t("reqNotFound")}
            </div>
          ) : (
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column: Details & Employee Actions */}
              <div className="lg:col-span-1 overflow-y-auto hide-scrollbar space-y-6 pr-2 rtl:pr-0 rtl:pl-2">
                <RequestDetails 
                  request={request}
                  onRefresh={reload}
                  isEmployee={true}
                  canAssign={canAssign}
                  assignees={assignees}
                  modules={modules}
                  workflows={workflows}
                />
              </div>
              
              {/* Right Column: Conversation */}
              <div className="lg:col-span-2 flex flex-col min-h-0 h-[60vh] lg:h-auto">
                <RequestConversation 
                  request={request}
                  onSendMessage={handleSend}
                  onUploadAttachment={handleUpload}
                  isSubmitting={submitting}
                />
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
