"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const { t } = useLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await login(email, password);
      if (res.ok) {
        router.push("/");
      } else if (res.status === 401) {
        setError(t("loginError"));
      } else {
        setError(t("loginErrorGeneric"));
      }
    } catch {
      setError(t("loginErrorGeneric"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm px-4">
      <div className="mb-8 text-center">
        <div className="text-2xl font-bold text-emerald-400">{t("appName")}</div>
        <div className="mt-1 text-sm text-slate-400">{t("tagline")}</div>
      </div>

      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-800 bg-slate-900/80 p-6 shadow-xl backdrop-blur"
      >
        <h1 className="mb-6 text-lg font-semibold text-slate-100">{t("signIn")}</h1>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-700/50 bg-rose-900/20 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}

        <div className="mb-4">
          <label className="mb-1 block text-sm text-slate-400" htmlFor="email">
            {t("email")}
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            placeholder="admin@acme.com"
            dir="ltr"
          />
        </div>

        <div className="mb-6">
          <label className="mb-1 block text-sm text-slate-400" htmlFor="password">
            {t("password")}
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            dir="ltr"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? t("signingIn") : t("signIn")}
        </button>
      </form>

      <p className="mt-6 text-center text-xs text-slate-500">{t("foundationPhase")} · v0.1.0</p>
    </div>
  );
}
