import uuid
from datetime import UTC, datetime

import pytest
from modeem_event_contracts import EventActor, EventEntity, EventEnvelope
from pydantic import ValidationError


def _valid_kwargs() -> dict:
    return {
        "event_name": "example.created",
        "occurred_at": datetime.now(UTC),
        "source": "modeem-ai-api",
        "actor": EventActor(actor_type="user", actor_id="u-1"),
        "entity": EventEntity(entity_type="example", entity_id="e-1"),
        "payload": {"key": "value"},
        "correlation_id": "corr-1",
        "idempotency_key": "idem-1",
    }


def test_valid_envelope() -> None:
    envelope = EventEnvelope(**_valid_kwargs())
    assert isinstance(envelope.event_id, uuid.UUID)
    assert envelope.event_version == 1
    assert envelope.tenant_id is None
    assert envelope.payload == {"key": "value"}


def test_missing_required_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(event_name="incomplete")  # type: ignore[call-arg]


def test_tenant_id_must_be_uuid() -> None:
    kwargs = _valid_kwargs() | {"tenant_id": "not-a-uuid"}
    with pytest.raises(ValidationError):
        EventEnvelope(**kwargs)
