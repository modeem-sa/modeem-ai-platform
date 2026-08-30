import { useLocale } from "@/components/locale-provider";
import { OperationTask, OpAction } from "@/lib/operations";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  in_progress: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  completed: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  submitted_for_approval: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  approved: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  rejected: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

const PRIORITY_COLORS: Record<string, string> = {
  low: "text-slate-400",
  medium: "text-sky-400",
  high: "text-amber-400",
  urgent: "text-rose-400 font-bold",
};

export function ManualTaskCard({ task, onAction }: { task: OperationTask, onAction: (action: OpAction) => void }) {
  const { t, locale } = useLocale();
  const dateFmt = new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en", { dateStyle: "medium" });

  const statusKey = `opStatus${task.status.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('')}`;

  return (
    <div className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/50 p-4 shadow-sm transition-shadow hover:border-slate-700">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">{task.tenant_name}</span>
          <h3 className="text-sm font-semibold text-slate-300">{task.title}</h3>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[task.status] || STATUS_COLORS.pending}`}>
          {t(statusKey) || task.status}
        </span>
      </div>

      {task.description && (
        <p className="mb-4 line-clamp-2 text-xs text-slate-500">{task.description}</p>
      )}

      <div className="mt-auto flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2 text-[10px] text-slate-400">
          <div>
            <span className="block uppercase tracking-wider text-slate-600">{t("opCategory")}</span>
            {task.category === "administrative" ? t("opCatAdministrative") : t("opCatFinancial")}
          </div>
          <div>
            <span className="block uppercase tracking-wider text-slate-600">{t("opPriority")}</span>
            <span className={PRIORITY_COLORS[task.priority]}>
              {t(`opPrio${task.priority.charAt(0).toUpperCase() + task.priority.slice(1)}`)}
            </span>
          </div>
          <div>
            <span className="block uppercase tracking-wider text-slate-600">{t("opAssignee")}</span>
            {task.assignee_name || <span className="text-slate-600 italic">{t("opUnassigned")}</span>}
          </div>
          <div>
            <span className="block uppercase tracking-wider text-slate-600">{t("opDueDate")}</span>
            {task.due_at ? dateFmt.format(new Date(task.due_at)) : "—"}
          </div>
        </div>

        {task.available_actions && task.available_actions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 border-t border-slate-800/50 pt-2">
            {task.available_actions.map((action) => {
              const actionKey = `opAction${action.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('')}`;
              const isReject = action === 'reject';
              return (
                <button
                  key={action}
                  onClick={() => onAction(action)}
                  className={`flex-1 rounded-lg px-2 py-1.5 text-[10px] uppercase tracking-wider font-medium transition-colors ${
                    isReject
                      ? "bg-rose-500/10 text-rose-400 hover:bg-rose-500/20"
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white"
                  }`}
                >
                  {t(actionKey) || action}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}