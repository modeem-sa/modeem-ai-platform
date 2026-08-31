"""Centralized read-policy registry for bounded, read-only Odoo resources.

The API caller NEVER supplies a raw Odoo model name, method name, raw
domain, order string, or field TYPE. Callers use a Modeem `resource_key`;
every model, field (with its expected value type), filter operator, and
order field is allowlisted here, server-side only.

Each business resource is added only after explicit approval of its model,
server-owned base domain and minimal field set. Customer and customer-invoice
summaries intentionally exclude private notes, banking data, invoice lines,
attachments and every write operation.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

# Global request-shape bounds for the read-preview phase.
MAX_FILTERS = 5
MAX_REQUESTED_FIELDS = 20
MAX_FILTER_STRING_LENGTH = 200
MAX_FILTER_LIST_ITEMS = 50
MAX_PREVIEW_OFFSET = 1000
DEFAULT_PAGE_SIZE = 25
ABSOLUTE_MAX_PAGE_SIZE = 50

# Small safe operator subset. AND-only semantics; no |, &, !, child_of,
# parent_of, raw domains, or arbitrary operators.
SAFE_OPERATORS = frozenset({"=", "!=", "in", "ilike", ">=", "<="})
FINANCIAL_SAFE_OPERATORS = SAFE_OPERATORS

FieldValueType = Literal[
    "integer", "string", "boolean", "number", "date", "datetime", "many2one"
]


@dataclass(frozen=True)
class ReadFieldPolicy:
    """Server-side declaration of a field's expected value type. Types are
    NEVER accepted from callers; they exist only in this registry.

    In addition to the base type, string fields may declare a fullmatch
    `pattern`, and integer fields a [min_value, max_value] range — values
    outside the contract are rejected locally BEFORE any network call.
    """

    name: str
    value_type: FieldValueType
    nullable: bool = False
    max_length: int | None = None
    pattern: str | None = None
    min_value: int = 1
    max_value: int = 2_147_483_647

    def __post_init__(self):
        if self.pattern is not None:
            re.compile(self.pattern)  # fail fast on bad patterns at import


@dataclass(frozen=True)
class ReadPolicy:
    resource_key: str
    odoo_model: str
    fields: dict[str, ReadFieldPolicy]
    default_fields: tuple[str, ...]
    allowed_filter_fields: frozenset[str]
    allowed_filter_operators: frozenset[str]
    allowed_order_fields: frozenset[str]
    base_domain: tuple[tuple[Any, ...], ...] = ()
    max_page_size: int = field(default=ABSOLUTE_MAX_PAGE_SIZE)
    required_module: str | None = None
    requires_company_scope: bool = False

    @property
    def allowed_fields(self) -> frozenset[str]:
        return frozenset(self.fields)

    def __post_init__(self):
        # Every filterable field MUST declare an explicit field policy.
        missing = self.allowed_filter_fields - set(self.fields)
        if missing:
            raise ValueError(
                f"policy '{self.resource_key}' missing field policies "
                f"for filterable fields: {sorted(missing)}"
            )


def _fields(*policies: ReadFieldPolicy) -> dict[str, ReadFieldPolicy]:
    return {p.name: p for p in policies}


_COUNTRIES = ReadPolicy(
    resource_key="countries",
    odoo_model="res.country",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        # Country names are human text but bounded and printable-only
        # (no control chars, no SQL/ilike wildcards, no backslashes).
        ReadFieldPolicy(
            name="name",
            value_type="string",
            nullable=False,
            max_length=100,
            pattern=r"[^\x00-\x1f\x7f%_\\]{1,100}",
        ),
        # ISO-like country codes: short ASCII letters only.
        ReadFieldPolicy(
            name="code",
            value_type="string",
            nullable=False,
            max_length=4,
            pattern=r"[A-Za-z]{1,4}",
        ),
    ),
    default_fields=("id", "name", "code"),
    allowed_filter_fields=frozenset({"id", "name", "code"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "code"}),
    max_page_size=ABSOLUTE_MAX_PAGE_SIZE,
)

# Phase 2F: first real business resource — a privacy-reviewed SUMMARY
# subset of the Modeem BMS beneficiary model (modeem.bms.beneficiary,
# Odoo 16 module). ONLY the five approved fields exist here; sensitive
# fields (id_type, id_number, birth_date, age, phone_number, nationality,
# gender, family_id, family_member_ids, relationship_type,
# beneficiary_type, support_ids, active, audit/avatar fields) are
# deliberately ABSENT and must go through explicit privacy review before
# ever being added. Filters are allowed only on id/name/is_family (not on
# financial totals) and ordering only on id/name.
_BENEFICIARIES_SUMMARY = ReadPolicy(
    resource_key="beneficiaries_summary",
    odoo_model="modeem.bms.beneficiary",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        # Beneficiary names are personal data: bounded, printable-only
        # (no control chars, no SQL/ilike wildcards, no backslashes).
        ReadFieldPolicy(
            name="name",
            value_type="string",
            nullable=False,
            max_length=255,
            pattern=r"[^\x00-\x1f\x7f%_\\]{1,255}",
        ),
        ReadFieldPolicy(name="is_family", value_type="boolean", nullable=False),
        ReadFieldPolicy(
            name="total_draft_supports", value_type="number", nullable=False
        ),
        ReadFieldPolicy(
            name="total_paid_supports", value_type="number", nullable=False
        ),
    ),
    default_fields=(
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    ),
    allowed_filter_fields=frozenset({"id", "name", "is_family"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
    max_page_size=ABSOLUTE_MAX_PAGE_SIZE,
)

# Read-only customer summary. A server-owned domain restricts this resource to
# customer partners; callers cannot remove or replace it. Private notes,
# addresses, bank details, credit limits and chatter data are deliberately
# excluded.
_CUSTOMERS = ReadPolicy(
    resource_key="customers",
    odoo_model="res.partner",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(
            name="name",
            value_type="string",
            nullable=False,
            max_length=255,
            pattern=r"[^\x00-\x1f\x7f%_\\]{1,255}",
        ),
        ReadFieldPolicy(name="email", value_type="string", nullable=True, max_length=320),
        ReadFieldPolicy(name="phone", value_type="string", nullable=True, max_length=64),
        ReadFieldPolicy(name="mobile", value_type="string", nullable=True, max_length=64),
        ReadFieldPolicy(name="vat", value_type="string", nullable=True, max_length=64),
        ReadFieldPolicy(
            name="company_type",
            value_type="string",
            nullable=False,
            max_length=16,
            pattern=r"(person|company)",
        ),
        ReadFieldPolicy(
            name="customer_rank",
            value_type="integer",
            nullable=False,
            min_value=0,
        ),
        ReadFieldPolicy(name="active", value_type="boolean", nullable=False),
    ),
    default_fields=(
        "id",
        "name",
        "email",
        "phone",
        "mobile",
        "vat",
        "company_type",
        "active",
    ),
    allowed_filter_fields=frozenset(
        {"id", "name", "email", "vat", "company_type", "active"}
    ),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
    base_domain=(("customer_rank", ">", 0),),
    max_page_size=ABSOLUTE_MAX_PAGE_SIZE,
)

# Read-only customer invoice summary. Vendor bills, journal entries, lines,
# attachments and free-text narration are outside this resource.
_INVOICES = ReadPolicy(
    resource_key="invoices",
    odoo_model="account.move",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(
            name="move_type",
            value_type="string",
            nullable=False,
            max_length=32,
            pattern=r"(out_invoice|out_refund)",
        ),
        ReadFieldPolicy(
            name="state",
            value_type="string",
            nullable=False,
            max_length=16,
            pattern=r"(draft|posted|cancel)",
        ),
        ReadFieldPolicy(name="invoice_date", value_type="date", nullable=True),
        ReadFieldPolicy(name="invoice_date_due", value_type="date", nullable=True),
        ReadFieldPolicy(name="partner_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="amount_total", value_type="number", nullable=False),
        ReadFieldPolicy(name="amount_residual", value_type="number", nullable=False),
        ReadFieldPolicy(
            name="payment_state",
            value_type="string",
            nullable=True,
            max_length=32,
        ),
    ),
    default_fields=(
        "id",
        "name",
        "move_type",
        "state",
        "invoice_date",
        "invoice_date_due",
        "partner_id",
        "currency_id",
        "company_id",
        "amount_total",
        "amount_residual",
        "payment_state",
    ),
    allowed_filter_fields=frozenset(
        {"id", "name", "move_type", "state", "invoice_date", "payment_state"}
    ),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "invoice_date", "amount_total"}),
    base_domain=(("move_type", "in", ("out_invoice", "out_refund")),),
    max_page_size=ABSOLUTE_MAX_PAGE_SIZE,
    required_module="account",
    requires_company_scope=True,
)

# Technical module inventory used to compare the live Odoo database with the
# approved repository catalog. Only installed modules are returned; callers
# cannot query uninstalled applications or arbitrary ir.model metadata.
_INSTALLED_MODULES = ReadPolicy(
    resource_key="installed_modules",
    odoo_model="ir.module.module",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(
            name="name",
            value_type="string",
            nullable=False,
            max_length=255,
            pattern=r"[A-Za-z0-9_]{1,255}",
        ),
        ReadFieldPolicy(
            name="shortdesc",
            value_type="string",
            nullable=False,
            max_length=255,
        ),
        ReadFieldPolicy(
            name="installed_version",
            value_type="string",
            nullable=True,
            max_length=64,
        ),
        ReadFieldPolicy(name="application", value_type="boolean", nullable=False),
        ReadFieldPolicy(name="category_id", value_type="many2one", nullable=True),
    ),
    default_fields=(
        "id",
        "name",
        "shortdesc",
        "installed_version",
        "application",
        "category_id",
    ),
    allowed_filter_fields=frozenset({"id", "name", "application"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
    base_domain=(("state", "=", "installed"),),
    max_page_size=ABSOLUTE_MAX_PAGE_SIZE,
)

_COMPANIES = ReadPolicy(
    resource_key="companies",
    odoo_model="res.company",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="country_id", value_type="many2one", nullable=True),
    ),
    default_fields=("id", "name", "currency_id", "country_id"),
    allowed_filter_fields=frozenset({"id", "name"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
)

_EMPLOYEES_SUMMARY = ReadPolicy(
    resource_key="employees_summary",
    odoo_model="hr.employee",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="job_title", value_type="string", nullable=True, max_length=255),
        ReadFieldPolicy(name="department_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="active", value_type="boolean", nullable=False),
    ),
    default_fields=("id", "name", "job_title", "department_id", "company_id", "active"),
    allowed_filter_fields=frozenset({"id", "name", "active"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
    base_domain=(("active", "=", True),),
    required_module="hr",
    requires_company_scope=True,
)

_ATTENDANCE_SUMMARY = ReadPolicy(
    resource_key="attendance_summary",
    odoo_model="hr.attendance",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="employee_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(
            name="check_in", value_type="datetime", nullable=False, max_length=32
        ),
        ReadFieldPolicy(
            name="check_out", value_type="datetime", nullable=True, max_length=32
        ),
        ReadFieldPolicy(name="worked_hours", value_type="number", nullable=False),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
    ),
    default_fields=(
        "id",
        "employee_id",
        "check_in",
        "check_out",
        "worked_hours",
        "company_id",
    ),
    allowed_filter_fields=frozenset({"id", "employee_id", "check_in", "check_out"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "check_in", "check_out", "worked_hours"}),
    required_module="hr_attendance",
    requires_company_scope=True,
)

_LEAVES_SUMMARY = ReadPolicy(
    resource_key="leaves_summary",
    odoo_model="hr.leave",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="employee_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="holiday_status_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="request_date_from", value_type="date", nullable=True),
        ReadFieldPolicy(name="request_date_to", value_type="date", nullable=True),
        ReadFieldPolicy(name="number_of_days", value_type="number", nullable=False),
        ReadFieldPolicy(name="state", value_type="string", nullable=False, max_length=32),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
    ),
    default_fields=(
        "id",
        "employee_id",
        "holiday_status_id",
        "request_date_from",
        "request_date_to",
        "number_of_days",
        "state",
        "company_id",
    ),
    allowed_filter_fields=frozenset(
        {"id", "employee_id", "request_date_from", "request_date_to", "state"}
    ),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset(
        {"id", "request_date_from", "request_date_to", "number_of_days"}
    ),
    required_module="hr_holidays",
    requires_company_scope=True,
)

_PAYROLL_SUMMARY = ReadPolicy(
    resource_key="payroll_summary",
    odoo_model="hr.payslip",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="employee_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="date_from", value_type="date", nullable=False),
        ReadFieldPolicy(name="date_to", value_type="date", nullable=False),
        ReadFieldPolicy(name="state", value_type="string", nullable=False, max_length=32),
        ReadFieldPolicy(name="struct_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="net_wage", value_type="number", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
    ),
    default_fields=(
        "id",
        "name",
        "employee_id",
        "date_from",
        "date_to",
        "state",
        "struct_id",
        "net_wage",
        "company_id",
    ),
    allowed_filter_fields=frozenset(
        {"id", "employee_id", "date_from", "date_to", "state"}
    ),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset(
        {"id", "name", "date_from", "date_to", "net_wage"}
    ),
    required_module="hr_payroll",
    requires_company_scope=True,
)

_DEPARTMENTS_SUMMARY = ReadPolicy(
    resource_key="departments_summary",
    odoo_model="hr.department",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="manager_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="active", value_type="boolean", nullable=False),
    ),
    default_fields=("id", "name", "manager_id", "company_id", "active"),
    allowed_filter_fields=frozenset({"id", "name", "active"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name"}),
    base_domain=(("active", "=", True),),
    required_module="hr",
    requires_company_scope=True,
)

_VENDOR_BILLS = ReadPolicy(
    resource_key="vendor_bills",
    odoo_model="account.move",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="move_type", value_type="string", nullable=False, max_length=32),
        ReadFieldPolicy(name="state", value_type="string", nullable=False, max_length=16),
        ReadFieldPolicy(name="invoice_date", value_type="date", nullable=True),
        ReadFieldPolicy(name="invoice_date_due", value_type="date", nullable=True),
        ReadFieldPolicy(name="partner_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="amount_total", value_type="number", nullable=False),
        ReadFieldPolicy(name="amount_residual", value_type="number", nullable=False),
        ReadFieldPolicy(name="payment_state", value_type="string", nullable=True, max_length=32),
    ),
    default_fields=(
        "id", "name", "move_type", "state", "invoice_date", "invoice_date_due",
        "partner_id", "currency_id", "company_id", "amount_total", "amount_residual",
        "payment_state",
    ),
    allowed_filter_fields=frozenset(
        {"id", "name", "state", "invoice_date", "payment_state"}
    ),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "invoice_date", "amount_total"}),
    base_domain=(("move_type", "in", ("in_invoice", "in_refund")),),
    required_module="account",
    requires_company_scope=True,
)

_PAYMENTS_SUMMARY = ReadPolicy(
    resource_key="payments_summary",
    odoo_model="account.payment",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="date", value_type="date", nullable=False),
        ReadFieldPolicy(name="amount", value_type="number", nullable=False),
        ReadFieldPolicy(name="payment_type", value_type="string", nullable=False, max_length=16),
        ReadFieldPolicy(name="partner_type", value_type="string", nullable=False, max_length=16),
        ReadFieldPolicy(name="partner_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="state", value_type="string", nullable=False, max_length=32),
    ),
    default_fields=(
        "id", "name", "date", "amount", "payment_type", "partner_type",
        "partner_id", "currency_id", "company_id", "state",
    ),
    allowed_filter_fields=frozenset(
        {"id", "name", "date", "payment_type", "partner_type", "state"}
    ),
    allowed_filter_operators=FINANCIAL_SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "date", "amount"}),
    required_module="account",
    requires_company_scope=True,
)

_JOURNALS_SUMMARY = ReadPolicy(
    resource_key="journals_summary",
    odoo_model="account.journal",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="code", value_type="string", nullable=False, max_length=16),
        ReadFieldPolicy(name="type", value_type="string", nullable=False, max_length=32),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="active", value_type="boolean", nullable=False),
    ),
    default_fields=("id", "name", "code", "type", "currency_id", "company_id", "active"),
    allowed_filter_fields=frozenset({"id", "name", "code", "type", "active"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "code"}),
    base_domain=(("active", "=", True),),
    required_module="account",
    requires_company_scope=True,
)

# General ledger header resource used by the operations service. Keep this
# separate from the richer employee-facing financial review resource so callers
# that only need the compact operation catalog do not gain extra fields.
_ACCOUNTING_ENTRIES = ReadPolicy(
    resource_key="accounting_entries",
    odoo_model="account.move",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="date", value_type="date", nullable=False),
        ReadFieldPolicy(name="ref", value_type="string", nullable=True, max_length=255),
        ReadFieldPolicy(
            name="state",
            value_type="string",
            nullable=False,
            max_length=16,
            pattern=r"(draft|posted|cancel)",
        ),
        ReadFieldPolicy(name="journal_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
    ),
    default_fields=("id", "name", "date", "ref", "state", "journal_id", "company_id"),
    allowed_filter_fields=frozenset({"id", "name", "date", "state"}),
    allowed_filter_operators=SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "date"}),
    base_domain=(("move_type", "=", "entry"),),
    required_module="account",
    requires_company_scope=True,
)

# Read-only general journal entries. The server-owned move_type domain prevents
# invoices and bills from being mixed into this resource. Chatter, attachments,
# invoice lines and unrestricted narration are deliberately excluded.
_JOURNAL_ENTRIES = ReadPolicy(
    resource_key="journal_entries",
    odoo_model="account.move",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=False, max_length=255),
        ReadFieldPolicy(name="date", value_type="date", nullable=False),
        ReadFieldPolicy(name="ref", value_type="string", nullable=True, max_length=255),
        ReadFieldPolicy(name="journal_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="partner_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(
            name="state",
            value_type="string",
            nullable=False,
            max_length=16,
            pattern=r"(draft|posted|cancel)",
        ),
        ReadFieldPolicy(name="amount_total_signed", value_type="number", nullable=False),
    ),
    default_fields=(
        "id",
        "name",
        "date",
        "ref",
        "journal_id",
        "partner_id",
        "currency_id",
        "company_id",
        "state",
        "amount_total_signed",
    ),
    allowed_filter_fields=frozenset({"id", "name", "date", "state", "journal_id"}),
    allowed_filter_operators=FINANCIAL_SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "name", "date", "amount_total_signed"}),
    base_domain=(("move_type", "=", "entry"),),
    required_module="account",
    requires_company_scope=True,
)

# Bounded ledger lines for one or more explicitly selected journal entries.
# Account codes/names arrive through the allowlisted many2one relation only;
# reconciliation, analytic, bank and attachment data remain inaccessible.
_JOURNAL_ITEMS = ReadPolicy(
    resource_key="journal_items",
    odoo_model="account.move.line",
    fields=_fields(
        ReadFieldPolicy(name="id", value_type="integer", nullable=False),
        ReadFieldPolicy(name="date", value_type="date", nullable=False),
        ReadFieldPolicy(name="move_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="account_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="name", value_type="string", nullable=True, max_length=255),
        ReadFieldPolicy(name="partner_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="currency_id", value_type="many2one", nullable=True),
        ReadFieldPolicy(name="company_id", value_type="many2one", nullable=False),
        ReadFieldPolicy(name="debit", value_type="number", nullable=False),
        ReadFieldPolicy(name="credit", value_type="number", nullable=False),
        ReadFieldPolicy(name="balance", value_type="number", nullable=False),
        ReadFieldPolicy(
            name="parent_state",
            value_type="string",
            nullable=False,
            max_length=16,
            pattern=r"(draft|posted|cancel)",
        ),
    ),
    default_fields=(
        "id",
        "date",
        "move_id",
        "account_id",
        "name",
        "partner_id",
        "currency_id",
        "company_id",
        "debit",
        "credit",
        "balance",
        "parent_state",
    ),
    allowed_filter_fields=frozenset(
        {"id", "date", "move_id", "account_id", "parent_state"}
    ),
    allowed_filter_operators=FINANCIAL_SAFE_OPERATORS,
    allowed_order_fields=frozenset({"id", "date", "debit", "credit", "balance"}),
    base_domain=(
        ("move_id.move_type", "=", "entry"),
        ("display_type", "=", False),
    ),
    required_module="account",
    requires_company_scope=True,
)

READ_POLICIES: dict[str, ReadPolicy] = {
    _COUNTRIES.resource_key: _COUNTRIES,
    _BENEFICIARIES_SUMMARY.resource_key: _BENEFICIARIES_SUMMARY,
    _CUSTOMERS.resource_key: _CUSTOMERS,
    _INVOICES.resource_key: _INVOICES,
    _INSTALLED_MODULES.resource_key: _INSTALLED_MODULES,
    _COMPANIES.resource_key: _COMPANIES,
    _EMPLOYEES_SUMMARY.resource_key: _EMPLOYEES_SUMMARY,
    _ATTENDANCE_SUMMARY.resource_key: _ATTENDANCE_SUMMARY,
    _LEAVES_SUMMARY.resource_key: _LEAVES_SUMMARY,
    _PAYROLL_SUMMARY.resource_key: _PAYROLL_SUMMARY,
    _DEPARTMENTS_SUMMARY.resource_key: _DEPARTMENTS_SUMMARY,
    _VENDOR_BILLS.resource_key: _VENDOR_BILLS,
    _PAYMENTS_SUMMARY.resource_key: _PAYMENTS_SUMMARY,
    _JOURNALS_SUMMARY.resource_key: _JOURNALS_SUMMARY,
    _ACCOUNTING_ENTRIES.resource_key: _ACCOUNTING_ENTRIES,
    _JOURNAL_ENTRIES.resource_key: _JOURNAL_ENTRIES,
    _JOURNAL_ITEMS.resource_key: _JOURNAL_ITEMS,
}


def get_policy(resource_key: str) -> ReadPolicy | None:
    return READ_POLICIES.get(resource_key)

@dataclass(frozen=True)
class FilterValueSpec:
    """Explicit per-field value contract for filter values.

    kind:
      - "int": positive integers only (bool explicitly rejected).
      - "str": strings only, bounded by max_length and (optionally) a
        fullmatch regex pattern.
    """

    kind: str  # "int" | "str"
    max_length: int = MAX_FILTER_STRING_LENGTH
    pattern: str | None = None
    min_value: int = 1
    max_value: int = 2_147_483_647

    def __post_init__(self):
        if self.kind not in ("int", "str"):
            raise ValueError(f"unknown filter value kind: {self.kind}")
        if self.pattern is not None:
            re.compile(self.pattern)  # fail fast on bad patterns at import
