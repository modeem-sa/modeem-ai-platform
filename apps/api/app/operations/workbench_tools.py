"""Controlled, request-bound, read-only tools for the internal AI Workbench."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import require_odoo_module_scope, require_service_scope
from app.models import Connection, ServiceRequest, TenantMembership, User

TOOL_KEY = "finance.get_overdue_customer_invoices"
PAGE_SIZE = 50
MAX_TOOL_RECORDS = 200


class OverdueInvoicesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minimum_days_overdue: int = Field(default=30, ge=1, le=3650)
    max_records: int = Field(default=100, ge=1, le=MAX_TOOL_RECORDS)


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
    )
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
    return TOOL_KEY if has_invoice and has_overdue else None


def finance_tool_input_from_instruction(instruction: str) -> OverdueInvoicesInput:
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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Odoo returned an invalid financial amount.",
        )
    return Decimal(str(value))


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