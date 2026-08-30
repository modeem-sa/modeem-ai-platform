"""Focused contract tests for bounded overdue-invoice AI proposals."""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.api import operations as operations_api
from app.content_manager.provider import ProviderFailureError
from app.models import AuditLog, OperationTask
from app.operations.ai_proposal import InvoiceActivityProposal, canonical_proposal
from app.operations.proposals import OperationsProposalService, OverdueInvoiceSummary
from tests.test_auth_security import TestingSession, _client, _csrf, _login


class FakeProvider:
    model = "test-model"

    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(kwargs)
        return self.result


def _summary(**changes: object) -> OverdueInvoiceSummary:
    values: dict[str, object] = {
        "tenant_id": uuid4(),
        "as_of_date": date(2026, 4, 10),
        "currency": "SAR",
        "invoice_count": 8,
        "customers_affected": 5,
        "total_overdue": Decimal("12500.50"),
        "oldest_days_overdue": 47,
    }
    values.update(changes)
    return OverdueInvoiceSummary(**values)


def _valid_result() -> dict[str, object]:
    return {
        "title": "متابعة الفواتير المتأخرة",
        "summary": "متابعة ثماني فواتير مستحقة.",
        "note": "راجع حالة التحصيل وتواصل مع العملاء وفق الإجراءات المعتمدة.",
        "deadline_offset_days": 3,
        "priority": "high",
        "priority_reason": "أقدم فاتورة متأخرة منذ 47 يومًا.",
        "confidence": 0.91,
    }


def test_valid_arabic_proposal_has_server_owned_date_and_metadata():
    summary = _summary()
    provider = FakeProvider(_valid_result())

    proposal = OperationsProposalService(provider).propose(
        tenant_id=summary.tenant_id,
        summary=summary,
    )

    assert proposal.title.startswith("متابعة")
    assert proposal.recommended_deadline == date(2026, 4, 13)
    assert proposal.metadata.model == "test-model"
    assert proposal.metadata.prompt_version == "overdue-activity-v1"
    assert len(proposal.metadata.prompt_sha256) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"priority": "critical"},
        {"confidence": "0.9"},
        {"deadline_offset_days": 31},
        {"odoo_model": "account.move"},
    ],
)
def test_malformed_or_capability_bearing_provider_output_fails_explicitly(change):
    raw = _valid_result()
    raw.update(change)
    summary = _summary()

    with pytest.raises(ProviderFailureError):
        OperationsProposalService(FakeProvider(raw)).propose(
            tenant_id=summary.tenant_id,
            summary=summary,
        )


def test_prompt_payload_is_aggregate_bounded_and_omits_tenant_and_action_choices():
    summary = _summary()
    provider = FakeProvider(_valid_result())
    OperationsProposalService(provider).propose(tenant_id=summary.tenant_id, summary=summary)

    call = provider.calls[0]
    payload = call["user_payload"]
    assert isinstance(payload, dict)
    aggregate = payload["overdue_invoice_summary"]
    assert set(aggregate) == {
        "as_of_date",
        "currency",
        "invoice_count",
        "customers_affected",
        "total_overdue",
        "oldest_days_overdue",
    }
    assert "tenant" not in str(payload).lower()
    prompt = str(call["system_prompt"]).lower()
    for forbidden_choice in ("odoo model", "odoo method", "approval", "executed"):
        assert forbidden_choice in prompt


@pytest.mark.parametrize(
    "secret_field",
    ["connection_id", "api_key", "password", "access_token", "base_url"],
)
def test_input_schema_forbids_secret_bearing_connector_fields(secret_field):
    values = _summary().model_dump()
    values[secret_field] = "must-not-pass"
    with pytest.raises(ValueError):
        OverdueInvoiceSummary(**values)


def test_tenant_context_mismatch_fails_before_provider_call():
    summary = _summary()
    provider = FakeProvider(_valid_result())
    with pytest.raises(ValueError, match="tenant context mismatch"):
        OperationsProposalService(provider).propose(tenant_id=uuid4(), summary=summary)
    assert provider.calls == []


def _invoice_source_task(seed) -> str:
    db = TestingSession()
    task = OperationTask(
        tenant_id=seed["tenant_a"],
        title="Overdue invoice",
        category="financial",
        priority="high",
        created_by_user_id=seed["user_a"],
        source_type="odoo",
        source_record_id=42,
        source_signal="overdue_customer_invoice",
        source_snapshot_json=(
            '{"activity_type_id":3,"company_id":7,"currency":"SAR",'
            '"due_date":"2020-04-01","residual":"12500.50"}'
        ),
    )
    db.add(task)
    db.commit()
    task_id = str(task.id)
    db.close()
    return task_id


def test_generation_endpoint_calls_provider_and_hash_binds_draft_and_fixed_ids(seed, monkeypatch):
    provider = FakeProvider(_valid_result())
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client()
    _login(client, "a@example.com")
    response = client.post(
        f"/api/v1/operations/tasks/{_invoice_source_task(seed)}/action/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    assert len(provider.calls) == 1
    action = response.json()["action"]
    proposal = action["proposal"]
    assert proposal["company_id"] == 7
    assert proposal["invoice_id"] == 42
    assert proposal["activity_type_id"] == 3
    assert proposal["title"] == _valid_result()["title"]
    validated = InvoiceActivityProposal.model_validate_json(json.dumps(proposal))
    assert canonical_proposal(validated)[1] == action["proposal_hash"]
    changed_ai = validated.model_copy(update={"title": "عنوان مختلف"})
    changed_target = validated.model_copy(update={"invoice_id": 43})
    assert canonical_proposal(changed_ai)[1] != action["proposal_hash"]
    assert canonical_proposal(changed_target)[1] != action["proposal_hash"]


def test_generation_endpoint_rejects_malformed_provider_output_and_audits_safely(seed, monkeypatch):
    provider = FakeProvider({"title": "غير مكتمل"})
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client()
    _login(client, "a@example.com")
    task_id = _invoice_source_task(seed)
    response = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "Operations proposal provider failed"}
    db = TestingSession()
    audit = (
        db.query(AuditLog)
        .filter_by(action="operation_action.generation_failed", resource_id=task_id)
        .one()
    )
    assert audit.metadata_json == {"status": "failed", "error_category": "provider_failure"}
    db.close()


def test_submitted_action_cannot_be_regenerated(seed, monkeypatch):
    provider = FakeProvider(_valid_result())
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client()
    _login(client, "a@example.com")
    task_id = _invoice_source_task(seed)
    generated = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert generated.status_code == 200
    submitted = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/submit",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert submitted.status_code == 200

    forbidden = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert forbidden.status_code == 409
    assert len(provider.calls) == 1


def test_failed_action_retry_preserves_approved_identity(seed, monkeypatch):
    from app.models import OperationAction

    provider = FakeProvider(_valid_result())
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client()
    _login(client, "a@example.com")
    task_id = _invoice_source_task(seed)
    generated = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    ).json()
    client.post(
        f"/api/v1/operations/tasks/{task_id}/action/submit",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    approved = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/approve",
        json={
            "expected_version": 1,
            "expected_action_version": 2,
            "expected_proposal_hash": generated["action"]["proposal_hash"],
        },
        headers=_csrf(client),
    ).json()

    db = TestingSession()
    action_id = UUID(approved["action"]["id"])
    action = db.query(OperationAction).filter_by(id=action_id).one()
    action.status = "failed"
    action.error = "external_execution_failed"
    action.version += 1
    db.commit()
    before = (action.proposal_json, action.proposal_hash, action.idempotency_marker)
    failed_version = action.version
    db.close()

    retried = client.post(
        f"/api/v1/operations/tasks/{task_id}/action/retry",
        json={
            "expected_version": 1,
            "expected_action_version": failed_version,
            "expected_proposal_hash": before[1],
        },
        headers=_csrf(client),
    )
    assert retried.status_code == 200
    db = TestingSession()
    action = db.query(OperationAction).filter_by(id=action_id).one()
    assert action.status == "queued"
    assert (action.proposal_json, action.proposal_hash, action.idempotency_marker) == before
    db.close()