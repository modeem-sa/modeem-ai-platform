"""Server-owned executable envelope for an AI invoice-activity draft."""

import json
from datetime import date
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.operations.proposals import ActivityProposal, Priority, ProposalMetadata


class InvoiceActivityProposal(BaseModel):
    """The only executable shape; all Odoo identifiers are supplied by the server."""

    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["invoice_activity"] = "invoice_activity"
    company_id: int = Field(gt=0)
    invoice_id: int = Field(gt=0)
    activity_type_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=500)
    note: str = Field(min_length=1, max_length=2_000)
    date_deadline: date
    priority: Priority
    priority_reason: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: ProposalMetadata


def executable_invoice_activity_proposal(
    draft: ActivityProposal,
    *,
    company_id: int,
    invoice_id: int,
    activity_type_id: int,
) -> InvoiceActivityProposal:
    """Combine validated untrusted text with immutable server-selected targets."""
    return InvoiceActivityProposal(
        company_id=company_id,
        invoice_id=invoice_id,
        activity_type_id=activity_type_id,
        title=draft.title,
        summary=draft.summary,
        note=draft.note,
        date_deadline=draft.recommended_deadline,
        priority=draft.priority,
        priority_reason=draft.priority_reason,
        confidence=draft.confidence,
        metadata=draft.metadata,
    )


def canonical_proposal(value: InvoiceActivityProposal) -> tuple[str, str]:
    """Serialize every reviewable and executable value into the approval hash."""
    payload = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return payload, sha256(payload.encode()).hexdigest()