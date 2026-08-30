"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";

type ConnectionOut = {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  database_name: string | null;
  username: string | null;
  status: string;
  is_active: boolean;
  has_credentials: boolean;
  auth_mode: string;
  detected_odoo_version: string | null;
  detected_edition: string | null;
  selected_transport: string | null;
  last_tested_at: string | null;
  last_test_status: string | null;
  last_test_error_code: string | null;
  updated_at: string;
};

type PreviewResource =
  | "countries"
  | "beneficiaries_summary"
  | "customers"
  | "invoices"
  | "installed_modules"
  | "companies"
  | "employees_summary"
  | "departments_summary"
  | "vendor_bills"
  | "payments_summary"
  | "journals_summary";

type PreviewRecord = {
  id?: number;
  name?: string;
  code?: string;
  is_family?: boolean;
  total_draft_supports?: number;
  total_paid_supports?: number;
  email?: string | null;
  phone?: string | null;
  mobile?: string | null;
  vat?: string | null;
  company_type?: string;
  active?: boolean;
  move_type?: string;
  state?: string;
  invoice_date?: string | null;
  invoice_date_due?: string | null;
  partner_id?: [number, string] | null;
  currency_id?: [number, string] | null;
  amount_total?: number;
  amount_residual?: number;
  payment_state?: string | null;
  shortdesc?: string;
  installed_version?: string | null;
  application?: boolean;
  category_id?: [number, string] | null;
  job_title?: string | null;
  department_id?: [number, string] | null;
  manager_id?: [number, string] | null;
  company_id?: [number, string] | null;
  country_id?: [number, string] | null;
  date?: string;
  amount?: number;
  payment_type?: string;
  partner_type?: string;
  type?: string;
};

type PreviewPage = {
  resource: string;
  records: PreviewRecord[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
};

const COMPANY_SCOPED_RESOURCES = new Set<PreviewResource>([
  "invoices",
  "employees_summary",
  "departments_summary",
  "vendor_bills",
  "payments_summary",
  "journals_summary",
]);

function resourceRequiresCompany(resource: PreviewResource): boolean {
  return COMPANY_SCOPED_RESOURCES.has(resource);
}

function csrfHeaders(): Record<string, string> {
  const match = document.cookie.match(/(?:^|;\s*)modeem_csrf=([^;]+)/);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

type FormState = {
  name: string;
  base_url: string;
  database_name: string;
  username: string;
  auth_mode: string;
  secret: string;
};

const emptyForm: FormState = {
  name: "",
  base_url: "",
  database_name: "",
  username: "",
  auth_mode: "auto",
  secret: "",
};

export default function ConnectionsPage() {
  const { t, locale } = useLocale();
  const { user } = useAuth();
  const role = user?.current_tenant?.role ?? "";
  const canWrite = role === "owner" || role === "admin" || role === "superuser";

  const [rows, setRows] = useState<ConnectionOut[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [editing, setEditing] = useState<ConnectionOut | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const credentialMustBeReentered =
    !editing ||
    form.username.trim() !== (editing.username ?? "").trim() ||
    form.auth_mode !== (editing.auth_mode ?? "auto");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [previewConn, setPreviewConn] = useState<ConnectionOut | null>(null);
  const [previewResource, setPreviewResource] = useState<PreviewResource>("countries");
  const [previewPage, setPreviewPage] = useState<PreviewPage | null>(null);
  const [previewLimit, setPreviewLimit] = useState(25);
  const [previewOffset, setPreviewOffset] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [installedModules, setInstalledModules] = useState<Set<string>>(new Set());
  const [companies, setCompanies] = useState<PreviewRecord[]>([]);
  const [companyId, setCompanyId] = useState<number | null>(null);
  // Guards against out-of-order preview responses (e.g. switching
  // resource while a slower previous request is still in flight).
  const previewReqRef = useRef(0);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/backend/api/v1/connections", { credentials: "same-origin" });
      if (!res.ok) throw new Error();
      setRows(await res.json());
      setLoadError(false);
    } catch {
      setLoadError(true);
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError(null);
    setShowForm(true);
  };

  const openEdit = (c: ConnectionOut) => {
    setEditing(c);
    setForm({
      name: c.name,
      base_url: c.base_url,
      database_name: c.database_name ?? "",
      username: c.username ?? "",
      auth_mode: c.auth_mode ?? "auto",
      secret: "", // never pre-fill an existing secret
    });
    setFormError(null);
    setShowForm(true);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (credentialMustBeReentered && !form.secret) {
      setFormError(t("connSecretRequiredAfterIdentityChange"));
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      let res: Response;
      if (editing) {
        const body: Record<string, unknown> = {
          name: form.name,
          base_url: form.base_url,
          database_name: form.database_name || null,
          auth_mode: form.auth_mode,
        };
        // Canonical login: Connection.username only. Never send it as null
        // (it cannot be cleared); omit to preserve.
        if (form.username.trim()) {
          body.username = form.username.trim();
        }
        if (form.secret) {
          body.credentials = { password_or_api_key: form.secret };
        }
        res = await fetch(`/backend/api/v1/connections/${editing.id}`, {
          method: "PATCH",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify(body),
        });
      } else {
        res = await fetch("/backend/api/v1/connections", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            name: form.name,
            provider: "odoo",
            base_url: form.base_url,
            database_name: form.database_name || null,
            username: form.username.trim(),
            auth_mode: form.auth_mode,
            credentials: { password_or_api_key: form.secret },
          }),
        });
      }
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setFormError(typeof data?.detail === "string" ? data.detail : t("connError"));
        return;
      }
      // Clear form state (including the secret) before closing.
      setForm(emptyForm);
      setEditing(null);
      setShowForm(false);
      await load();
    } catch {
      setFormError(t("connError"));
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async (c: ConnectionOut) => {
    setTestingId(c.id);
    try {
      const res = await fetch(`/backend/api/v1/connections/${c.id}/test`, {
        method: "POST",
        credentials: "same-origin",
        headers: csrfHeaders(),
      });
      if (res.ok) {
        await res.json();
      }
      await load();
    } finally {
      setTestingId(null);
    }
  };

  const loadPreview = async (
    c: ConnectionOut,
    limit: number,
    offset: number,
    resource: PreviewResource,
    selectedCompanyId: number | null = companyId,
  ) => {
    const reqId = ++previewReqRef.current;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await fetch(`/backend/api/v1/connections/${c.id}/read-preview`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        // Ordering uses only server-allowlisted fields (name for both resources).
        body: JSON.stringify({
          resource,
          limit,
          offset,
          order_by: "name",
          order_direction: "asc",
          ...(resourceRequiresCompany(resource) && selectedCompanyId
            ? { company_id: selectedCompanyId }
            : {}),
        }),
      });
      if (reqId !== previewReqRef.current) return; // stale response; ignore
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const code = data?.detail?.error_code;
        if (res.status === 409) throw new Error("unavailable");
        if (code === "access_denied") throw new Error("access_denied");
        throw new Error("preview");
      }
      setPreviewPage(await res.json());
      setPreviewLimit(limit);
      setPreviewOffset(offset);
    } catch (error) {
      if (reqId !== previewReqRef.current) return;
      const message = error instanceof Error ? error.message : "preview";
      setPreviewError(
        message === "unavailable"
          ? t("previewModuleUnavailable")
          : message === "access_denied"
            ? t("previewAccessDenied")
            : t("previewError"),
      );
    } finally {
      if (reqId === previewReqRef.current) setPreviewLoading(false);
    }
  };

  const loadPreviewContext = async (c: ConnectionOut) => {
    const request = (body: Record<string, unknown>) =>
      fetch(`/backend/api/v1/connections/${c.id}/read-preview`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify(body),
      });
    try {
      const [moduleRes, companyRes] = await Promise.all([
        request({
          resource: "installed_modules",
          filters: [{ field: "name", operator: "in", value: ["hr", "account"] }],
          limit: 10,
          order_by: "name",
        }),
        request({ resource: "companies", limit: 50, order_by: "name" }),
      ]);
      if (moduleRes.ok) {
        const page: PreviewPage = await moduleRes.json();
        setInstalledModules(new Set(page.records.map((r) => r.name).filter(Boolean) as string[]));
      }
      if (companyRes.ok) {
        const page: PreviewPage = await companyRes.json();
        setCompanies(page.records);
        const firstId = page.records.find((r) => typeof r.id === "number")?.id ?? null;
        setCompanyId(firstId);
      }
    } catch {
      setInstalledModules(new Set());
      setCompanies([]);
      setCompanyId(null);
    }
  };

  const openPreview = (c: ConnectionOut) => {
    setPreviewConn(c);
    setPreviewPage(null);
    setPreviewResource("companies");
    setInstalledModules(new Set());
    setCompanies([]);
    setCompanyId(null);
    void loadPreviewContext(c);
    void loadPreview(c, 25, 0, "companies");
  };

  const changePreviewResource = (resource: PreviewResource) => {
    if (!previewConn) return;
    setPreviewResource(resource);
    setPreviewPage(null);
    setPreviewOffset(0);
    void loadPreview(previewConn, previewLimit, 0, resource);
  };

  const closePreview = () => {
    setPreviewConn(null);
    setPreviewPage(null);
    setPreviewError(null);
    setPreviewOffset(0);
    setPreviewLimit(25);
    setPreviewResource("countries");
    setInstalledModules(new Set());
    setCompanies([]);
    setCompanyId(null);
  };

  const disable = async (c: ConnectionOut) => {
    if (!window.confirm(t("connDisableConfirm"))) return;
    const res = await fetch(`/backend/api/v1/connections/${c.id}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: csrfHeaders(),
    });
    if (res.ok) await load();
  };

  const dateFmt = new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en", {
    dateStyle: "medium",
  });

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <Header titleKey="connections" />
      <main className="min-w-0 flex-1 p-6">
        <div className="mb-4 flex items-center justify-between">
          <div />
          {canWrite && (
            <button
              onClick={openCreate}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400"
            >
              {t("connNew")}
            </button>
          )}
        </div>

        {loadError && (
          <p className="mb-4 rounded-md border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">
            {t("connLoadError")}
          </p>
        )}

        {rows === null ? (
          <p className="text-slate-400">{t("loading")}</p>
        ) : rows.length === 0 && !loadError ? (
          <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
            <p className="text-slate-300">{t("connEmpty")}</p>
            <p className="mt-2 text-sm text-slate-500">{t("connEmptyHint")}</p>
          </div>
        ) : rows.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-start font-medium">{t("connName")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connProvider")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connBaseUrl")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connDatabase")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connUsername")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connStatus")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connCredentials")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connOdooVersion")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connLastTest")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("connUpdated")}</th>
                  {canWrite && (
                    <th className="px-4 py-3 text-start font-medium">{t("connActions")}</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950/40">
                {rows.map((c) => (
                  <tr key={c.id} className="text-slate-200">
                    <td className="px-4 py-3 font-medium text-white">{c.name}</td>
                    <td className="px-4 py-3">{c.provider}</td>
                    <td className="px-4 py-3 text-slate-400" dir="ltr">
                      {c.base_url}
                    </td>
                    <td className="px-4 py-3">{c.database_name ?? "—"}</td>
                    <td className="px-4 py-3">{c.username ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span
                        className={
                          c.status === "configured"
                            ? "rounded-full bg-emerald-950 px-2.5 py-1 text-xs text-emerald-400"
                            : "rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-400"
                        }
                      >
                        {c.status === "configured" ? t("connConfigured") : t("connDisabled")}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {c.has_credentials ? t("connCredsSet") : t("connCredsMissing")}
                    </td>
                    <td className="px-4 py-3 text-slate-400" dir="ltr">
                      {c.detected_odoo_version
                        ? `${c.detected_odoo_version}${
                            c.detected_edition && c.detected_edition !== "unknown"
                              ? ` (${
                                  c.detected_edition === "enterprise"
                                    ? t("connEnterprise")
                                    : t("connCommunity")
                                })`
                              : ""
                          }${c.selected_transport ? ` · ${c.selected_transport}` : ""}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {c.last_test_status === "success" ? (
                        <span className="rounded-full bg-emerald-950 px-2.5 py-1 text-xs text-emerald-400">
                          {t("connTestOk")}
                        </span>
                      ) : c.last_test_status === "error" ? (
                        <span
                          className="rounded-full bg-red-950 px-2.5 py-1 text-xs text-red-400"
                          title={c.last_test_error_code ?? undefined}
                        >
                          {t("connTestFail")}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                      {c.last_tested_at && (
                        <span className="ms-2 text-xs text-slate-500">
                          {dateFmt.format(new Date(c.last_tested_at))}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{dateFmt.format(new Date(c.updated_at))}</td>
                    {canWrite && (
                      <td className="px-4 py-3">
                        <div className="flex gap-3">
                          {c.status !== "disabled" && c.has_credentials && (
                            <button
                              onClick={() => void testConnection(c)}
                              disabled={testingId === c.id}
                              className="text-sky-400 hover:text-sky-300 disabled:opacity-60"
                            >
                              {testingId === c.id ? t("connTesting") : t("connTest")}
                            </button>
                          )}
                          {c.status !== "disabled" && c.last_test_status === "success" && (
                            <button
                              onClick={() => openPreview(c)}
                              className="text-violet-400 hover:text-violet-300"
                            >
                              {t("connPreview")}
                            </button>
                          )}
                          <button
                            onClick={() => openEdit(c)}
                            className="text-emerald-400 hover:text-emerald-300"
                          >
                            {t("connEdit")}
                          </button>
                          {c.status !== "disabled" && (
                            <button
                              onClick={() => void disable(c)}
                              className="text-red-400 hover:text-red-300"
                            >
                              {t("connDisable")}
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {previewConn && canWrite && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            onClick={closePreview}
          >
            <div
              role="dialog"
              aria-modal="true"
              className="max-h-[calc(100vh-2rem)] w-full max-w-6xl overflow-y-auto rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-xl"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="sticky top-0 z-20 -mx-6 -mt-6 flex items-center justify-between border-b border-slate-800 bg-slate-900 px-6 py-4">
                <h2 className="text-lg font-semibold text-white">
                  {t("connPreviewTitle")} — {previewConn.name}
                </h2>
                <button
                  onClick={closePreview}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
                >
                  <span aria-hidden="true" className="me-1 text-base">×</span>
                  {t("connClose")}
                </button>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-300">
                <label>
                  {t("previewResource")}
                  <select
                    value={previewResource}
                    onChange={(e) =>
                      changePreviewResource(e.target.value as PreviewResource)
                    }
                    className="ms-2 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-white"
                  >
                    <option value="countries">{t("previewCountries")}</option>
                    <option value="beneficiaries_summary">{t("previewBeneficiaries")}</option>
                    <option value="customers">{t("previewCustomers")}</option>
                    <option value="invoices">{t("previewInvoices")}</option>
                    <option value="installed_modules">{t("previewInstalledModules")}</option>
                    <option value="companies">{t("previewCompanies")}</option>
                    {installedModules.has("hr") && (
                      <>
                        <option value="employees_summary">{t("previewEmployees")}</option>
                        <option value="departments_summary">{t("previewDepartments")}</option>
                      </>
                    )}
                    {installedModules.has("account") && (
                      <>
                        <option value="vendor_bills">{t("previewVendorBills")}</option>
                        <option value="payments_summary">{t("previewPayments")}</option>
                        <option value="journals_summary">{t("previewJournals")}</option>
                      </>
                    )}
                  </select>
                </label>
                {resourceRequiresCompany(previewResource) && (
                  <label>
                    {t("previewCompanyScope")}
                    <select
                      value={companyId ?? ""}
                      onChange={(e) => {
                        const next = Number(e.target.value);
                        setCompanyId(next);
                        setPreviewPage(null);
                        setPreviewOffset(0);
                        void loadPreview(
                          previewConn,
                          previewLimit,
                          0,
                          previewResource,
                          next,
                        );
                      }}
                      className="ms-2 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-white"
                    >
                      {companies.map((company) => (
                        <option key={company.id} value={company.id}>
                          {company.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  {t("previewPageSize")}
                  <select
                    value={previewLimit}
                    onChange={(e) =>
                      void loadPreview(previewConn, Number(e.target.value), 0, previewResource)
                    }
                    className="ms-2 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-white"
                  >
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                  </select>
                </label>
              </div>

              {previewError && (
                <p className="mt-4 rounded-md border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">
                  {previewError}
                </p>
              )}

              {previewLoading ? (
                <p className="mt-4 text-slate-400">{t("loading")}</p>
              ) : previewPage && previewPage.records.length > 0 ? (
                <div className="mt-4 overflow-x-auto rounded-lg border border-slate-800">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-950 text-slate-400">
                      <tr>
                        <th className="px-4 py-2 text-start font-medium">{t("previewId")}</th>
                        <th className="px-4 py-2 text-start font-medium">{t("previewName")}</th>
                        {previewResource === "countries" ? (
                          <th className="px-4 py-2 text-start font-medium">{t("previewCode")}</th>
                        ) : previewResource === "beneficiaries_summary" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewIsFamily")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewDraftSupports")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewPaidSupports")}</th>
                          </>
                        ) : previewResource === "customers" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewEmail")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewPhone")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewVat")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCompanyType")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("active")}</th>
                          </>
                        ) : previewResource === "invoices" || previewResource === "vendor_bills" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCustomer")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewInvoiceDate")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewDueDate")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewTotal")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewResidual")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewPaymentState")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("status")}</th>
                          </>
                        ) : previewResource === "installed_modules" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewModuleTitle")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewModuleVersion")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewModuleCategory")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewModuleApplication")}</th>
                          </>
                        ) : previewResource === "companies" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCountry")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCurrency")}</th>
                          </>
                        ) : previewResource === "employees_summary" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewJobTitle")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewDepartment")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("active")}</th>
                          </>
                        ) : previewResource === "departments_summary" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewManager")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("active")}</th>
                          </>
                        ) : previewResource === "payments_summary" ? (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewDate")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewAmount")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewPaymentType")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewPartner")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("status")}</th>
                          </>
                        ) : (
                          <>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCode")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("type")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("previewCurrency")}</th>
                            <th className="px-4 py-2 text-start font-medium">{t("active")}</th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {previewPage.records.map((r, i) => (
                        <tr key={r.id ?? i} className="text-slate-200">
                          <td className="px-4 py-2" dir="ltr">{r.id ?? "—"}</td>
                          <td className="px-4 py-2">{r.name ?? "—"}</td>
                          {previewResource === "countries" ? (
                            <td className="px-4 py-2" dir="ltr">{r.code ?? "—"}</td>
                          ) : previewResource === "beneficiaries_summary" ? (
                            <>
                              <td className="px-4 py-2">
                                {typeof r.is_family === "boolean"
                                  ? r.is_family
                                    ? t("previewYes")
                                    : t("previewNo")
                                  : "—"}
                              </td>
                              <td className="px-4 py-2" dir="ltr">
                                {typeof r.total_draft_supports === "number"
                                  ? r.total_draft_supports
                                  : "—"}
                              </td>
                              <td className="px-4 py-2" dir="ltr">
                                {typeof r.total_paid_supports === "number"
                                  ? r.total_paid_supports
                                  : "—"}
                              </td>
                            </>
                          ) : previewResource === "customers" ? (
                            <>
                              <td className="px-4 py-2" dir="ltr">{r.email ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">
                                {r.phone ?? r.mobile ?? "—"}
                              </td>
                              <td className="px-4 py-2" dir="ltr">{r.vat ?? "—"}</td>
                              <td className="px-4 py-2">
                                {r.company_type === "company"
                                  ? t("previewCompany")
                                  : t("previewPerson")}
                              </td>
                              <td className="px-4 py-2">
                                {typeof r.active === "boolean"
                                  ? r.active
                                    ? t("previewYes")
                                    : t("previewNo")
                                  : "—"}
                              </td>
                            </>
                          ) : previewResource === "invoices" || previewResource === "vendor_bills" ? (
                            <>
                              <td className="px-4 py-2">{r.partner_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">{r.invoice_date ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">{r.invoice_date_due ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">
                                {typeof r.amount_total === "number"
                                  ? `${r.amount_total} ${r.currency_id?.[1] ?? ""}`.trim()
                                  : "—"}
                              </td>
                              <td className="px-4 py-2" dir="ltr">
                                {typeof r.amount_residual === "number"
                                  ? `${r.amount_residual} ${r.currency_id?.[1] ?? ""}`.trim()
                                  : "—"}
                              </td>
                              <td className="px-4 py-2">{r.payment_state ?? "—"}</td>
                              <td className="px-4 py-2">{r.state ?? "—"}</td>
                            </>
                          ) : previewResource === "installed_modules" ? (
                            <>
                              <td className="px-4 py-2">{r.shortdesc ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">
                                {r.installed_version ?? "—"}
                              </td>
                              <td className="px-4 py-2">{r.category_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">
                                {typeof r.application === "boolean"
                                  ? r.application
                                    ? t("previewYes")
                                    : t("previewNo")
                                  : "—"}
                              </td>
                            </>
                          ) : previewResource === "companies" ? (
                            <>
                              <td className="px-4 py-2">{r.country_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">{r.currency_id?.[1] ?? "—"}</td>
                            </>
                          ) : previewResource === "employees_summary" ? (
                            <>
                              <td className="px-4 py-2">{r.job_title ?? "—"}</td>
                              <td className="px-4 py-2">{r.department_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">
                                {r.active ? t("previewYes") : t("previewNo")}
                              </td>
                            </>
                          ) : previewResource === "departments_summary" ? (
                            <>
                              <td className="px-4 py-2">{r.manager_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">
                                {r.active ? t("previewYes") : t("previewNo")}
                              </td>
                            </>
                          ) : previewResource === "payments_summary" ? (
                            <>
                              <td className="px-4 py-2" dir="ltr">{r.date ?? "—"}</td>
                              <td className="px-4 py-2" dir="ltr">
                                {typeof r.amount === "number"
                                  ? `${r.amount} ${r.currency_id?.[1] ?? ""}`.trim()
                                  : "—"}
                              </td>
                              <td className="px-4 py-2">{r.payment_type ?? "—"}</td>
                              <td className="px-4 py-2">{r.partner_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">{r.state ?? "—"}</td>
                            </>
                          ) : (
                            <>
                              <td className="px-4 py-2" dir="ltr">{r.code ?? "—"}</td>
                              <td className="px-4 py-2">{r.type ?? "—"}</td>
                              <td className="px-4 py-2">{r.currency_id?.[1] ?? "—"}</td>
                              <td className="px-4 py-2">
                                {r.active ? t("previewYes") : t("previewNo")}
                              </td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : previewPage ? (
                <p className="mt-4 text-slate-400">{t("previewEmpty")}</p>
              ) : null}

              <div className="mt-4 flex items-center justify-between text-sm">
                <button
                  disabled={previewLoading || previewOffset === 0}
                  onClick={() =>
                    void loadPreview(
                      previewConn,
                      previewLimit,
                      Math.max(0, previewOffset - previewLimit),
                      previewResource,
                    )
                  }
                  className="rounded-md border border-slate-700 px-3 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                >
                  {t("previewPrev")}
                </button>
                <span className="text-slate-500">
                  {previewPage
                    ? `${previewOffset + 1}–${previewOffset + previewPage.returned_count}`
                    : ""}
                </span>
                <button
                  disabled={previewLoading || !previewPage?.has_more}
                  onClick={() =>
                    void loadPreview(
                      previewConn,
                      previewLimit,
                      previewPage?.next_offset ?? previewOffset + previewLimit,
                      previewResource,
                    )
                  }
                  className="rounded-md border border-slate-700 px-3 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                >
                  {t("previewNext")}
                </button>
              </div>
            </div>
          </div>
        )}

        {showForm && canWrite && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <form
              onSubmit={submit}
              className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-xl"
            >
              <h2 className="text-lg font-semibold text-white">
                {editing ? t("connEditTitle") : t("connCreateTitle")}
              </h2>

              <div className="mt-4 grid gap-4">
                <label className="text-sm text-slate-300">
                  {t("connName")}
                  <input
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="text-sm text-slate-300">
                  {t("connProvider")}
                  <select
                    disabled
                    value="odoo"
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
                  >
                    <option value="odoo">Odoo</option>
                  </select>
                </label>
                <label className="text-sm text-slate-300">
                  {t("connBaseUrl")}
                  <input
                    required
                    type="url"
                    dir="ltr"
                    placeholder="https://example.odoo.com"
                    value={form.base_url}
                    onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="text-sm text-slate-300">
                  {t("connDatabase")}
                  <input
                    dir="ltr"
                    value={form.database_name}
                    onChange={(e) => setForm({ ...form, database_name: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="text-sm text-slate-300">
                  {t("connUsername")}
                  <input
                    dir="ltr"
                    required={!editing}
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="text-sm text-slate-300">
                  {t("connAuthMode")}
                  <select
                    value={form.auth_mode}
                    onChange={(e) => setForm({ ...form, auth_mode: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  >
                    <option value="auto">{t("connAuthAuto")}</option>
                    <option value="password">{t("connAuthPassword")}</option>
                    <option value="api_key">{t("connAuthApiKey")}</option>
                  </select>
                </label>
                <label className="text-sm text-slate-300">
                  {t("connPasswordLabel")}
                  {credentialMustBeReentered && <span className="text-red-400"> *</span>}
                  <input
                    type="password"
                    autoComplete="new-password"
                    required={credentialMustBeReentered}
                    value={form.secret}
                    onChange={(e) => setForm({ ...form, secret: e.target.value })}
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-emerald-500"
                  />
                  {editing && !credentialMustBeReentered && (
                    <span className="mt-1 block text-xs text-slate-500">
                      {t("connKeepSecretHint")}
                    </span>
                  )}
                  {editing && credentialMustBeReentered && (
                    <span className="mt-1 block text-xs text-amber-400">
                      {t("connSecretRequiredAfterIdentityChange")}
                    </span>
                  )}
                </label>
              </div>

              {formError && <p className="mt-4 text-sm text-red-400">{formError}</p>}

              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => {
                    // Clear secret/form state on cancel.
                    setForm(emptyForm);
                    setEditing(null);
                    setFormError(null);
                    setShowForm(false);
                  }}
                  className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
                >
                  {t("connCancel")}
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
                >
                  {saving ? t("connSaving") : t("connSave")}
                </button>
              </div>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}
