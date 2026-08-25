"use client";

import { useState } from "react";
import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";

function csrfHeaders(): Record<string, string> {
  const match = document.cookie.match(/(?:^|;\s*)modeem_csrf=([^;]+)/);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

export default function SettingsPage() {
  const { t } = useLocale();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(
    null,
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    if (newPassword.length < 8) {
      setMessage({ kind: "error", text: t("passwordTooShort") });
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage({ kind: "error", text: t("passwordMismatch") });
      return;
    }
    if (newPassword === currentPassword) {
      setMessage({ kind: "error", text: t("passwordSame") });
      return;
    }
    setSaving(true);
    try {
      const res = await fetch("/backend/api/v1/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        credentials: "same-origin",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (res.ok) {
        setMessage({ kind: "success", text: t("passwordChanged") });
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
      } else if (res.status === 400) {
        const body = await res.json().catch(() => null);
        const detail: string = body?.detail ?? "";
        setMessage({
          kind: "error",
          text: detail.includes("different") ? t("passwordSame") : t("passwordChangeFailed"),
        });
      } else {
        setMessage({ kind: "error", text: t("passwordChangeError") });
      }
    } catch {
      setMessage({ kind: "error", text: t("passwordChangeError") });
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-slate-500 focus:outline-none";

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey="settings" />
      <main className="flex-1 p-6">
        <div className="max-w-md rounded-lg border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-lg font-semibold text-white">{t("changePassword")}</h2>
          <form onSubmit={onSubmit} className="mt-4 space-y-4">
            <div>
              <label htmlFor="current-password" className="mb-1 block text-sm text-slate-300">
                {t("currentPassword")}
              </label>
              <input
                id="current-password"
                type="password"
                autoComplete="current-password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="new-password" className="mb-1 block text-sm text-slate-300">
                {t("newPassword")}
              </label>
              <input
                id="new-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="confirm-password" className="mb-1 block text-sm text-slate-300">
                {t("confirmNewPassword")}
              </label>
              <input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            {message && (
              <p
                role="alert"
                className={`text-sm ${message.kind === "success" ? "text-emerald-400" : "text-red-400"}`}
              >
                {message.text}
              </p>
            )}
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-60 transition-colors"
            >
              {saving ? t("saving") : t("changePassword")}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
