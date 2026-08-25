"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Membership = { tenant_id: string; tenant_name: string; role: string };
export type CurrentTenant = { id: string; name: string; role: string };
export type AuthUser = {
  id: string;
  email: string;
  full_name: string;
  is_superuser: boolean;
  current_tenant: CurrentTenant | null;
  memberships: Membership[];
};

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<{ ok: boolean; status: number }>;
  logout: () => Promise<void>;
  selectTenant: (tenantId: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function csrfHeaders(): Record<string, string> {
  const match = document.cookie.match(/(?:^|;\s*)modeem_csrf=([^;]+)/);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/backend/api/v1/auth/me", { credentials: "same-origin" });
      setUser(res.ok ? await res.json() : null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (loading) return;
    if (!user && pathname !== "/login") router.replace("/login");
    if (user && pathname === "/login") router.replace("/");
  }, [loading, user, pathname, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch("/backend/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ email, password }),
      });
      if (res.ok) {
        setUser(await res.json());
        router.replace("/");
      }
      return { ok: res.ok, status: res.status };
    },
    [router],
  );

  const logout = useCallback(async () => {
    await fetch("/backend/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: csrfHeaders(),
    });
    setUser(null);
    router.replace("/login");
  }, [router]);

  const selectTenant = useCallback(async (tenantId: string) => {
    const res = await fetch("/backend/api/v1/auth/tenant", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      credentials: "same-origin",
      body: JSON.stringify({ tenant_id: tenantId }),
    });
    if (res.ok) setUser(await res.json());
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, login, logout, selectTenant }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
