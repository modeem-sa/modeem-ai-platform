"""Contracts for the fixed customer-invoice chatter collection path."""

from contextlib import nullcontext
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api import operations as operations_api
from app.integrations.odoo import invoice_chatter_collection as chatter
from app.models import (
    CollectionMessage,
    CollectionMessageEvent,
    Connection,
    OperationTask,
)
from app.operations.collection_message import canonical_collection_message
from app.workers import operations as operations_worker
from tests.test_auth_security import TestingSession, _client, _csrf, _login


class _Provider:
    model = "must-not-be-sent"

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"content": "نرجو التكرم بمراجعة المبلغ المستحق وسداده في أقرب وقت ممكن."}


def _source_task(seed, *, tenant="tenant_a"):
    db = TestingSession()
    connection = Connection(
        tenant_id=seed[tenant],
        name=f"odoo-{tenant}",
        provider="odoo",
        base_url="https://odoo.example",
        database_name="db",
        username="service",
        odoo_company_id=7,
        encrypted_credentials=b"not-exposed",
        encryption_version=1,
        selected_transport="json2",
        last_test_status="success",
        created_by_user_id=seed["user_a"] if tenant == "tenant_a" else seed["user_b"],
    )
    db.add(connection)
    db.flush()
    task = OperationTask(
        tenant_id=seed[tenant],
        title="Overdue invoice",
        category="financial",
        priority="high",
        created_by_user_id=seed["user_a"] if tenant == "tenant_a" else seed["user_b"],
        source_type="odoo",
        source_connection_id=connection.id,
        source_record_id=42,
        source_signal="overdue_customer_invoice",
        source_snapshot_json=(
            '{"company_id":7,"currency":"SAR","due_date":"2020-04-01",'
            '"residual":"12500.50"}'
        ),
    )
    db.add(task)
    db.commit()
    result = str(task.id)
    db.close()
    return result


def _generate(seed, monkeypatch):
    provider = _Provider()
    monkeypatch.setattr(
        operations_api, "_collection_source_identity", lambda *args: ("1" * 64, 55)
    )
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client()
    _login(client, "a@example.com")
    task_id = _source_task(seed)
    response = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    return client, task_id, response.json()["collection_message"], provider


def _exact(message):
    return {
        "expected_version": 1,
        "expected_message_version": message["version"],
        "expected_draft_version": message["draft_version"],
        "expected_draft_hash": message["draft_hash"],
        "expected_source_version": message["source_version"],
        "expected_source_hash": message["source_hash"],
    }


def test_happy_path_binds_exact_copy_and_provider_sees_no_target_or_secrets(seed, monkeypatch):
    client, task_id, draft, provider = _generate(seed, monkeypatch)
    assert draft["channel"] == "odoo_customer_invoice_chatter"
    call_text = str(provider.calls[0]).lower()
    for forbidden in (
        "connection_id", "tenant_id", "invoice_id", "partner_id", "base_url",
        "password", "api_key", "account.move", "message_post",
    ):
        assert forbidden not in call_text

    submitted = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft),
        headers=_csrf(client),
    )
    assert submitted.status_code == 200
    awaiting = submitted.json()["collection_message"]
    approved = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting),
        headers=_csrf(client),
    )
    assert approved.status_code == 200
    result = approved.json()["collection_message"]
    assert result["status"] == "queued"
    assert result["approved_content"] == result["draft_content"]
    assert result["approved_hash"] == result["draft_hash"]
    assert result["approved_draft_version"] == result["draft_version"]


def test_stale_hash_version_csrf_and_tenant_isolation(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    stale = _exact(draft)
    stale["expected_draft_hash"] = "0" * 64
    assert client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=stale,
        headers=_csrf(client),
    ).status_code == 409
    assert client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft),
    ).status_code == 403
    other = _client()
    _login(other, "b@example.com")
    assert other.get(f"/api/v1/operations/tasks/{task_id}").status_code == 404


def test_generation_rejects_non_overdue_invoice_signal(seed, monkeypatch):
    provider = _Provider()
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider, "from_environment",
        staticmethod(lambda: provider),
    )
    monkeypatch.setattr(
        operations_api, "_collection_source_identity", lambda *args: ("1" * 64, 55)
    )
    task_id = _source_task(seed)
    db = TestingSession()
    task = db.query(OperationTask).filter_by(id=UUID(task_id)).one()
    task.source_signal = "some_other_odoo_signal"
    db.commit()
    db.close()
    client = _client()
    _login(client, "a@example.com")
    response = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/generate",
        json={"expected_version": 1}, headers=_csrf(client),
    )
    assert response.status_code == 409
    assert provider.calls == []


def test_generation_rejects_contact_opt_out_before_calling_provider(seed, monkeypatch):
    provider = _Provider()
    monkeypatch.setattr(
        operations_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    monkeypatch.setattr(
        operations_api,
        "_collection_source_identity",
        lambda *args: (_ for _ in ()).throw(
            chatter.CollectionMessagePolicyError(
                "customer has opted out", code="contact_opted_out"
            )
        ),
    )
    task_id = _source_task(seed)
    client = _client()
    _login(client, "a@example.com")
    response = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/generate",
        json={"expected_version": 1},
        headers=_csrf(client),
    )
    assert response.status_code == 409
    assert response.json()["detail"].endswith("contact_opted_out")
    assert provider.calls == []


def test_stale_or_drifted_source_identity_cannot_submit_or_approve(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    stale = _exact(draft)
    stale["expected_source_hash"] = "2" * 64
    assert client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=stale, headers=_csrf(client),
    ).status_code == 409
    monkeypatch.setattr(
        operations_api, "_collection_source_identity", lambda *args: ("3" * 64, 99)
    )
    assert client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft), headers=_csrf(client),
    ).status_code == 409


def test_approval_rechecks_opt_out_and_records_static_policy_result(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft),
        headers=_csrf(client),
    ).json()["collection_message"]
    monkeypatch.setattr(
        operations_api,
        "_collection_source_identity",
        lambda *args: (_ for _ in ()).throw(
            chatter.CollectionMessagePolicyError(
                "customer has opted out", code="contact_opted_out"
            )
        ),
    )
    response = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting),
        headers=_csrf(client),
    )
    assert response.status_code == 409
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "awaiting_approval"
    assert (
        db.query(CollectionMessageEvent)
        .filter_by(message_id=message.id, event="policy_checked", detail="contact_opted_out")
        .count()
        == 1
    )
    db.close()


def test_worker_is_idempotent_bounded_and_records_verified_receipt(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft), headers=_csrf(client),
    ).json()["collection_message"]
    client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting), headers=_csrf(client),
    )
    calls = []
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(operations_worker, "read_invoice_collection_target", lambda **kwargs: 55)
    monkeypatch.setattr(operations_worker, "canonical_collection_source_identity", lambda **kwargs: "1" * 64)
    monkeypatch.setattr(operations_worker, "decrypt_credentials", lambda *a, **k: {})
    monkeypatch.setattr(
        operations_worker, "resolve_auth_material",
        lambda *a, **k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(
        operations_worker, "deliver_invoice_collection_message",
        lambda **kwargs: calls.append(kwargs) or
        {"message_id": 81, "created": True, "verified": True},
    )
    assert operations_worker.run_queued_collection_messages_once() == 1
    assert operations_worker.run_queued_collection_messages_once() == 0
    assert len(calls) == 1
    assert calls[0]["invoice_id"] == 42
    assert calls[0]["company_id"] == 7
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "succeeded"
    assert message.external_message_id == 81
    assert message.verified_at is not None
    assert {"sending", "sent", "verifying", "verified", "succeeded"} <= {
        row.event for row in db.query(CollectionMessageEvent).all()
    }
    db.close()


@pytest.mark.parametrize("policy_code", ["contact_opted_out", "outside_contact_hours"])
def test_worker_rechecks_contact_policy_after_approval(
    seed, monkeypatch, policy_code
):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft),
        headers=_csrf(client),
    ).json()["collection_message"]
    client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting),
        headers=_csrf(client),
    )
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(operations_worker, "decrypt_credentials", lambda *a, **k: {})
    monkeypatch.setattr(
        operations_worker,
        "resolve_auth_material",
        lambda *a, **k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(
        operations_worker,
        "read_invoice_collection_target",
        lambda **kwargs: (_ for _ in ()).throw(
            chatter.CollectionMessagePolicyError("blocked", code=policy_code)
        ),
    )
    monkeypatch.setattr(
        operations_worker,
        "deliver_invoice_collection_message",
        lambda **kwargs: pytest.fail("blocked contact must never receive a message"),
    )
    assert operations_worker.run_queued_collection_messages_once() == 0
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "failed"
    assert message.error == policy_code
    assert (
        db.query(CollectionMessageEvent)
        .filter_by(message_id=message.id, event="policy_checked", detail=policy_code)
        .count()
        == 1
    )
    db.close()


def test_worker_source_drift_after_approval_fails_without_external_post(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft), headers=_csrf(client),
    ).json()["collection_message"]
    client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting), headers=_csrf(client),
    )
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(operations_worker, "decrypt_credentials", lambda *a, **k: {})
    monkeypatch.setattr(
        operations_worker, "resolve_auth_material",
        lambda *a, **k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(operations_worker, "read_invoice_collection_target", lambda **kwargs: 99)
    monkeypatch.setattr(operations_worker, "canonical_collection_source_identity", lambda **kwargs: "9" * 64)
    monkeypatch.setattr(
        operations_worker, "deliver_invoice_collection_message",
        lambda **kwargs: pytest.fail("source drift must not post externally"),
    )
    assert operations_worker.run_queued_collection_messages_once() == 0
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "failed"
    assert message.error == "source_identity_changed"
    db.close()


def test_worker_paid_after_approval_fails_without_external_post(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft), headers=_csrf(client),
    ).json()["collection_message"]
    client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting), headers=_csrf(client),
    )
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(operations_worker, "decrypt_credentials", lambda *a, **k: {})
    monkeypatch.setattr(
        operations_worker, "resolve_auth_material",
        lambda *a, **k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(
        operations_worker, "read_invoice_collection_target",
        lambda **kwargs: (_ for _ in ()).throw(
            chatter.CollectionMessagePolicyError("invoice has no collectible residual")
        ),
    )
    monkeypatch.setattr(
        operations_worker, "deliver_invoice_collection_message",
        lambda **kwargs: pytest.fail("paid invoice must never be posted"),
    )
    assert operations_worker.run_queued_collection_messages_once() == 0
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "queued"
    assert message.error == "delivery_failed"
    db.close()


def test_retry_limit_and_approved_copy_immutability(seed, monkeypatch):
    client, task_id, draft, _provider = _generate(seed, monkeypatch)
    awaiting = client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/submit",
        json=_exact(draft), headers=_csrf(client),
    ).json()["collection_message"]
    client.post(
        f"/api/v1/operations/tasks/{task_id}/collection-message/approve",
        json=_exact(awaiting), headers=_csrf(client),
    )
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(
        operations_worker, "decrypt_credentials",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("secret upstream detail")),
    )
    for _ in range(3):
        operations_worker.run_queued_collection_messages_once()
    db = TestingSession()
    message = db.query(CollectionMessage).filter_by(task_id=UUID(task_id)).one()
    assert message.status == "failed"
    assert message.attempt_count == 3
    assert message.error == "delivery_failed"
    message.approved_content = "نص آخر"
    with pytest.raises(ValueError, match="immutable"):
        db.commit()
    db.rollback()
    db.close()


def test_chatter_adapter_reconciles_existing_message_without_post(monkeypatch):
    content, _digest = canonical_collection_message("رسالة تحصيل آمنة", 1)
    body, _marker = chatter._body(content, "collection-marker-1")
    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(chatter, "_invoice", lambda *a, **k: 55)
    monkeypatch.setattr(chatter, "_find", lambda *a, **k: 91)
    monkeypatch.setattr(
        chatter.json2, "_post",
        lambda *a, **k: pytest.fail("idempotent reconciliation must not post"),
    )
    result = chatter.deliver_invoice_collection_message(
        base_url="https://odoo.example", database="db", transport="json2",
        login="service", secret="secret", environment="test", company_id=7,
        invoice_id=42, content=content, idempotency_marker="collection-marker-1",
        expected_partner_id=55, as_of_date=date(2026, 4, 10),
    )
    assert body
    assert result == {"message_id": 91, "created": False, "verified": True}


@pytest.mark.parametrize(
    ("partner", "now", "code"),
    [
        (
            {"id": 55, "opt_out": True, "tz": "Asia/Riyadh"},
            datetime(2026, 4, 10, 10, tzinfo=UTC),
            "contact_opted_out",
        ),
        (
            {"id": 55, "opt_out": False, "tz": "Asia/Riyadh"},
            datetime(2026, 4, 10, 3, 30, tzinfo=UTC),
            "outside_contact_hours",
        ),
    ],
)
def test_chatter_policy_uses_only_fixed_odoo_fields_and_local_time(
    monkeypatch, partner, now, code
):
    invoice = {
        "id": 42,
        "company_id": [7, "Company"],
        "move_type": "out_invoice",
        "state": "posted",
        "amount_residual": "100.00",
        "invoice_date_due": "2026-04-01",
        "commercial_partner_id": [55, "Customer"],
    }
    requested_partner_fields = []

    def search_read(*args, model, fields, **kwargs):
        if model == "account.move":
            return [invoice]
        assert model == "res.partner"
        requested_partner_fields.extend(fields)
        return [partner]

    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(chatter, "_search_read", search_read)
    with pytest.raises(chatter.CollectionMessagePolicyError) as caught:
        chatter.read_invoice_collection_target(
            base_url="https://odoo.example",
            database="db",
            transport="json2",
            login="service",
            secret="secret",
            environment="test",
            company_id=7,
            invoice_id=42,
            as_of_date=date(2026, 4, 10),
            now=now,
        )
    assert caught.value.code == code
    assert requested_partner_fields == ["id", "opt_out", "tz"]


@pytest.mark.parametrize("timezone_value", [None, False, "", 3, []])
def test_delivery_fails_closed_when_odoo_timezone_is_missing_or_invalid(
    monkeypatch, timezone_value
):
    invoice = {
        "id": 42,
        "company_id": [7, "Company"],
        "move_type": "out_invoice",
        "state": "posted",
        "amount_residual": "100.00",
        "invoice_date_due": "2026-04-01",
        "commercial_partner_id": [55, "Customer"],
    }
    partner = {"id": 55, "opt_out": False}
    if timezone_value is not None:
        partner["tz"] = timezone_value

    def search_read(*args, model, **kwargs):
        return [invoice] if model == "account.move" else [partner]

    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(chatter, "_search_read", search_read)
    monkeypatch.setattr(
        chatter.json2,
        "_post",
        lambda *a, **k: pytest.fail("invalid policy data must block message_post"),
    )
    with pytest.raises(chatter.CollectionMessagePolicyError) as caught:
        chatter.deliver_invoice_collection_message(
            base_url="https://odoo.example",
            database="db",
            transport="json2",
            login="service",
            secret="secret",
            environment="test",
            company_id=7,
            invoice_id=42,
            content="رسالة تحصيل",
            idempotency_marker="collection-marker-1",
            expected_partner_id=55,
            as_of_date=date(2026, 4, 10),
            now=datetime(2026, 4, 10, 10, tzinfo=UTC),
        )
    assert caught.value.code == "policy_unavailable"


def test_refund_is_not_an_eligible_collection_target(monkeypatch):
    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(
        chatter, "_search_read",
        lambda *a, **k: [{"id": 42, "company_id": [7, "Company"], "move_type": "out_refund",
                          "state": "posted",
                          "commercial_partner_id": [55, "Customer"]}],
    )
    with pytest.raises(chatter.CollectionMessagePolicyError):
        chatter.read_invoice_collection_target(
            base_url="https://odoo.example", database="db", transport="json2",
            login="service", secret="secret", environment="test", company_id=7, invoice_id=42,
            as_of_date=date(2026, 4, 10),
        )


@pytest.mark.parametrize("state", ["draft", "cancel"])
def test_unposted_invoice_is_not_an_eligible_collection_target(monkeypatch, state):
    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(
        chatter, "_search_read",
        lambda *a, **k: [{"id": 42, "company_id": [7, "Company"], "move_type": "out_invoice",
                          "state": state,
                          "commercial_partner_id": [55, "Customer"]}],
    )
    monkeypatch.setattr(
        chatter.json2, "_post",
        lambda *a, **k: pytest.fail("unposted invoices must never receive a message"),
    )
    with pytest.raises(chatter.CollectionMessagePolicyError):
        chatter.read_invoice_collection_target(
            base_url="https://odoo.example", database="db", transport="json2",
            login="service", secret="secret", environment="test", company_id=7, invoice_id=42,
            as_of_date=date(2026, 4, 10),
        )


@pytest.mark.parametrize(
    ("residual", "due_date"),
    [
        (0, "2026-04-01"),
        ("-1.00", "2026-04-01"),
        ("100.00", "2026-04-10"),
        ("100.00", "2026-04-11"),
        (None, "2026-04-01"),
        ("100.00", None),
    ],
)
def test_non_collectible_state_fails_before_message_post(
    monkeypatch, residual, due_date
):
    monkeypatch.setattr(chatter.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(chatter.safe_http, "build_client", lambda _env: nullcontext(object()))
    monkeypatch.setattr(
        chatter, "_search_read",
        lambda *a, **k: [{
            "id": 42,
            "company_id": [7, "Company"],
            "move_type": "out_invoice",
            "state": "posted",
            "amount_residual": residual,
            "invoice_date_due": due_date,
            "commercial_partner_id": [55, "Customer"],
        }],
    )
    monkeypatch.setattr(
        chatter.json2, "_post",
        lambda *a, **k: pytest.fail("non-collectible invoice must never be posted"),
    )
    with pytest.raises(chatter.CollectionMessagePolicyError):
        chatter.deliver_invoice_collection_message(
            base_url="https://odoo.example", database="db", transport="json2",
            login="service", secret="secret", environment="test", company_id=7,
            invoice_id=42, content="رسالة تحصيل", idempotency_marker="collection-marker-1",
            expected_partner_id=55, as_of_date=date(2026, 4, 10),
        )