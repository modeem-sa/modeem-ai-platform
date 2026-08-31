"""Structured, tenant-bound AI assistance for bounded Odoo read results."""

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, ValidationError

from app.content_manager.provider import ContentManagerProvider, ProviderFailureError

AssistantLocale = Literal["ar", "en"]
AutomationMode = Literal["automatic", "approval_required", "manual"]
WorkflowKey = Literal[
    "monitor_records",
    "prepare_follow_up",
    "prepare_invoice_activity",
    "prepare_collection_draft",
    "human_review",
]

PROMPT_VERSION = "finance-assistant-v1"
_MAX_RECORDS = 50
_MAX_FIELDS = 30
_MAX_TEXT_LENGTH = 500
_SECRET_FIELD_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "credential",
    "api_key",
    "authorization",
)


class AssistantFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=160)
    evidence: str = Field(min_length=1, max_length=500)
    severity: Literal["info", "attention", "risk"]


class AutomationOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    workflow_key: WorkflowKey
    title: str = Field(min_length=1, max_length=160)
    mode: AutomationMode
    reason: str = Field(min_length=1, max_length=500)


class _AssistantModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1_200)
    findings: list[AssistantFinding] = Field(max_length=8)
    automation_opportunities: list[AutomationOpportunity] = Field(max_length=5)
    next_step: str = Field(min_length=1, max_length=500)
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class FinanceAssistantResult(_AssistantModelResult):
    service: str = Field(min_length=1, max_length=64)
    locale: AssistantLocale
    analyzed_count: int = Field(ge=0, le=_MAX_RECORDS)
    prompt_version: str = Field(min_length=1, max_length=64)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=200)


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key)[:64]: _safe_value(item)
            for key, item in list(value.items())[:20]
            if not any(fragment in str(key).lower() for fragment in _SECRET_FIELD_FRAGMENTS)
        }
    return str(value)[:_MAX_TEXT_LENGTH]


def sanitized_records(records: object) -> list[dict[str, Any]]:
    """Keep only bounded JSON-like Odoo facts and drop secret-looking fields."""
    if not isinstance(records, list):
        raise TypeError("records must be a list")
    safe: list[dict[str, Any]] = []
    for record in records[:_MAX_RECORDS]:
        if not isinstance(record, dict):
            raise TypeError("record must be an object")
        safe.append(
            {
                str(key)[:64]: _safe_value(value)
                for key, value in list(record.items())[:_MAX_FIELDS]
                if not any(
                    fragment in str(key).lower()
                    for fragment in _SECRET_FIELD_FRAGMENTS
                )
            }
        )
    return safe


class FinanceAssistantService:
    """Explain Odoo facts and classify safe automation opportunities."""

    def __init__(
        self,
        provider: ContentManagerProvider,
        prompt_path: Path | None = None,
    ) -> None:
        self.provider = provider
        self.prompt_path = (
            prompt_path
            or Path(__file__).parents[1] / "prompts" / "operations" / "finance_assistant.md"
        )
        self.model_name = str(getattr(provider, "model", "unknown"))

    def analyze(
        self,
        *,
        service: str,
        locale: AssistantLocale,
        records: object,
    ) -> FinanceAssistantResult:
        safe_records = sanitized_records(records)
        prompt = self.prompt_path.read_text(encoding="utf-8").strip()
        try:
            raw = self.provider.generate(
                system_prompt=prompt,
                user_payload={
                    "service": service,
                    "response_language": "Arabic" if locale == "ar" else "English",
                    "records": safe_records,
                },
            )
            parsed = _AssistantModelResult.model_validate(raw)
        except (ProviderFailureError, ValidationError, TypeError) as exc:
            raise ProviderFailureError() from exc
        return FinanceAssistantResult(
            **parsed.model_dump(),
            service=service,
            locale=locale,
            analyzed_count=len(safe_records),
            prompt_version=PROMPT_VERSION,
            prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            model=self.model_name,
        )