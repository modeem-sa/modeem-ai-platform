"""Content-manager workflow and strict model-output validation."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.content_manager.provider import ContentManagerProvider, ProviderFailureError
from app.content_manager.repository import PromptRepository

BoundedOption = Annotated[str, Field(min_length=1, max_length=200)]


class UIField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    type: Literal["text", "textarea", "number", "date", "email", "select"]
    required: bool = True
    placeholder: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=500)
    options: list[BoundedOption] = Field(default_factory=list, max_length=20)


class UISuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)
    submit_label: str = Field(default="", max_length=100)
    fields: list[UIField] = Field(default_factory=list, max_length=10)
    suggestions: list[UISuggestion] = Field(default_factory=list, max_length=10)


class ModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["complete", "needs_information"]
    document: str | None = Field(default=None, max_length=30000)
    ui: UIConfig | None = None
    document_type: str | None = Field(default=None, max_length=128)
    document_action: Literal["revise_active_document", "create_new_document"] | None = None

    @model_validator(mode="after")
    def valid_state(self) -> "ModelResult":
        if self.status == "complete" and not self.document:
            raise ValueError("complete response requires a document")
        if self.status == "needs_information" and (self.ui is None or not self.ui.fields):
            raise ValueError("needs_information response requires UI fields")
        return self


class ContentManagerWorkflow:
    def __init__(
        self,
        provider: ContentManagerProvider,
        repository: PromptRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or PromptRepository()

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        signals, redirect = self.repository.scope()
        routed = str(request.get("latest_correction") or request["original_request"]).casefold()
        if any(signal.casefold() in routed for signal in signals):
            return {"status": "out_of_scope", "redirect_message": redirect}
        try:
            raw = self.provider.generate(
                system_prompt=self.repository.system_prompt(),
                user_payload=request,
            )
            result = ModelResult.model_validate(raw)
        except (ProviderFailureError, ValidationError, ValueError, TypeError) as exc:
            raise ProviderFailureError() from exc
        return result.model_dump(exclude_none=True)
