"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Header } from "@/components/header";
import { useAuth } from "@/components/auth-provider";
import { useLocale } from "@/components/locale-provider";

type Tenant = { id: string; name: string };
type Membership = {
  id: string; tenant_id: string; tenant_name: string; user_id: string; email: string;
  full_name: string; user_is_active: boolean; role: string; is_active: boolean;
  odoo_module_scope: string[] | null;
  service_scope: string[] | null;
};
type SelectableUser = { id: string; email: string; full_name: string };
type Bootstrap = { tenants: Tenant[]; memberships: Membership[]; scope_modules: string[]; scope_services: string[]; users: SelectableUser[] };
type Assignment = { tenant_id: string; role: string; is_active: boolean; odoo_module_scope: string[] | null; service_scope: string[] | null };

const roles = ["owner", "admin", "manager", "member", "viewer", "customer"];
const csrfHeaders = (): Record<string, string> => {
  const token = document.cookie.match(/(?:^|;\s*)modeem_csrf=([^;]+)/)?.[1];
  return token ? { "X-CSRF-Token": decodeURIComponent(token) } : {};
};
function ScopeEditor({ assignment, modules, services, onChange, ar, disabled = false, allowUnrestricted = true }: { assignment: Assignment; modules: string[]; services: string[]; onChange: (change: Partial<Assignment>) => void; ar: boolean; disabled?: boolean; allowUnrestricted?: boolean }) {
  const toggle = (key: "odoo_module_scope" | "service_scope", value: string) => {
    const current = assignment[key];
    if (current === null) return;
    onChange({ [key]: current.includes(value) ? current.filter((item) => item !== value) : [...current, value] });
  };
  const group = (key: "odoo_module_scope" | "service_scope", title: string, values: string[]) => {
    const unrestricted = assignment[key] === null;
    return <fieldset className="rounded border border-slate-800 p-2" disabled={disabled}>
      <legend className="px-1 text-slate-400">{title}</legend>
      <div className="mb-2 flex gap-3">
        <label className={unrestricted ? "font-medium text-emerald-300" : "text-slate-400"}><input type="radio" checked={unrestricted} disabled={!allowUnrestricted} onChange={() => onChange({ [key]: null })} /> {ar ? "غير مقيّد" : "Unrestricted"}</label>
        <label className={!unrestricted ? "font-medium text-sky-300" : "text-slate-400"}><input type="radio" checked={!unrestricted} onChange={() => onChange({ [key]: [] })} /> {ar ? "مقيّد" : "Restricted"}</label>
      </div>
      {unrestricted ? <p className="rounded bg-emerald-950/40 p-2 text-emerald-300">{ar ? "يشمل كل الخيارات المسموحة." : "Includes every allowed option."}</p> :
        <div className="flex flex-wrap gap-2">{values.map((item) => <label key={item} className="text-slate-300"><input type="checkbox" checked={assignment[key]?.includes(item) ?? false} onChange={() => toggle(key, item)} /> {item}</label>)}{assignment[key]?.length === 0 && <span className="text-amber-300">{ar ? "لا يوجد وصول" : "No access"}</span>}</div>}
    </fieldset>;
  };
  return <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">{group("odoo_module_scope", ar ? "موديولات Odoo" : "Odoo modules", modules)}{group("service_scope", ar ? "الخدمات" : "Services", services)}</div>;
}

export default function PermissionsPage() {
  const { user } = useAuth();
  const { locale } = useLocale();
  const ar = locale === "ar";
  const current = user?.current_tenant;
  const canManage = Boolean(user?.is_superuser || ["owner", "admin"].includes(current?.role ?? "") ||
    (current?.role === "manager" && current.service_scope?.includes("tenant_memberships")));
  const delegatedManager = current?.role === "manager";
  const [data, setData] = useState<Bootstrap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [email, setEmail] = useState(""); const [name, setName] = useState(""); const [password, setPassword] = useState("");
  const [accountMode, setAccountMode] = useState<"new" | "existing">("new");
  const [existingUserId, setExistingUserId] = useState("");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [tenantToAdd, setTenantToAdd] = useState("");
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    const response = await fetch("/backend/api/v1/permissions", { credentials: "same-origin" });
    if (!response.ok) throw new Error();
    const next: Bootstrap = await response.json();
    setData(next);
    setTenantToAdd((old) => old || next.tenants[0]?.id || "");
  }, []);
  useEffect(() => { if (canManage) void load().catch(() => setError(ar ? "تعذر تحميل الصلاحيات." : "Could not load permissions.")); }, [load, canManage, ar]);

  const addAssignment = () => {
    if (!tenantToAdd || assignments.some((item) => item.tenant_id === tenantToAdd)) return;
    setAssignments((old) => [...old, {
      tenant_id: tenantToAdd,
      role: "member",
      is_active: true,
      odoo_module_scope: delegatedManager ? [] : null,
      service_scope: delegatedManager ? [] : null,
    }]);
  };
  const updateAssignment = (index: number, change: Partial<Assignment>) =>
    setAssignments((old) => old.map((item, i) => i === index ? { ...item, ...change } : item));
  const create = async (event: React.FormEvent) => {
    event.preventDefault(); if (!assignments.length) return;
    setSaving(true); setError(null);
    try {
      const response = await fetch("/backend/api/v1/permissions", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify(accountMode === "existing"
          ? { user_id: existingUserId, memberships: assignments }
          : { email, full_name: name, password, memberships: assignments }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail);
      setEmail(""); setName(""); setPassword(""); setExistingUserId(""); setAssignments([]); await load();
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : (ar ? "تعذر حفظ الحساب." : "Could not save account.")); }
    finally { setSaving(false); }
  };
  const patch = async (member: Membership, changes: Record<string, unknown>) => {
    setSaving(true); setError(null);
    try {
      const response = await fetch(`/backend/api/v1/permissions/memberships/${member.id}`, {
        method: "PATCH", credentials: "same-origin", headers: { "Content-Type": "application/json", ...csrfHeaders() }, body: JSON.stringify(changes),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail);
      await load();
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : (ar ? "تعذر تحديث العضوية." : "Could not update membership.")); }
    finally { setSaving(false); }
  };
  const visible = useMemo(() => (data?.memberships ?? []).filter((m) =>
    `${m.full_name} ${m.email} ${m.tenant_name}`.toLowerCase().includes(filter.toLowerCase())), [data, filter]);
  const roleOptions = delegatedManager ? roles.filter((item) => !["owner", "admin"].includes(item)) : roles;
  const moduleOptions = delegatedManager ? (current?.odoo_module_scope ?? data?.scope_modules ?? []) : (data?.scope_modules ?? []);
  const serviceOptions = delegatedManager ? (current?.service_scope ?? []) : (data?.scope_services ?? []);
  if (!canManage) return <div className="flex flex-1 flex-col"><Header titleKey="permissions" /><main className="p-6 text-slate-300">{ar ? "ليس لديك صلاحية إدارة المستخدمين." : "You do not have permission to manage people."}</main></div>;

  return <div className="flex min-w-0 flex-1 flex-col" dir={ar ? "rtl" : "ltr"}>
    <Header titleKey="permissions" />
    <main className="flex-1 space-y-6 p-4 sm:p-6">
      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="text-lg font-semibold text-white">{ar ? "إضافة حساب" : "Add an account"}</h2>
        <p className="mt-1 text-sm text-slate-400">{ar ? "يمكن منح الحساب عضوية في جمعية واحدة أو أكثر." : "Assign the account to one or more associations."}</p>
        <form onSubmit={create} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="flex gap-3 sm:col-span-2 lg:col-span-3"><label><input type="radio" checked={accountMode === "new"} onChange={() => setAccountMode("new")} /> {ar ? "حساب جديد" : "New account"}</label><label><input type="radio" checked={accountMode === "existing"} onChange={() => setAccountMode("existing")} /> {ar ? "حساب موجود" : "Existing account"}</label></div>
          {accountMode === "new" ? <><input required value={name} onChange={(e) => setName(e.target.value)} placeholder={ar ? "الاسم الكامل" : "Full name"} className="rounded border border-slate-700 bg-slate-950 p-2" /><input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={ar ? "البريد الإلكتروني" : "Email"} className="rounded border border-slate-700 bg-slate-950 p-2" /><input required minLength={8} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={ar ? "كلمة المرور" : "Password"} className="rounded border border-slate-700 bg-slate-950 p-2" /></> : <select required value={existingUserId} onChange={(e) => setExistingUserId(e.target.value)} className="rounded border border-slate-700 bg-slate-950 p-2 sm:col-span-2 lg:col-span-3"><option value="">{ar ? "اختر حساباً" : "Select an account"}</option>{data?.users.map((u) => <option key={u.id} value={u.id}>{u.full_name} · {u.email}</option>)}</select>}
          <div className="flex gap-2 sm:col-span-2 lg:col-span-3">
            <select value={tenantToAdd} onChange={(e) => setTenantToAdd(e.target.value)} className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 p-2">
              {data?.tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button type="button" onClick={addAssignment} className="rounded border border-sky-700 px-3 text-sky-300">{ar ? "إضافة جمعية" : "Add association"}</button>
          </div>
          {assignments.map((assignment, index) => <div key={assignment.tenant_id} className="rounded border border-slate-700 p-3 sm:col-span-2 lg:col-span-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="me-auto text-sm text-white">{data?.tenants.find((t) => t.id === assignment.tenant_id)?.name}</span>
              <select value={assignment.role} onChange={(e) => updateAssignment(index, { role: e.target.value })} className="rounded bg-slate-950 p-1 text-sm">{roleOptions.map((r) => <option key={r}>{r}</option>)}</select>
              <button type="button" onClick={() => setAssignments((old) => old.filter((_, i) => i !== index))} className="text-sm text-rose-300">{ar ? "إزالة" : "Remove"}</button>
            </div>
            <ScopeEditor assignment={assignment} modules={moduleOptions} services={serviceOptions} onChange={(change) => updateAssignment(index, change)} ar={ar} allowUnrestricted={!delegatedManager} />
            {assignment.role === "customer" && <p className="mt-2 text-xs text-amber-300">{ar ? "حساب عميل: سيقتصر الوصول على بوابة طلبات الخدمة." : "Customer accounts are limited to the service-request portal."}</p>}
          </div>)}
          <button disabled={saving || !assignments.length} className="rounded bg-emerald-500 p-2 font-medium text-slate-950 disabled:opacity-60 sm:col-span-2 lg:col-span-3">{saving ? (ar ? "جارٍ الحفظ…" : "Saving…") : (ar ? "إنشاء الحساب" : "Create account")}</button>
        </form>
      </section>
      {error && <p role="alert" className="rounded border border-red-800 p-3 text-red-300">{error}</p>}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold text-white">{ar ? "العضويات الحالية" : "Existing memberships"}</h2><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={ar ? "بحث…" : "Search…"} className="rounded border border-slate-700 bg-slate-950 p-2 text-sm" /></div>
        {data === null ? <p className="text-slate-400">{ar ? "جارٍ التحميل…" : "Loading…"}</p> : visible.length === 0 ? <p className="rounded border border-dashed border-slate-700 p-8 text-center text-slate-400">{ar ? "لا توجد عضويات." : "No memberships found."}</p> :
          <div className="grid gap-3 md:grid-cols-2">{visible.map((m) => <article key={m.id} className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
             <div className="flex items-start justify-between gap-2"><div><h3 className="font-medium text-white">{m.full_name}</h3><p className="text-sm text-slate-500">{m.email} · {m.tenant_name}</p></div><button disabled={saving || (delegatedManager && ["owner", "admin"].includes(m.role))} onClick={() => void patch(m, { is_active: !m.is_active })} className={m.is_active ? "text-emerald-400 disabled:opacity-50" : "text-slate-500 disabled:opacity-50"}>{m.is_active ? (ar ? "نشط" : "Active") : (ar ? "معطل" : "Inactive")}</button></div>
             <div className="mt-3 flex flex-wrap gap-2"><select disabled={saving || (delegatedManager && ["owner", "admin"].includes(m.role))} value={m.role} onChange={(e) => void patch(m, { role: e.target.value })} className="rounded bg-slate-950 p-1 text-sm">{(delegatedManager && ["owner", "admin"].includes(m.role) ? [m.role] : roleOptions).map((r) => <option key={r}>{r}</option>)}</select>{m.role === "customer" && <span className="text-xs text-amber-300">{ar ? "عميل — وصول محدود" : "Customer — limited access"}</span>}</div>
             {delegatedManager && ["owner", "admin"].includes(m.role) ? <p className="mt-3 rounded bg-slate-800 p-2 text-xs text-slate-400">{ar ? "عضوية بصلاحيات أعلى — للعرض فقط." : "Elevated membership — read only."}</p> : <ScopeEditor assignment={{ tenant_id: m.tenant_id, role: m.role, is_active: m.is_active, odoo_module_scope: m.odoo_module_scope, service_scope: m.service_scope }} modules={moduleOptions} services={serviceOptions} ar={ar} allowUnrestricted={!delegatedManager} onChange={(change) => void patch(m, change)} />}
          </article>)}</div>}
      </section>
    </main>
  </div>;
}