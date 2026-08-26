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
SAFE_OPERATORS = frozenset({"=", "!=", "in", "ilike"})

FieldValueType = Literal["integer", "string", "boolean", "number", "date", "many2one"]


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
)

READ_POLICIES: dict[str, ReadPolicy] = {
    _COUNTRIES.resource_key: _COUNTRIES,
    _BENEFICIARIES_SUMMARY.resource_key: _BENEFICIARIES_SUMMARY,
    _CUSTOMERS.resource_key: _CUSTOMERS,
    _INVOICES.resource_key: _INVOICES,
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
