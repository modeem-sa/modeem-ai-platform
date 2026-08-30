import { useState, useEffect, useCallback } from "react";
import { useLocale } from "@/components/locale-provider";
import { fetchRecurringTemplates, createRecurringTemplate, enableRecurringTemplate, RecurringTemplate, CreateRecurringTemplatePayload, OperationsBootstrap } from "@/lib/operations";

export function RecurringTemplates({ bootstrap }: { bootstrap: OperationsBootstrap }) {
  const { t } = useLocale();
  const [templates, setTemplates] = useState<RecurringTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRecurringTemplates();
      setTemplates(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await enableRecurringTemplate(id, enabled);
      void load();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : t("opToggleTemplateFailed"));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">{t("opTemplatesTitle")}</h2>
          <p className="text-sm text-slate-400">{t("opTemplatesDesc")}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-400"
        >
          {t("opNewTemplate")}
        </button>
      </div>

      {error && <div className="rounded-xl border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-300">{error}</div>}

      {loading ? (
        <div className="py-12 text-center text-slate-400">{t("loading")}</div>
      ) : templates.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-12 text-center">
          <p className="text-slate-300">{t("opNoTemplates")}</p>
          <p className="mt-2 text-sm text-slate-500">{t("opNoTemplatesHint")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {templates.map((tpl) => (
            <div key={tpl.id} className="flex flex-col rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-sm">
              <div className="mb-3 flex items-start justify-between">
                <div>
                  <h3 className="text-base font-semibold text-slate-100">{tpl.title}</h3>
                  <span className="text-xs text-slate-500">
                    {t(tpl.frequency === 'daily' ? 'opDaily' : tpl.frequency === 'weekly' ? 'opWeekly' : 'opMonthly')} • {tpl.timezone}
                  </span>
                </div>
                <button 
                  onClick={() => handleToggle(tpl.id, !tpl.enabled)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${tpl.enabled ? 'bg-emerald-500' : 'bg-slate-700'}`}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${tpl.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </div>
              {tpl.description && <p className="mb-4 text-sm text-slate-400">{tpl.description}</p>}
              <div className="mt-auto flex gap-4 text-xs text-slate-500">
                <span>{tpl.category}</span>
                <span>{tpl.priority}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateTemplateModal bootstrap={bootstrap} onClose={() => setShowCreate(false)} onSuccess={() => { setShowCreate(false); void load(); }} />
      )}
    </div>
  );
}

function CreateTemplateModal({ bootstrap, onClose, onSuccess }: { bootstrap: OperationsBootstrap, onClose: () => void, onSuccess: () => void }) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<CreateRecurringTemplatePayload>({
    tenant_id: bootstrap.tenants[0]?.id || "",
    title: "",
    description: "",
    category: "administrative",
    priority: "medium",
    frequency: "monthly",
    timezone: "UTC"
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createRecurringTemplate(form);
      onSuccess();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("opSaveTemplateFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="mb-5 text-lg font-bold text-slate-100">{t("opNewTemplate")}</h2>
        
        {error && <div className="mb-4 rounded-lg bg-rose-950/50 p-3 text-sm text-rose-400">{error}</div>}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTenant")}
            <select required value={form.tenant_id} onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500">
              {bootstrap.tenants.filter(t => t.can_create).map(tenant => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskTitle")}
            <input required type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500" />
          </label>
          <label className="flex flex-col gap-1.5 text-sm text-slate-300">
            {t("opTaskDesc")}
            <textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500" />
          </label>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opFrequency")}
              <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500">
                <option value="daily">{t("opDaily")}</option>
                <option value="weekly">{t("opWeekly")}</option>
                <option value="monthly">{t("opMonthly")}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opTimezone")}
              <input type="text" required value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} placeholder={t("opTimezonePlaceholder")} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500" />
            </label>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opCategory")}
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500">
                <option value="administrative">{t("opCatAdministrative")}</option>
                <option value="financial">{t("opCatFinancial")}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm text-slate-300">
              {t("opPriority")}
              <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-indigo-500">
                <option value="low">{t("opPrioLow")}</option>
                <option value="medium">{t("opPrioMedium")}</option>
                <option value="high">{t("opPrioHigh")}</option>
                <option value="urgent">{t("opPrioUrgent")}</option>
              </select>
            </label>
          </div>
          
          <div className="mt-4 flex justify-end gap-3 border-t border-slate-800 pt-4">
            <button type="button" onClick={onClose} disabled={saving} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200">{t("opCancel")}</button>
            <button type="submit" disabled={saving} className="rounded-lg bg-indigo-500 px-6 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50">{saving ? t("saving") : t("save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}