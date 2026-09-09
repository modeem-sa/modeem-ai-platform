"use client";

import { useLocale } from "@/components/locale-provider";
import {
  RequestAssignee,
  RequestModule,
  ServiceRequest,
  ServiceRequestStatus,
} from "@/lib/service-requests";
import { AutomationWorkflow } from "@/lib/automation";
import { getPriorityLabel, getPriorityColor, getStatusLabel, getStatusColor, formatDate } from "@/lib/utils";
import { useRequestMutations } from "@/hooks/use-service-requests";
import { useState } from "react";
import { IconAlertCircle } from "@/components/icons";

export function RequestDetails({ 
  request, 
  onRefresh,
  isEmployee = false,
  canAssign = false,
  assignees = [],
  modules = [],
  workflows = [],
}: { 
  request: ServiceRequest;
  onRefresh: () => void;
  isEmployee?: boolean;
  canAssign?: boolean;
  assignees?: RequestAssignee[];
  modules?: RequestModule[];
  workflows?: AutomationWorkflow[];
}) {
  const { t, locale } = useLocale();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const mut = useRequestMutations(request.id, request.version, onRefresh);
  const statusTransitions: Record<ServiceRequestStatus, ServiceRequestStatus[]> = {
    open: ["in_progress", "resolved", "closed"],
    in_progress: ["waiting_customer", "resolved", "closed"],
    waiting_customer: ["in_progress", "closed"],
    resolved: ["closed", "open"],
    closed: ["open"],
  };
  const statusOptions = [request.status, ...statusTransitions[request.status]];

  const handleAction = async (action: () => Promise<unknown>) => {
    setSubmitting(true);
    setError(null);
    try {
      await action();
    } catch (err: unknown) {
      if (err instanceof Error && err.message === "conflict") {
        setError(t("reqConflict"));
        setTimeout(onRefresh, 3000);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex gap-3">
          <IconAlertCircle className="shrink-0 w-5 h-5" />
          <p>{error}</p>
        </div>
      )}

      {/* Core Details */}
      <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/50 space-y-4">
        <div>
          <h3 className="text-sm font-medium text-slate-400 mb-1">{t("reqSubject")}</h3>
          <p className="text-base text-slate-200">{request.subject}</p>
        </div>
        
        <div>
          <h3 className="text-sm font-medium text-slate-400 mb-1">{t("reqDescription")}</h3>
          <p className="text-sm text-slate-300 whitespace-pre-wrap">{request.description}</p>
        </div>

        <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-800/60">
          <div>
            <h3 className="text-xs font-medium text-slate-500 mb-1.5">{t("reqStatus")}</h3>
            <span className={`inline-flex text-xs px-2.5 py-1 rounded-full border font-medium ${getStatusColor(request.status)}`}>
              {getStatusLabel(request.status, t)}
            </span>
          </div>
          <div>
            <h3 className="text-xs font-medium text-slate-500 mb-1.5">{t("reqPriority")}</h3>
            <span className={`inline-flex text-xs px-2.5 py-1 rounded-full border font-medium ${getPriorityColor(request.priority)}`}>
              {getPriorityLabel(request.priority, t)}
            </span>
          </div>
        </div>
      </div>

      {/* Employee Actions */}
      {isEmployee && (
        <div className="p-5 rounded-xl border border-emerald-900/30 bg-emerald-950/10 space-y-5">
          <h3 className="text-sm font-medium text-emerald-400 flex items-center gap-2">
            {t("reqActions")}
          </h3>
          
          <div className="space-y-4">
            {/* Status Change */}
            <div className="flex flex-col gap-2">
              <label className="text-xs text-slate-400">{t("reqChangeStatus")}</label>
              <select
                disabled={submitting}
                data-testid="request-status-select"
                value={request.status}
                onChange={(e) => handleAction(() => mut.changeStatus(e.target.value as ServiceRequestStatus))}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                {statusOptions.map(s => (
                  <option key={s} value={s}>{getStatusLabel(s, t)}</option>
                ))}
              </select>
            </div>

            {/* Assignment */}
            {canAssign && <div className="flex flex-col gap-2">
              <label className="text-xs text-slate-400">{t("reqAssignee")}</label>
              <select
                disabled={submitting}
                data-testid="request-assignee-select"
                value={request.assigned_employee_id || ""}
                onChange={(e) => {
                  if (e.target.value && e.target.value !== request.assigned_employee_id) {
                    void handleAction(() => mut.assign(e.target.value));
                  }
                }}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                {assignees.map(a => (
                  <option key={a.user_id} value={a.user_id}>{a.full_name} ({a.role})</option>
                ))}
              </select>
            </div>}

            {/* Classification */}
            <div className="flex flex-col gap-2">
              <label className="text-xs text-slate-400">{t("reqModule")}</label>
              <select
                disabled={submitting}
                data-testid="request-module-select"
                value={request.requested_module || ""}
                onChange={(e) => {
                  if (e.target.value && e.target.value !== request.requested_module) {
                    void handleAction(() => mut.classify(e.target.value));
                  }
                }}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                <option value="">-- {t("reqClassifyModule")} --</option>
                {modules.map(m => (
                  <option key={m.name} value={m.name}>{m.shortdesc || m.name}</option>
                ))}
              </select>
            </div>
            
            {/* Dispatch */}
            {request.requested_module && workflows.length > 0 && (
              <div className="flex flex-col gap-2 pt-2 border-t border-slate-800/60">
                <label className="text-xs text-slate-400">{t("reqDispatch")}</label>
                <select
                  disabled={submitting || !!request.workflow_key}
                  data-testid="request-workflow-select"
                  value={request.workflow_key || ""}
                  onChange={(e) => {
                    if (e.target.value) void handleAction(() => mut.dispatch(e.target.value));
                  }}
                  className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value="">-- {t("reqDispatchWorkflow")} --</option>
                  {workflows.filter(w =>
                    w.required_odoo_module === request.requested_module &&
                    w.enabled &&
                    w.steps.every(step => step.executor_available || w.step_modes[step.key] === "manual")
                  ).map(w => (
                    <option key={w.key} value={w.key}>{locale === "ar" ? w.label_ar : w.label_en}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reopen Action for Customer */}
      {!isEmployee && (request.status === "closed" || request.status === "resolved") && (
        <button
          onClick={() => handleAction(() => mut.changeStatus("open"))}
          disabled={submitting}
          data-testid="request-reopen-button"
          className="w-full py-2.5 rounded-lg border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 transition-colors text-sm font-medium disabled:opacity-50"
        >
          {t("reqReopen")}
        </button>
      )}

      {/* Metadata */}
      <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/30 text-xs text-slate-400 space-y-3">
        <div className="flex justify-between">
          <span>{t("reqReference")}</span>
          <span className="font-mono text-slate-300">{request.public_reference}</span>
        </div>
        <div className="flex justify-between">
          <span>{t("reqDate")}</span>
          <span>{formatDate(request.created_at, locale)}</span>
        </div>
        {request.automation_status !== "none" && (
          <div className="flex justify-between pt-3 border-t border-slate-800">
            <span>{t("reqAutomationStatus")}</span>
            <span className="text-slate-300">{request.automation_status}</span>
          </div>
        )}
        {request.automation_result != null && (
          <div className="pt-3 border-t border-slate-800">
            <div className="mb-2 text-slate-400">{t("reqResult")}</div>
            <pre
              data-testid="request-automation-result"
              className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-start text-xs text-slate-200"
            >
              {typeof request.automation_result === "string"
                ? request.automation_result
                : JSON.stringify(request.automation_result, null, 2)}
            </pre>
          </div>
        )}
        {request.automation_error && (
          <div
            data-testid="request-automation-error"
            className="pt-3 border-t border-slate-800 text-rose-400"
          >
            {request.automation_error}
          </div>
        )}
      </div>
    </div>
  );
}
