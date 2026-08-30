"use client";

import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";

export function Header({ titleKey }: { titleKey: string }) {
  const { t, toggleLocale } = useLocale();
  const { user, logout, selectTenant } = useAuth();

  const memberships = user?.memberships ?? [];
  const current = user?.current_tenant ?? null;

  return (
    <header className="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-800 bg-slate-900/60 px-4 md:px-6 py-3 md:py-4 gap-3 md:gap-0">
      <h1 className="text-lg md:text-xl font-semibold text-white">{t(titleKey)}</h1>
      <div className="flex flex-wrap items-center gap-2 md:gap-3 w-full md:w-auto justify-between md:justify-end">
        {user && (
          <div className="flex items-center gap-2 md:gap-3 rounded-md border border-slate-800 bg-slate-950/60 px-2 md:px-3 py-1.5 flex-1 md:flex-none justify-between md:justify-start">
            <div className="hidden md:block text-end">
              <div className="text-sm font-medium text-white leading-tight">
                {user.full_name}
              </div>
              <div className="text-[11px] text-slate-400 leading-tight">
                {current ? `${current.name} · ${current.role}` : "—"}
              </div>
            </div>

            {memberships.length > 1 ? (
              <select
                value={current?.id ?? ""}
                onChange={(e) => selectTenant(e.target.value)}
                className="max-w-[120px] md:max-w-none rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 truncate"
                aria-label={t("tenant")}
              >
                {memberships.map((m) => (
                  <option key={m.tenant_id} value={m.tenant_id}>
                    {m.tenant_name} · {m.role}
                  </option>
                ))}
              </select>
            ) : (
              <div className="md:hidden text-xs text-slate-300 truncate max-w-[120px]">
                {current?.name || user.full_name}
              </div>
            )}

            <button
              onClick={logout}
              className="shrink-0 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 transition-colors"
            >
              {t("logout")}
            </button>
          </div>
        )}
        <button
          onClick={toggleLocale}
          className="shrink-0 rounded-md border border-slate-700 px-3 py-1.5 text-xs md:text-sm text-slate-200 hover:bg-slate-800 transition-colors"
        >
          {t("language")}
        </button>
      </div>
    </header>
  );
}
