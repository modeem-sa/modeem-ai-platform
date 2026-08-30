"""Safe AI proposal boundary for overdue customer invoices.

This module only drafts an activity for a human to review.  It deliberately has
no Odoo client, persistence, approval, or execution capability.
"""

from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    ValidationError,
    model_validator,
)

from app.content_manager.provider import ContentManagerProvider, ProviderFailureError

PROMPT_VERSION = "overdue-activity-v1"
Priority = Literal["low", "medium", "high", "urgent"]


class OverdueInvoiceSummary(BaseModel):
    """Aggregate, tenant-bound input with no connection or invoice credentials."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    as_of_date: date
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    invoice_count: int = Field(ge=1, le=100_000)
    customers_affected: int = Field(ge=1, le=100_000)
    total_overdue: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    oldest_days_overdue: int = Field(ge=1, le=3_650)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "OverdueInvoiceSummary":
        if self.customers_affected > self.invoice_count:
            raise ValueError("customers_affected cannot exceed invoice_count")
        return self

    def provider_payload(self) -> dict[str, object]:
        """Return only the aggregate facts the model is allowed to see."""
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "currency": self.currency,
            "invoice_count": self.invoice_count,
            "customers_affected": self.customers_affected,
            "total_overdue": format(self.total_overdue, "f"),
            "oldest_days_overdue": self.oldest_days_overdue,
        }


class _ModelProposal(BaseModel):
    """Authoritative schema for untrusted provider output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=500)
    note: str = Field(min_length=1, max_length=2_000)
    deadline_offset_days: int = Field(ge=1, le=30)
    priority: Priority
    priority_reason: str = Field(min_length=1, max_length=500)
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class ProposalMetadata(BaseModel):
    """Server-owned provenance for reproducibility and audit support."""

    model_config = ConfigDict(extra="forbid", strict=True)

    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=64)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ActivityProposal(_ModelProposal):
    """Arabic-capable draft only; callers must separately review and execute it."""

    recommended_deadline: date
    metadata: ProposalMetadata


class OperationsPromptRepository:
    """Load the immutable, server-owned operations prompt."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(__file__).parents[1] / "prompts" / "operations" / "activity.md"

    def system_prompt(self) -> str:
        return self._path.read_text(encoding="utf-8").strip()


class OperationsProposalService:
    """Generate one bounded proposal without selecting or invoking Odoo actions."""

    def __init__(
        self,
        provider: ContentManagerProvider,
        repository: OperationsPromptRepository | None = None,
        model_name: str | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or OperationsPromptRepository()
        self.model_name = model_name or str(getattr(provider, "model", "unknown"))

    def propose(
        self,
        *,
        tenant_id: UUID,
        summary: OverdueInvoiceSummary,
    ) -> ActivityProposal:
        if tenant_id != summary.tenant_id:
            raise ValueError("tenant context mismatch")

        prompt = self.repository.system_prompt()
        try:
            raw: Any = self.provider.generate(
                system_prompt=prompt,
                user_payload={"overdue_invoice_summary": summary.provider_payload()},
            )
            model_proposal = _ModelProposal.model_validate(raw)
            metadata = ProposalMetadata(
                model=self.model_name,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            )
        except (ProviderFailureError, ValidationError, TypeError) as exc:
            # Project convention is to fail explicitly on provider/shape failure;
            # fabricating a financial follow-up recommendation is not safe.
            raise ProviderFailureError() from exc

        return ActivityProposal(
            **model_proposal.model_dump(),
            recommended_deadline=summary.as_of_date
            + timedelta(days=model_proposal.deadline_offset_days),
            metadata=metadata,
        )