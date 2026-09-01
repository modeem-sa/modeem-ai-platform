"""Bounded AI draft contract for one fixed invoice-chatter collection message."""

import json
import unicodedata
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.content_manager.provider import ContentManagerProvider, ProviderFailureError
from app.operations.proposals import OverdueInvoiceSummary


class CollectionMessageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def safe_arabic_text(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if not value or not any("\u0600" <= char <= "\u06ff" for char in value):
            raise ValueError("collection message must contain Arabic text")
        if any(ord(char) < 32 and char not in ("\n", "\t") for char in value):
            raise ValueError("collection message contains control characters")
        return value


def canonical_collection_message(content: str, draft_version: int) -> tuple[str, str]:
    """Bind the exact normalized content and reviewed draft version."""
    draft = CollectionMessageDraft(content=content)
    payload = json.dumps(
        {"content": draft.content, "draft_version": draft_version},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return draft.content, sha256(payload.encode("utf-8")).hexdigest()


def canonical_collection_source_identity(
    *,
    connection_id: str,
    company_id: int,
    invoice_id: int,
    partner_id: int,
    source_version: int,
    source_snapshot: dict[str, object],
) -> str:
    """Opaque approval identity for a server-read invoice target and recipient."""
    if source_version < 1:
        raise ValueError("source version is invalid")
    payload = json.dumps(
        {
            "connection_id": connection_id,
            "company_id": company_id,
            "invoice_id": invoice_id,
            "partner_id": partner_id,
            "source_version": source_version,
            # A sync changing the trusted server snapshot invalidates stale approval.
            "source_snapshot_sha256": sha256(
                json.dumps(source_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class CollectionMessageProposalService:
    """Allow the model to propose text only from non-identifying aggregate facts."""

    def __init__(self, provider: ContentManagerProvider) -> None:
        self.provider = provider

    def propose(self, summary: OverdueInvoiceSummary) -> CollectionMessageDraft:
        prompt = (
            "اكتب رسالة تحصيل عربية مهذبة ومهنية من 1 إلى 1000 حرف. "
            "أعد JSON بالمفتاح content فقط. لا تذكر اسماً أو رقم فاتورة أو بيانات اتصال. "
            "لا تختر مستأجراً أو مستلماً أو قناة أو نموذج أو طريقة Odoo، ولا تطلب أسراراً."
        )
        try:
            raw: Any = self.provider.generate(
                system_prompt=prompt,
                user_payload={"overdue_invoice_summary": summary.provider_payload()},
            )
            return CollectionMessageDraft.model_validate(raw)
        except (ProviderFailureError, ValidationError, TypeError) as exc:
            raise ProviderFailureError() from exc


def rules_based_collection_message(
    summary: OverdueInvoiceSummary,
) -> CollectionMessageDraft:
    """Prepare non-identifying Arabic text when no model provider is configured."""
    return CollectionMessageDraft(
        content=(
            "نرجو التكرم بمراجعة المبلغ المستحق وسداده في أقرب وقت ممكن. "
            f"مر على تاريخ الاستحقاق {summary.oldest_days_overdue} يومًا. "
            "إذا تم السداد بالفعل، يرجى تجاهل هذه الرسالة والتواصل معنا عند الحاجة."
        )
    )