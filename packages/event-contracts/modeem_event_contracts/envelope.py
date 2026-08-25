"""Shared event envelope schema (Pydantic v2).

This is the canonical contract for all future platform events. It contains
no real beneficiary or Odoo model names — those belong to later phases.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventActor(BaseModel):
    actor_type: str
    actor_id: str | None = None


class EventEntity(BaseModel):
    entity_type: str
    entity_id: str | None = None


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_name: str
    event_version: int = 1
    occurred_at: datetime
    source: str
    tenant_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    actor: EventActor
    entity: EventEntity
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None
