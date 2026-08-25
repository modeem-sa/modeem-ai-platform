"""Centralized read-policy registry (Phase 2D, typed in Phase 2E).

The API caller NEVER supplies a raw Odoo model name, method name, raw
domain, order string, or field TYPE. Callers use a Modeem `resource_key`;
every model, field (with its expected value type), filter operator, and
order field is allowlisted here, server-side only.

Phase 2E ships ONLY the technical `countries` resource (res.country) to
validate the generic read infrastructure. Business resources (partners,
invoices, employees, ...) are added only after explicit approval of each
domain — do not add them here speculatively. Only the value types needed
by the current resource exist; relational/date types are added when a
real approved resource requires them.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

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

FieldValueType = Literal["integer", "string", "boolean", "number"]


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

READ_POLICIES: dict[str, ReadPolicy] = {
    _COUNTRIES.resource_key: _COUNTRIES,
    _BENEFICIARIES_SUMMARY.resource_key: _BENEFICIARIES_SUMMARY,
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
