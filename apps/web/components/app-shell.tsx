"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";
import { Sidebar } from "@/components/sidebar";

function TenantSelection() {
  const { user, selectTenant, logout } = useAuth();
  const { t } = useLocale();

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900/60 p-6 shadow-lg">
        <h1 className="text-lg font-semibold text-white">{t("selectTenantTitle")}</h1>
        <p className="mt-1 text-sm text-slate-400">{t("selectTenantSubtitle")}</p>
        <div className="mt-5 flex flex-col gap-2">
          {user?.memberships.map((m) => (
            <button
              key={m.tenant_id}
              onClick={() => selectTenant(m.tenant_id)}
              className="flex items-center justify-between rounded-md border border-slate-700 bg-slate-950 px-4 py-3 text-start text-sm text-white transition-colors hover:border-emerald-500 hover:bg-slate-900"
            >
              <span>{m.tenant_name}</span>
              <span className="text-xs text-slate-400">{m.role}</span>
            </button>
          ))}
        </div>
        <button
          onClick={logout}
          className="mt-4 text-sm text-slate-400 underline-offset-4 hover:text-slate-200 hover:underline"
        >
          {t("logout")}
        </button>
      </div>
    </main>
  );
}

/**
 * Renders the authenticated shell (sidebar + content) for app pages and a
 * bare layout for the login page. Blocks page content until the session is
 * verified so protected pages never flash for unauthenticated visitors.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const { t } = useLocale();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        {t("loading")}
      </div>
    );
  }

  // Multiple tenants and none selected yet: force an explicit choice.
  if (!user.current_tenant && user.memberships.length > 0) {
    return <TenantSelection />;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      {children}
    </div>
  );
}
