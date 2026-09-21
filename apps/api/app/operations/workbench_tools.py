"""Controlled, request-bound, read-only tools for the internal AI Workbench."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.orm import Session

from app.api.deps import require_odoo_module_scope, require_service_scope
from app.models import Connection, ServiceRequest, TenantMembership, User

TOOL_KEY = "finance.get_overdue_customer_invoices"
CUSTOMER_INVOICES_TOOL_KEY = "finance.get_customer_invoices"
RECEIVABLES_TOOL_KEY = "finance.get_receivables_summary"
VENDOR_BILLS_TOOL_KEY = "finance.get_vendor_bills"
RECENT_PAYMENTS_TOOL_KEY = "finance.get_recent_payments"
PAGE_SIZE = 50
MAX_TOOL_RECORDS = 200


class OverdueInvoicesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minimum_days_overdue: int = Field(default=30, ge=1, le=3650)
    max_records: int = Field(default=100, ge=1, le=MAX_TOOL_RECORDS)


class InvoiceLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    customer: str | None = Field(default=None, min_length=1, max_length=255)
    state: Literal["draft", "posted", "cancel"] | None = None
    payment_status: Literal["not_paid", "partial", "in_payment", "paid", "reversed"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    max_records: int = Field(default=100, ge=1, le=MAX_TOOL_RECORDS)

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_iso_dates(cls, value: Any) -> Any:
        return _parse_iso_date(value)


class ReceivablesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_records: int = Field(default=MAX_TOOL_RECORDS, ge=1, le=MAX_TOOL_RECORDS)


class VendorBillsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    vendor: str | None = Field(default=None, min_length=1, max_length=255)
    state: Literal["draft", "posted", "cancel"] | None = None
    payment_status: Literal["not_paid", "partial", "in_payment", "paid", "reversed"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    due_status: Literal["all", "overdue", "not_due"] = "all"
    max_records: int = Field(default=100, ge=1, le=MAX_TOOL_RECORDS)

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_iso_dates(cls, value: Any) -> Any:
        return _parse_iso_date(value)


class RecentPaymentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date_from: date | None = None
    date_to: date | None = None
    direction: Literal["all", "incoming", "outgoing"] = "all"
    max_records: int = Field(default=100, ge=1, le=MAX_TOOL_RECORDS)

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_iso_dates(cls, value: Any) -> Any:
        return _parse_iso_date(value)


def _parse_iso_date(value: Any) -> Any:
    if value is None or isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PydanticCustomError("date_type", "date must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PydanticCustomError(
            "date_format",
            "date must be an ISO date string",
        ) from exc


class AgingAmounts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    days_0_30: str
    days_31_60: str
    days_61_90: str
    over_90_days: str


class CurrencyTotal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    currency_id: int
    currency: str
    invoice_count: int
    outstanding_amount: str
    aging: AgingAmounts


class OverdueInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int
    customer_id: int
    customer: str
    invoice_number: str
    invoice_date: str | None
    due_date: str
    days_overdue: int
    currency_id: int
    currency: str
    total_amount: str
    remaining_amount: str


class OverdueInvoicesResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool_key: Literal["finance.get_overdue_customer_invoices"]
    source: Literal["Odoo"]
    as_of: str
    minimum_days_overdue: int
    complete: bool
    result_truncated: bool
    needs_narrower_filter: bool
    returned_count: int
    returned_customer_count: int
    invoices: list[OverdueInvoice]
    totals_by_currency: list[CurrencyTotal]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    description: str
    required_module: str
    required_service: str
    required_permission: str
    mode: Literal["read"]


FINANCE_TOOLS = {
    TOOL_KEY: ToolDefinition(
        key=TOOL_KEY,
        description="Read posted customer invoices overdue by a server-calculated threshold.",
        required_module="account",
        required_service="financial",
        required_permission="service_requests.workbench.finance.read",
        mode="read",
    ),
    CUSTOMER_INVOICES_TOOL_KEY: ToolDefinition(
        key=CUSTOMER_INVOICES_TOOL_KEY,
        description="Read customer invoices using bounded, approved filters.",
        required_module="account",
        required_service="financial",
        required_permission="service_requests.workbench.finance.read",
        mode="read",
    ),
    RECEIVABLES_TOOL_KEY: ToolDefinition(
        key=RECEIVABLES_TOOL_KEY,
        description="Calculate deterministic open and overdue receivables by currency.",
        required_module="account",
        required_service="financial",
        required_permission="service_requests.workbench.finance.read",
        mode="read",
    ),
    VENDOR_BILLS_TOOL_KEY: ToolDefinition(
        key=VENDOR_BILLS_TOOL_KEY,
        description="Read vendor bills using bounded, approved filters.",
        required_module="account",
        required_service="financial",
        required_permission="service_requests.workbench.finance.read",
        mode="read",
    ),
    RECENT_PAYMENTS_TOOL_KEY: ToolDefinition(
        key=RECENT_PAYMENTS_TOOL_KEY,
        description="Read recent posted payment summaries using bounded filters.",
        required_module="account",
        required_service="financial",
        required_permission="service_requests.workbench.finance.read",
        mode="read",
    ),
}


def select_finance_tool(instruction: str) -> str | None:
    """Select only a server-owned tool from natural-language intent."""
    text = " ".join(instruction.casefold().split())
    has_invoice = "invoice" in text or "فاتور" in text or "فواتير" in text
    has_overdue = (
        "overdue" in text
        or "past due" in text
        or "متأخر" in text
        or "مستحق" in text
    )
    if has_invoice and has_overdue:
        return TOOL_KEY
    if any(term in text for term in ("receivable", "accounts receivable", "ذمم", "مستحقة على العملاء", "إجمالي المبالغ")):
        return RECEIVABLES_TOOL_KEY
    if any(term in text for term in ("vendor bill", "supplier bill", "فواتير المورد", "فواتير الموردين")):
        return VENDOR_BILLS_TOOL_KEY
    if any(term in text for term in ("payment", "payments", "مدفوعات", "المدفوعات", "دفعات")):
        return RECENT_PAYMENTS_TOOL_KEY
    if has_invoice:
        return CUSTOMER_INVOICES_TOOL_KEY
    return None


def _date_range_from_instruction(
    instruction: str,
    *,
    today: date | None = None,
) -> tuple[date | None, date | None]:
    text = " ".join(instruction.casefold().split())
    current = today or datetime.now(UTC).date()
    if "last 30 days" in text or "آخر 30 يوم" in text:
        return current - timedelta(days=29), current
    if "today" in text or "اليوم" in text:
        return current, current
    if "this month" in text or "هذا الشهر" in text:
        return current.replace(day=1), current
    if "last month" in text or "الشهر الماضي" in text:
        end = current.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if "current year" in text or "this year" in text or "من بداية السنة" in text:
        return current.replace(month=1, day=1), current
    if (
        re.search(r"\b(?:yesterday|last\s+\d+\s+days?|from\s+\d{4}-\d{2}-\d{2})\b", text)
        or "أمس" in text
        or re.search(r"آخر\s+\d+\s+يوم", text)
        or re.search(r"\d{4}-\d{2}-\d{2}", text)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported date expression. Use an approved relative date phrase.",
        )
    return None, None


def _named_party(instruction: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s+(.+?)(?=\s+(?:غير|المتأخر|المسددة|unpaid|paid|from|خلال|آخر)|$)",
            instruction,
            re.IGNORECASE,
        )
        if match:
            value = " ".join(match.group(1).strip(" .،").split())
            return value or None
    return None


def finance_tool_input_from_instruction(
    instruction: str,
    tool_key: str = TOOL_KEY,
    *,
    today: date | None = None,
) -> BaseModel:
    date_from, date_to = _date_range_from_instruction(instruction, today=today)
    text = instruction.casefold()
    if tool_key == CUSTOMER_INVOICES_TOOL_KEY:
        return InvoiceLookupInput(
            customer=_named_party(instruction, ("العميل", "customer")),
            payment_status="not_paid" if "غير المسدد" in text or "unpaid" in text else None,
            date_from=date_from,
            date_to=date_to,
        )
    if tool_key == RECEIVABLES_TOOL_KEY:
        return ReceivablesInput()
    if tool_key == VENDOR_BILLS_TOOL_KEY:
        return VendorBillsInput(
            vendor=_named_party(instruction, ("المورد", "vendor", "supplier")),
            payment_status="not_paid" if "غير المسدد" in text or "unpaid" in text else None,
            date_from=date_from,
            date_to=date_to,
            due_status="overdue" if "متأخر" in text or "overdue" in text else "all",
        )
    if tool_key == RECENT_PAYMENTS_TOOL_KEY:
        direction = "incoming" if "incoming" in text or "واردة" in text else "outgoing" if "outgoing" in text or "صادرة" in text else "all"
        return RecentPaymentsInput(
            date_from=date_from,
            date_to=date_to,
            direction=direction,
        )
    match = re.search(
        r"(?<!\d)(\d{1,5})\s*\+?\s*(?:days?|يوم(?:اً|ًا|ا)?)",
        instruction.casefold(),
    )
    if match is None:
        return OverdueInvoicesInput()
    days = int(match.group(1))
    if days < 1 or days > 3650:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The overdue-day threshold must be between 1 and 3650.",
        )
    return OverdueInvoicesInput(minimum_days_overdue=days)


def require_tool_permission(
    db: Session,
    actor: User,
    request: ServiceRequest,
    permission: str,
) -> None:
    """Enforce the registry permission independently of prompt/tool selection."""
    if permission != "service_requests.workbench.finance.read":
        raise HTTPException(status_code=403, detail="Finance tool permission denied")
    if actor.is_superuser:
        return
    membership = (
        db.query(TenantMembership)
        .filter(
            TenantMembership.tenant_id == request.tenant_id,
            TenantMembership.user_id == actor.id,
            TenantMembership.is_active.is_(True),
            TenantMembership.role.in_(("owner", "admin", "manager", "member")),
        )
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Finance tool permission denied")


def _money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Odoo returned an invalid financial amount.",
        )
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Odoo returned an invalid financial amount.",
        )
    return amount


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _relation(value: Any, field: str) -> tuple[int, str]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or isinstance(value[0], bool)
        or not isinstance(value[0], int)
        or not isinstance(value[1], str)
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Odoo returned an invalid {field}.",
        )
    return value[0], value[1]


def execute_overdue_customer_invoices(
    *,
    db: Session,
    actor: User,
    request: ServiceRequest,
    connection: Connection,
    tool_input: OverdueInvoicesInput,
    read_page: Callable[..., dict[str, Any]],
    today: date | None = None,
) -> OverdueInvoicesResult:
    """Execute the fixed overdue-invoice query and deterministic calculations."""
    definition = FINANCE_TOOLS[TOOL_KEY]
    require_tool_permission(db, actor, request, definition.required_permission)
    require_service_scope(db, actor, request.tenant_id, definition.required_service)
    require_odoo_module_scope(db, actor, request.tenant_id, definition.required_module)
    if connection.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Service request not found")
    if connection.odoo_company_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Odoo connection has no configured company.",
        )

    as_of = today or datetime.now(UTC).date()
    cutoff = as_of - timedelta(days=tool_input.minimum_days_overdue)
    fixed_filters = [
        {"field": "move_type", "operator": "=", "value": "out_invoice"},
        {"field": "state", "operator": "=", "value": "posted"},
        {
            "field": "payment_state",
            "operator": "in",
            "value": ["not_paid", "partial", "in_payment"],
        },
        {"field": "invoice_date_due", "operator": "<=", "value": cutoff.isoformat()},
        {"field": "amount_residual", "operator": ">=", "value": 0.000001},
    ]
    raw_records: list[dict[str, Any]] = []
    offset = 0
    has_more = False
    while len(raw_records) < tool_input.max_records:
        limit = min(PAGE_SIZE, tool_input.max_records - len(raw_records))
        page = read_page(
            connection,
            resource="invoices",
            filters=fixed_filters,
            limit=limit,
            offset=offset,
            company_scoped=True,
            order_by="id",
            order_direction="asc",
        )
        records = page.get("records")
        if (
            not isinstance(records, list)
            or page.get("offset") != offset
            or page.get("returned_count") != len(records)
            or not isinstance(page.get("has_more"), bool)
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Odoo returned invalid pagination metadata.",
            )
        raw_records.extend(records)
        has_more = page["has_more"]
        if not has_more:
            break
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Odoo returned invalid pagination metadata.",
            )
        offset = next_offset

    truncated = has_more
    invoices: list[OverdueInvoice] = []
    totals: dict[int, dict[str, Any]] = {}
    customer_ids: set[int] = set()
    for record in raw_records:
        try:
            due_date = date.fromisoformat(record["invoice_date_due"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Odoo returned an invalid invoice due date.",
            ) from exc
        days_overdue = (as_of - due_date).days
        if days_overdue < tool_input.minimum_days_overdue:
            continue
        customer_id, customer = _relation(record.get("partner_id"), "customer")
        currency_id, currency = _relation(record.get("currency_id"), "currency")
        total_amount = _money(record.get("amount_total"))
        remaining_amount = _money(record.get("amount_residual"))
        customer_ids.add(customer_id)
        invoices.append(
            OverdueInvoice(
                id=record["id"],
                customer_id=customer_id,
                customer=customer,
                invoice_number=record["name"],
                invoice_date=record.get("invoice_date"),
                due_date=due_date.isoformat(),
                days_overdue=days_overdue,
                currency_id=currency_id,
                currency=currency,
                total_amount=_money_text(total_amount),
                remaining_amount=_money_text(remaining_amount),
            )
        )
        currency_total = totals.setdefault(
            currency_id,
            {
                "currency": currency,
                "count": 0,
                "outstanding": Decimal(0),
                "aging": [Decimal(0), Decimal(0), Decimal(0), Decimal(0)],
            },
        )
        currency_total["count"] += 1
        currency_total["outstanding"] += remaining_amount
        bucket = 0 if days_overdue <= 30 else 1 if days_overdue <= 60 else 2 if days_overdue <= 90 else 3
        currency_total["aging"][bucket] += remaining_amount

    # A partial dataset must never be presented as a complete financial total.
    totals_by_currency = []
    if not truncated:
        totals_by_currency = [
            CurrencyTotal(
                currency_id=currency_id,
                currency=value["currency"],
                invoice_count=value["count"],
                outstanding_amount=_money_text(value["outstanding"]),
                aging=AgingAmounts(
                    days_0_30=_money_text(value["aging"][0]),
                    days_31_60=_money_text(value["aging"][1]),
                    days_61_90=_money_text(value["aging"][2]),
                    over_90_days=_money_text(value["aging"][3]),
                ),
            )
            for currency_id, value in sorted(totals.items())
        ]
    return OverdueInvoicesResult(
        tool_key=TOOL_KEY,
        source="Odoo",
        as_of=as_of.isoformat(),
        minimum_days_overdue=tool_input.minimum_days_overdue,
        complete=not truncated,
        result_truncated=truncated,
        needs_narrower_filter=truncated,
        returned_count=len(invoices),
        returned_customer_count=len(customer_ids),
        invoices=invoices,
        totals_by_currency=totals_by_currency,
    )


class FinanceToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool_key: str
    source: Literal["Odoo"]
    as_of: str
    filters_used: list[dict[str, Any]]
    complete: bool
    result_truncated: bool
    needs_narrower_filter: bool
    returned_count: int
    returned_customer_count: int = 0
    invoices: list[dict[str, Any]] = Field(default_factory=list)
    bills: list[dict[str, Any]] = Field(default_factory=list)
    payments: list[dict[str, Any]] = Field(default_factory=list)
    totals_by_currency: list[dict[str, Any]] = Field(default_factory=list)


def parse_finance_tool_input(tool_key: str, value: dict[str, Any]) -> BaseModel:
    models: dict[str, type[BaseModel]] = {
        TOOL_KEY: OverdueInvoicesInput,
        CUSTOMER_INVOICES_TOOL_KEY: InvoiceLookupInput,
        RECEIVABLES_TOOL_KEY: ReceivablesInput,
        VENDOR_BILLS_TOOL_KEY: VendorBillsInput,
        RECENT_PAYMENTS_TOOL_KEY: RecentPaymentsInput,
    }
    model = models.get(tool_key)
    if model is None:
        raise HTTPException(status_code=422, detail="Unsupported finance tool")
    try:
        return model.model_validate(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid finance tool input") from exc


def _authorize_tool(
    db: Session,
    actor: User,
    request: ServiceRequest,
    connection: Connection,
    tool_key: str,
) -> None:
    definition = FINANCE_TOOLS[tool_key]
    require_tool_permission(db, actor, request, definition.required_permission)
    require_service_scope(db, actor, request.tenant_id, definition.required_service)
    require_odoo_module_scope(db, actor, request.tenant_id, definition.required_module)
    if connection.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Service request not found")
    if connection.odoo_company_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Odoo connection has no configured company.",
        )


def _read_bounded(
    *,
    connection: Connection,
    read_page: Callable[..., dict[str, Any]],
    resource: str,
    filters: list[dict[str, Any]],
    max_records: int,
) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    offset = 0
    has_more = False
    while len(records) < max_records:
        limit = min(PAGE_SIZE, max_records - len(records))
        page = read_page(
            connection,
            resource=resource,
            filters=filters,
            limit=limit,
            offset=offset,
            company_scoped=resource != "customers",
            order_by="id",
            order_direction="asc",
        )
        page_records = page.get("records")
        if (
            not isinstance(page_records, list)
            or page.get("offset") != offset
            or page.get("returned_count") != len(page_records)
            or not isinstance(page.get("has_more"), bool)
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Odoo returned invalid pagination metadata.",
            )
        records.extend(page_records)
        has_more = page["has_more"]
        if not has_more:
            break
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Odoo returned invalid pagination metadata.",
            )
        offset = next_offset
    return records, has_more


def _resolve_party(
    connection: Connection,
    read_page: Callable[..., dict[str, Any]],
    name: str,
    *,
    resource: Literal["finance_customers", "finance_vendors"],
    label: Literal["customer", "vendor"],
) -> tuple[int, str]:
    page = read_page(
        connection,
        resource=resource,
        fields=["id", "name"],
        filters=[{"field": "name", "operator": "ilike", "value": name}],
        limit=3,
        offset=0,
        company_scoped=True,
        order_by="name",
        order_direction="asc",
    )
    records = page.get("records")
    if not isinstance(records, list):
        raise HTTPException(status_code=502, detail=f"Odoo returned an invalid {label} result.")
    if not records:
        raise HTTPException(status_code=404, detail=f"No matching {label} was found.")
    if len(records) != 1 or page.get("has_more"):
        raise HTTPException(
            status_code=409,
            detail=f"Multiple similar {label}s were found. Please choose the {label}.",
        )
    record = records[0]
    if isinstance(record.get("id"), bool) or not isinstance(record.get("id"), int):
        raise HTTPException(status_code=502, detail=f"Odoo returned an invalid {label} result.")
    return record["id"], record["name"]


def _validate_dates(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The date range is invalid.")


def _invoice_result_row(record: dict[str, Any], party_label: str) -> dict[str, Any]:
    party_id, party = _relation(record.get("partner_id"), party_label)
    currency_id, currency = _relation(record.get("currency_id"), "currency")
    return {
        "id": record["id"],
        "party_id": party_id,
        "party": party,
        "number": record["name"],
        "invoice_date": record.get("invoice_date"),
        "due_date": record.get("invoice_date_due"),
        "state": record["state"],
        "payment_state": record.get("payment_state"),
        "currency_id": currency_id,
        "currency": currency,
        "total_amount": _money_text(_money(record.get("amount_total"))),
        "remaining_amount": _money_text(_money(record.get("amount_residual"))),
    }


def _currency_summaries(
    records: list[dict[str, Any]],
    *,
    as_of: date,
) -> list[dict[str, Any]]:
    totals: dict[int, dict[str, Any]] = {}
    for record in records:
        currency_id, currency = _relation(record.get("currency_id"), "currency")
        remaining = _money(record.get("amount_residual"))
        due_text = record.get("invoice_date_due")
        due = date.fromisoformat(due_text) if isinstance(due_text, str) else None
        overdue = due is not None and due < as_of
        entry = totals.setdefault(
            currency_id,
            {
                "currency_id": currency_id,
                "currency": currency,
                "open_receivables_total": Decimal(0),
                "overdue_receivables_total": Decimal(0),
                "invoice_count": 0,
                "overdue_invoice_count": 0,
                "aging": [Decimal(0), Decimal(0), Decimal(0), Decimal(0)],
            },
        )
        entry["open_receivables_total"] += remaining
        entry["invoice_count"] += 1
        if overdue and due is not None:
            days = (as_of - due).days
            entry["overdue_receivables_total"] += remaining
            entry["overdue_invoice_count"] += 1
            bucket = 0 if days <= 30 else 1 if days <= 60 else 2 if days <= 90 else 3
            entry["aging"][bucket] += remaining
    return [
        {
            **{key: value for key, value in entry.items() if key != "aging"},
            "open_receivables_total": _money_text(entry["open_receivables_total"]),
            "overdue_receivables_total": _money_text(entry["overdue_receivables_total"]),
            "aging": {
                "days_0_30": _money_text(entry["aging"][0]),
                "days_31_60": _money_text(entry["aging"][1]),
                "days_61_90": _money_text(entry["aging"][2]),
                "over_90_days": _money_text(entry["aging"][3]),
            },
        }
        for _, entry in sorted(totals.items())
    ]


def _simple_currency_summaries(
    records: list[dict[str, Any]],
    *,
    count_key: str,
    amount_field: str,
    outstanding_field: str | None = None,
) -> list[dict[str, Any]]:
    totals: dict[int, dict[str, Any]] = {}
    for record in records:
        currency_id, currency = _relation(record.get("currency_id"), "currency")
        entry = totals.setdefault(
            currency_id,
            {
                "currency_id": currency_id,
                "currency": currency,
                count_key: 0,
                "total_amount": Decimal(0),
                "outstanding_amount": Decimal(0),
            },
        )
        entry[count_key] += 1
        entry["total_amount"] += _money(record.get(amount_field))
        if outstanding_field:
            entry["outstanding_amount"] += _money(record.get(outstanding_field))
    result = []
    for _, entry in sorted(totals.items()):
        summary = {
            key: value
            for key, value in entry.items()
            if key not in {"total_amount", "outstanding_amount"}
        }
        summary["total_amount"] = _money_text(entry["total_amount"])
        if outstanding_field:
            summary["outstanding_amount"] = _money_text(entry["outstanding_amount"])
        result.append(summary)
    return result


def execute_finance_tool(
    *,
    db: Session,
    actor: User,
    request: ServiceRequest,
    connection: Connection,
    tool_key: str,
    tool_input: BaseModel,
    read_page: Callable[..., dict[str, Any]],
    today: date | None = None,
) -> BaseModel:
    if tool_key == TOOL_KEY:
        if not isinstance(tool_input, OverdueInvoicesInput):
            raise HTTPException(status_code=422, detail="Invalid finance tool input")
        return execute_overdue_customer_invoices(
            db=db,
            actor=actor,
            request=request,
            connection=connection,
            tool_input=tool_input,
            read_page=read_page,
            today=today,
        )
    if tool_key not in FINANCE_TOOLS:
        raise HTTPException(status_code=422, detail="Unsupported finance tool")
    _authorize_tool(db, actor, request, connection, tool_key)
    as_of = today or datetime.now(UTC).date()
    filters: list[dict[str, Any]] = []

    if isinstance(tool_input, InvoiceLookupInput):
        _validate_dates(tool_input.date_from, tool_input.date_to)
        filters.append({"field": "move_type", "operator": "=", "value": "out_invoice"})
        if tool_input.customer:
            customer_id, _ = _resolve_party(
                connection,
                read_page,
                tool_input.customer,
                resource="finance_customers",
                label="customer",
            )
            filters.append({"field": "partner_id", "operator": "=", "value": customer_id})
        for field, value in (
            ("state", tool_input.state),
            ("payment_state", tool_input.payment_status),
        ):
            if value:
                filters.append({"field": field, "operator": "=", "value": value})
        if tool_input.date_from:
            filters.append({"field": "invoice_date", "operator": ">=", "value": tool_input.date_from.isoformat()})
        if tool_input.date_to:
            filters.append({"field": "invoice_date", "operator": "<=", "value": tool_input.date_to.isoformat()})
        if len(filters) > 5:
            raise HTTPException(status_code=422, detail="Use fewer invoice filters.")
        records, truncated = _read_bounded(
            connection=connection,
            read_page=read_page,
            resource="invoices",
            filters=filters,
            max_records=tool_input.max_records,
        )
        rows = [_invoice_result_row(record, "customer") for record in records]
        return FinanceToolResult(
            tool_key=tool_key,
            source="Odoo",
            as_of=as_of.isoformat(),
            filters_used=filters,
            complete=not truncated,
            result_truncated=truncated,
            needs_narrower_filter=truncated,
            returned_count=len(rows),
            returned_customer_count=len({row["party_id"] for row in rows}),
            invoices=rows,
            totals_by_currency=[] if truncated else _simple_currency_summaries(
                records,
                count_key="invoice_count",
                amount_field="amount_total",
                outstanding_field="amount_residual",
            ),
        )

    if isinstance(tool_input, ReceivablesInput):
        filters = [
            {"field": "move_type", "operator": "=", "value": "out_invoice"},
            {"field": "state", "operator": "=", "value": "posted"},
            {"field": "amount_residual", "operator": ">=", "value": 0.000001},
        ]
        records, truncated = _read_bounded(
            connection=connection,
            read_page=read_page,
            resource="invoices",
            filters=filters,
            max_records=tool_input.max_records,
        )
        totals = [] if truncated else _currency_summaries(records, as_of=as_of)
        return FinanceToolResult(
            tool_key=tool_key,
            source="Odoo",
            as_of=as_of.isoformat(),
            filters_used=filters,
            complete=not truncated,
            result_truncated=truncated,
            needs_narrower_filter=truncated,
            returned_count=len(records),
            returned_customer_count=len({_relation(row.get("partner_id"), "customer")[0] for row in records}),
            totals_by_currency=totals,
        )

    if isinstance(tool_input, VendorBillsInput):
        _validate_dates(tool_input.date_from, tool_input.date_to)
        if tool_input.vendor:
            vendor_id, _ = _resolve_party(
                connection,
                read_page,
                tool_input.vendor,
                resource="finance_vendors",
                label="vendor",
            )
            filters.append({"field": "partner_id", "operator": "=", "value": vendor_id})
        for field, value in (
            ("state", tool_input.state),
            ("payment_state", tool_input.payment_status),
        ):
            if value:
                filters.append({"field": field, "operator": "=", "value": value})
        if tool_input.date_from:
            filters.append({"field": "invoice_date", "operator": ">=", "value": tool_input.date_from.isoformat()})
        if tool_input.date_to:
            filters.append({"field": "invoice_date", "operator": "<=", "value": tool_input.date_to.isoformat()})
        if tool_input.due_status == "overdue":
            filters.append({"field": "invoice_date_due", "operator": "<=", "value": (as_of - timedelta(days=1)).isoformat()})
        elif tool_input.due_status == "not_due":
            filters.append({"field": "invoice_date_due", "operator": ">=", "value": as_of.isoformat()})
        if len(filters) > 5:
            raise HTTPException(status_code=422, detail="Use fewer vendor bill filters.")
        records, truncated = _read_bounded(
            connection=connection,
            read_page=read_page,
            resource="vendor_bills",
            filters=filters,
            max_records=tool_input.max_records,
        )
        rows = [_invoice_result_row(record, "vendor") for record in records]
        return FinanceToolResult(
            tool_key=tool_key,
            source="Odoo",
            as_of=as_of.isoformat(),
            filters_used=filters,
            complete=not truncated,
            result_truncated=truncated,
            needs_narrower_filter=truncated,
            returned_count=len(rows),
            bills=rows,
            totals_by_currency=[] if truncated else _simple_currency_summaries(
                records,
                count_key="bill_count",
                amount_field="amount_total",
                outstanding_field="amount_residual",
            ),
        )

    if isinstance(tool_input, RecentPaymentsInput):
        _validate_dates(tool_input.date_from, tool_input.date_to)
        filters = [{"field": "state", "operator": "=", "value": "posted"}]
        if tool_input.date_from:
            filters.append({"field": "date", "operator": ">=", "value": tool_input.date_from.isoformat()})
        if tool_input.date_to:
            filters.append({"field": "date", "operator": "<=", "value": tool_input.date_to.isoformat()})
        if tool_input.direction != "all":
            payment_type = "inbound" if tool_input.direction == "incoming" else "outbound"
            filters.append({"field": "payment_type", "operator": "=", "value": payment_type})
        records, truncated = _read_bounded(
            connection=connection,
            read_page=read_page,
            resource="payments_summary",
            filters=filters,
            max_records=tool_input.max_records,
        )
        rows = []
        for record in records:
            currency_id, currency = _relation(record.get("currency_id"), "currency")
            partner_value = record.get("partner_id")
            partner = None
            if partner_value is not None:
                _, partner = _relation(partner_value, "payment partner")
            rows.append(
                {
                    "id": record["id"],
                    "reference": record["name"],
                    "date": record["date"],
                    "direction": record["payment_type"],
                    "partner_type": record["partner_type"],
                    "partner": partner,
                    "currency_id": currency_id,
                    "currency": currency,
                    "amount": _money_text(_money(record.get("amount"))),
                    "state": record["state"],
                }
            )
        return FinanceToolResult(
            tool_key=tool_key,
            source="Odoo",
            as_of=as_of.isoformat(),
            filters_used=filters,
            complete=not truncated,
            result_truncated=truncated,
            needs_narrower_filter=truncated,
            returned_count=len(rows),
            payments=rows,
            totals_by_currency=[] if truncated else _simple_currency_summaries(
                records,
                count_key="payment_count",
                amount_field="amount",
            ),
        )
    raise HTTPException(status_code=422, detail="Invalid finance tool input")