"use client";

import { useLocale } from "@/components/locale-provider";
import { ServiceRequestPriority, createServiceRequest } from "@/lib/service-requests";
import { useState } from "react";
import { IconAlertCircle } from "@/components/icons";
import { useRequestModules } from "@/hooks/use-service-requests";

export function NewRequestForm({ 
  tenantId, 
  onSuccess, 
  onCancel 
}: { 
  tenantId: string;
  onSuccess: (id: string) => void;
  onCancel: () => void;
}) {
  const { t } = useLocale();
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [requestedModule, setRequestedModule] = useState("");
  const [priority, setPriority] = useState<ServiceRequestPriority>("medium");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { modules, loading: modulesLoading } = useRequestModules(tenantId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || !description.trim()) return;
    
    setSubmitting(true);
    setError(null);
    try {
      const res = await createServiceRequest({
        tenant_id: tenantId,
        subject,
        description,
        ...(requestedModule ? { requested_module: requestedModule } : {}),
        priority
      });
      onSuccess(res.id);
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl">
      {error && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex gap-3">
          <IconAlertCircle className="shrink-0 w-5 h-5" />
          <p>{error}</p>
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">{t("reqSubject")}</label>
          <input
            type="text"
            required
            data-testid="new-request-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            disabled={submitting}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 focus:outline-none focus:border-emerald-500 transition-colors disabled:opacity-50"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">{t("reqDescription")}</label>
          <textarea
            required
            rows={5}
            data-testid="new-request-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 focus:outline-none focus:border-emerald-500 transition-colors disabled:opacity-50 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">{t("reqModule")}</label>
          <select
            data-testid="new-request-module"
            value={requestedModule}
            onChange={(event) => setRequestedModule(event.target.value)}
            disabled={submitting || modulesLoading}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 focus:outline-none focus:border-emerald-500 transition-colors disabled:opacity-50"
          >
            <option value="">{t("reqModuleOptional")}</option>
            {modules.map((module) => (
              <option key={module.name} value={module.name}>
                {module.shortdesc || module.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">{t("reqPriority")}</label>
          <div className="flex flex-wrap gap-3">
            {(["low", "medium", "high", "urgent"] as ServiceRequestPriority[]).map((p) => (
              <label key={p} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="priority"
                  value={p}
                  data-testid={`new-request-priority-${p}`}
                  checked={priority === p}
                  onChange={() => setPriority(p)}
                  disabled={submitting}
                  className="text-emerald-500 bg-slate-900 border-slate-700 focus:ring-emerald-500 focus:ring-offset-slate-950"
                />
                <span className="text-sm text-slate-300">{t(`reqPriority${p.charAt(0).toUpperCase() + p.slice(1)}`)}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 pt-4 border-t border-slate-800">
        <button
          type="submit"
          data-testid="new-request-submit-button"
          disabled={submitting || !subject.trim() || !description.trim()}
          className="px-5 py-2.5 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors disabled:opacity-50"
        >
          {submitting ? t("reqSubmitting") : t("reqSubmit")}
        </button>
        <button
          type="button"
          data-testid="new-request-cancel-button"
          onClick={onCancel}
          disabled={submitting}
          className="px-5 py-2.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 transition-colors disabled:opacity-50"
        >
          {t("reqCancel")}
        </button>
      </div>
    </form>
  );
}
