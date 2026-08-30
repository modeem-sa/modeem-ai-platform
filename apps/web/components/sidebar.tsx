"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/locale-provider";
import { useAuth } from "@/components/auth-provider";

const items = [
  { href: "/", key: "dashboard" },
  { href: "/operations", key: "operations" },
  { href: "/connections", key: "connections" },
  { href: "/workflows", key: "workflows" },
  { href: "/executions", key: "executions" },
  { href: "/agents/content-manager", key: "contentManager" },
  { href: "/audit-logs", key: "auditLogs" },
  { href: "/settings", key: "settings" },
];

export function Sidebar() {
  const { t } = useLocale();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="md:w-60 shrink-0 border-b md:border-b-0 md:border-e border-slate-800 bg-slate-950 p-3 md:p-4 flex flex-col md:h-screen sticky top-0 z-20 w-full">
      <div className="flex items-center justify-between mb-3 md:mb-6 px-2">
        <div>
          <div className="text-base md:text-lg font-bold text-emerald-400">{t("appName")}</div>
          <div className="hidden md:block text-xs text-slate-400 mt-1">{t("tagline")}</div>
        </div>
      </div>

      <div className="flex md:flex-col overflow-x-auto md:overflow-visible gap-2 md:gap-1 pb-2 md:pb-0 hide-scrollbar -mx-3 px-3 md:mx-0 md:px-0">
        {items.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`whitespace-nowrap md:whitespace-normal shrink-0 rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-emerald-500/15 text-emerald-300 font-medium"
                  : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
              }`}
            >
              {t(item.key)}
            </Link>
          );
        })}
      </div>

      <div className="hidden md:block mt-auto border-t border-slate-800 pt-3">
        {user && (
          <div className="mb-2 px-2">
            <div className="truncate text-xs font-medium text-slate-300">{user.full_name || user.email}</div>
            <div className="truncate text-[11px] text-slate-500">{user.current_tenant?.name}</div>
          </div>
        )}
        <button
          onClick={logout}
          className="w-full rounded-md px-3 py-2 text-start text-sm text-slate-400 transition-colors hover:bg-slate-800/60 hover:text-rose-300"
        >
          {t("signOut")}
        </button>
      </div>

      <div className="hidden md:block px-2 text-[11px] text-slate-500">{t("foundationPhase")} · v0.1.0</div>
    </aside>
  );
}
