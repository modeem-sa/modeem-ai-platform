"""Read-preview request/response schemas (Phase 2D).

The caller supplies a Modeem resource key — NEVER a raw Odoo model,
method, domain expression, or raw order string. Structural validation
lives here; policy-level validation (allowlists) lives in the reader.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.integrations.odoo.read_policies import (
    ABSOLUTE_MAX_PAGE_SIZE,
    DEFAULT_PAGE_SIZE,
    MAX_FILTER_LIST_ITEMS,
    MAX_FILTER_STRING_LENGTH,
    MAX_FILTERS,
    MAX_PREVIEW_OFFSET,
    MAX_REQUESTED_FIELDS,
)

# Only scalar filter values (or a flat list for "in"). Nested lists /
# raw domain syntax are structurally impossible.
_Scalar = str | int | bool


class ReadFilter(BaseModel):
    model_config = {"extra": "forbid"}

    field: str = Field(max_length=64)
    operator: Literal["=", "!=", "in", "ilike"]
    value: _Scalar | list[_Scalar] = Field()


class ReadPreviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    resource: str = Field(max_length=64)
    fields: list[str] | None = Field(default=None, max_length=MAX_REQUESTED_FIELDS)
    filters: list[ReadFilter] | None = Field(default=None, max_length=MAX_FILTERS)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=ABSOLUTE_MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=MAX_PREVIEW_OFFSET)
    order_by: str | None = Field(default=None, max_length=64)
    order_direction: Literal["asc", "desc"] = "asc"
    company_id: int | None = Field(default=None, ge=1)


class ReadPreviewResponse(BaseModel):
    resource: str
    fields: list[str]
    records: list[dict]
    limit: int
    offset: int
    returned_count: int
    has_more: bool
    next_offset: int | None
    transport: str


__all__ = [
    "MAX_FILTER_LIST_ITEMS",
    "MAX_FILTER_STRING_LENGTH",
    "ReadFilter",
    "ReadPreviewRequest",
    "ReadPreviewResponse",
]
