"use client";

import { useLocale } from "@/components/locale-provider";
import { getPriorityLabel, getPriorityColor, getStatusLabel, getStatusColor, formatDate } from "@/lib/utils";
import { ServiceRequest } from "@/lib/service-requests";
import Link from "next/link";
import { IconInbox, IconMessage, IconPaperclip, IconClock } from "@/components/icons";

export function ServiceRequestList({ 
  requests, 
  loading, 
  basePath 
}: { 
  requests: ServiceRequest[]; 
  loading: boolean;
  basePath: string;
}) {
  const { t, locale } = useLocale();

  if (loading && requests.length === 0) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse flex items-center justify-between p-4 rounded-xl border border-slate-800/60 bg-slate-900/40">
            <div className="flex gap-4">
              <div className="h-10 w-10 bg-slate-800 rounded-lg"></div>
              <div className="space-y-2">
                <div className="h-4 w-48 bg-slate-800 rounded"></div>
                <div className="h-3 w-32 bg-slate-800 rounded"></div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-4 text-center rounded-xl border border-slate-800/60 bg-slate-900/20 border-dashed">
        <div className="h-12 w-12 rounded-full bg-slate-800 flex items-center justify-center mb-4 text-slate-400">
          <IconInbox />
        </div>
        <h3 className="text-lg font-medium text-slate-300 mb-1">{t("reqEmpty")}</h3>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {requests.map((req) => (
        <Link 
          key={req.id} 
          href={`${basePath}/${req.id}`}
          data-testid={`request-list-item-${req.id}`}
          className="block group p-4 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-slate-800/50 hover:border-slate-700 transition-all duration-200"
        >
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-xs font-mono text-slate-500 bg-slate-950 px-2 py-0.5 rounded-md border border-slate-800">{req.public_reference}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${getStatusColor(req.status)}`}>
                  {getStatusLabel(req.status, t)}
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${getPriorityColor(req.priority)}`}>
                  {getPriorityLabel(req.priority, t)}
                </span>
              </div>
              <h4 className="text-base font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
                {req.subject}
              </h4>
            </div>
            
            <div className="flex items-center gap-4 text-xs text-slate-400 shrink-0">
              <div className="flex items-center gap-1.5" title={t("reqConversation")}>
                <IconMessage className="w-3.5 h-3.5" />
                <span>{req.messages.length}</span>
              </div>
              {req.attachments.length > 0 && (
                <div className="flex items-center gap-1.5" title={t("reqAttachments")}>
                  <IconPaperclip className="w-3.5 h-3.5" />
                  <span>{req.attachments.length}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-slate-500">
                <IconClock className="w-3.5 h-3.5" />
                <span>{formatDate(req.updated_at, locale)}</span>
              </div>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}
