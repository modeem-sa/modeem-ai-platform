"use client";

import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";

export function Header({ titleKey }: { titleKey: string }) {
  const { t, toggleLocale } = useLocale();
  const { user, logout, selectTenant } = useAuth();

  const memberships = user?.memberships ?? [];
  const current = user?.current_tenant ?? null;

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-6 py-4">
      <h1 className="text-xl font-semibold text-white">{t(titleKey)}</h1>
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-3 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-1.5">
            <div className="text-end">
              <div className="text-sm font-medium text-white leading-tight">
                {user.full_name}
              </div>
              <div className="text-[11px] text-slate-400 leading-tight">
                {current ? `${current.name} · ${current.role}` : "—"}
              </div>
            </div>
            {memberships.length > 1 && (
              <select
                value={current?.id ?? ""}
                onChange={(e) => selectTenant(e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
                aria-label={t("tenant")}
              >
                {memberships.map((m) => (
                  <option key={m.tenant_id} value={m.tenant_id}>
                    {m.tenant_name} · {m.role}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={logout}
              className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 transition-colors"
            >
              {t("logout")}
            </button>
          </div>
        )}
        <button
          onClick={toggleLocale}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 transition-colors"
        >
          {t("language")}
        </button>
      </div>
    </header>
  );
}
