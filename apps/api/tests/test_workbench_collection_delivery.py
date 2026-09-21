"""Direct worker acceptance coverage for the Phase 4D-B delivery boundary.

These tests deliberately invoke the worker rather than exercising delivery
through an HTTP request.  Every external Odoo operation is replaced with a
deterministic fake; a passing test therefore proves the local lifecycle and
its safety gates without contacting a real tenant.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.integrations.odoo import invoice_chatter_collection as chatter
from app.models import Connection, WorkbenchCollectionMessage
from app.workers import operations as worker_ops
from tests.test_auth_security import TestingSession
from tests.test_workbench_collection_messages import (
    _approve_body,
    _communication_prepare,
    _csrf,
    _invoice,
    _snapshot,
    _submit_body,
    _succeeded_action,
    _succeeded_multi_customer_action,
    _wire_read_only_snapshots,
)


def _patch_delivery_worker(monkeypatch, *, snapshots, adapter):
    """Install isolated fake credentials, Odoo reads, and adapter writes."""
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_a, **_k: {})
    monkeypatch.setattr(
        worker_ops,
        "resolve_auth_material",
        lambda *_a, **_k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(
        worker_ops,
        "read_invoice_collection_snapshot",
        lambda **kwargs: snapshots[int(kwargs["invoice_id"])].copy(),
    )
    monkeypatch.setattr(worker_ops, "deliver_invoice_collection_message", adapter)


def _queue_one(seed, monkeypatch, *, snapshots=None):
    """Build, approve, and explicitly queue one Workbench message."""
    _data, path, employee, manager, approved_action = _succeeded_action(
        seed, monkeypatch, snapshots=snapshots
    )
    prepared = _communication_prepare(employee, path, str(approved_action["id"]))
    assert prepared.status_code == 200, prepared.text
    draft = prepared.json()["messages"][0]
    submitted = employee.post(
        f"{path}/agent/communications/{draft['id']}/submit",
        json=_submit_body(draft),
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text
    awaiting = submitted.json()["message"]
    approved = manager.post(
        f"{path}/agent/communications/{draft['id']}/approve",
        json=_approve_body(awaiting),
        headers=_csrf(manager),
    )
    assert approved.status_code == 200, approved.text
    approved_message = approved.json()["message"]
    queued = manager.post(
        f"{path}/agent/communications/{draft['id']}/queue",
        json={
            "expected_message_version": approved_message["version"],
            "expected_approved_hash": approved_message["approved_hash"],
            "expected_approved_source_hash": approved_message["approved_source_hash"],
        },
        headers=_csrf(manager),
    )
    assert queued.status_code == 200, queued.text
    db = TestingSession()
    message = db.query(WorkbenchCollectionMessage).one()
    result = {
        "path": path,
        "employee": employee,
        "manager": manager,
        "message_id": message.id,
        "approved_content": message.approved_content,
        "approved_partner_id": message.approved_partner_id,
        "approved_hash": message.approved_hash,
        "approved_source_hash": message.approved_source_hash,
        "idempotency_marker": message.idempotency_marker,
        "invoice_ids": list(__import__("json").loads(message.invoice_ids_json)),
    }
    db.close()
    return result


def _message(seed_id):
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, seed_id)
    assert message is not None
    return message


def test_worker_empty_queue_is_safe(seed, monkeypatch):
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    db = TestingSession()
    db.query(WorkbenchCollectionMessage).delete()
    db.commit()
    db.close()
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0


def test_worker_delivers_exact_approved_identity_once(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    calls = []

    def adapter(**kwargs):
        calls.append(kwargs)
        return {"message_id": 801, "verified": True, "created": True}

    _patch_delivery_worker(monkeypatch, snapshots=snapshots, adapter=adapter)
    result = worker_ops.run_queued_workbench_collection_messages_once()
    if result != 1:
        debug_db = TestingSession()
        debug_message = debug_db.get(WorkbenchCollectionMessage, queued["message_id"])
        pytest.fail(
            f"worker result={result} status={debug_message.status} "
            f"error={debug_message.delivery_error_code} attempts={debug_message.attempt_count}"
        )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    assert len(calls) == 1
    assert calls[0]["content"] == queued["approved_content"]
    assert calls[0]["expected_partner_id"] == queued["approved_partner_id"]
    assert calls[0]["idempotency_marker"] == queued["idempotency_marker"]
    assert calls[0]["invoice_id"] == queued["invoice_ids"][0]
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "succeeded"
    assert message.external_message_id == 801
    assert message.delivery_anchor_invoice_id == min(queued["invoice_ids"])
    assert message.approved_hash == queued["approved_hash"]
    assert message.approved_source_hash == queued["approved_source_hash"]
    db.close()


def test_worker_grouped_customer_calls_adapter_once_and_persists_lowest_anchor(
    seed, monkeypatch
):
    records = [
        _invoice(
            invoice_id,
            due_date=datetime.now(UTC).date() - timedelta(days=days),
            residual=amount,
            customer_id=10,
            currency_id=1,
            currency="SAR",
        )
        for invoice_id, days, amount in ((3, 40, 30), (1, 41, 10), (2, 42, 20))
    ]
    _data, path, employee, approved_action = _succeeded_multi_customer_action(
        seed, monkeypatch, records
    )
    snapshots = {
        invoice_id: _snapshot(
            invoice_id,
            partner_id=10,
            residual=f"{amount:.2f}",
            overdue_days=days,
        )
        for invoice_id, days, amount in ((3, 40, 30), (1, 41, 10), (2, 42, 20))
    }
    _wire_read_only_snapshots(monkeypatch, snapshots)
    prepared = _communication_prepare(employee, path, str(approved_action["id"]))
    assert prepared.status_code == 200, prepared.text
    message = next(
        item for item in prepared.json()["messages"] if item["partner_id"] == 10
    )
    submitted = employee.post(
        f"{path}/agent/communications/{message['id']}/submit",
        json=_submit_body(message),
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text
    manager = employee  # the helper's manager is represented by the seeded client
    # Use the existing manager session created by the helper's fixture path.
    from tests.test_workbench_collection_messages import _client

    manager = _client("phase4c-multi-manager@example.com")
    approved = manager.post(
        f"{path}/agent/communications/{message['id']}/approve",
        json=_approve_body(submitted.json()["message"]),
        headers=_csrf(manager),
    )
    assert approved.status_code == 200, approved.text
    approved_message = approved.json()["message"]
    queued = manager.post(
        f"{path}/agent/communications/{message['id']}/queue",
        json={
            "expected_message_version": approved_message["version"],
            "expected_approved_hash": approved_message["approved_hash"],
            "expected_approved_source_hash": approved_message["approved_source_hash"],
        },
        headers=_csrf(manager),
    )
    assert queued.status_code == 200, queued.text
    calls = []
    _patch_delivery_worker(
        monkeypatch,
        snapshots=snapshots,
        adapter=lambda **kwargs: calls.append(kwargs)
        or {"message_id": 802, "verified": True, "created": True},
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 1
    assert len(calls) == 1
    assert calls[0]["invoice_id"] == 1
    db = TestingSession()
    stored = db.get(WorkbenchCollectionMessage, UUID(message["id"]))
    assert stored.delivery_anchor_invoice_id == 1
    assert stored.attempt_count == 1
    db.close()


@pytest.mark.parametrize(
    "drift",
    [
        {"state": "cancel"},
        {"residual": "0.00"},
        {"partner_id": 99},
        {"currency": "USD"},
        {"reference": "INV/CHANGED"},
        {"due_date": "2099-01-01"},
        {"company_id": 99},
    ],
)
def test_any_grouped_invoice_drift_sends_zero_and_fails_closed(
    seed, monkeypatch, drift
):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    live = {1: {**snapshots[1], **drift}}
    calls = []
    _patch_delivery_worker(
        monkeypatch,
        snapshots=live,
        adapter=lambda **kwargs: calls.append(kwargs),
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    assert calls == []
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "failed"
    assert message.delivery_error_code == "source_changed_requires_reapproval"
    db.close()


@pytest.mark.parametrize("code", ["contact_opted_out", "policy_unavailable"])
def test_preflight_policy_blocks_without_adapter_call(seed, monkeypatch, code):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)

    def blocked(**_kwargs):
        raise chatter.CollectionMessagePolicyError("blocked", code=code)

    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_a, **_k: {})
    monkeypatch.setattr(
        worker_ops,
        "resolve_auth_material",
        lambda *_a, **_k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(worker_ops, "read_invoice_collection_snapshot", blocked)
    monkeypatch.setattr(
        worker_ops,
        "deliver_invoice_collection_message",
        lambda **_kwargs: pytest.fail("policy-blocked message must not be sent"),
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "failed"
    assert message.delivery_error_code == code
    db.close()


def test_outside_hours_is_deferred_without_attempt_burn_or_immediate_rerun(
    seed, monkeypatch
):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)

    def blocked(**_kwargs):
        raise chatter.CollectionMessagePolicyError(
            "outside", code="outside_contact_hours"
        )

    _patch_delivery_worker(monkeypatch, snapshots=snapshots, adapter=blocked)
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "queued"
    assert message.attempt_count == 0
    assert message.next_attempt_at.replace(tzinfo=UTC) > datetime.now(UTC)
    db.close()
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0


@pytest.mark.parametrize("receipt", [{}, {"verified": False, "message_id": 11}, {"verified": True}])
def test_unverified_or_invalid_adapter_receipt_never_succeeds(seed, monkeypatch, receipt):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    _patch_delivery_worker(
        monkeypatch, snapshots=snapshots, adapter=lambda **_kwargs: receipt
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status != "succeeded"
    assert message.external_message_id is None
    db.close()


def test_transient_delivery_failure_is_bounded_at_three(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    calls = []

    def transient(**_kwargs):
        calls.append(_kwargs)
        raise worker_ops.ConnectorError("connection_timeout", "temporary")

    _patch_delivery_worker(monkeypatch, snapshots=snapshots, adapter=transient)
    for _ in range(4):
        db = TestingSession()
        message = db.get(WorkbenchCollectionMessage, queued["message_id"])
        message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        db.close()
        worker_ops.run_queued_workbench_collection_messages_once()
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert len(calls) == 3
    assert message.attempt_count == 3
    assert message.status == "failed"
    db.close()


def test_retryable_failure_reuses_marker_and_succeeds_before_limit(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    calls = []
    outcomes = iter(
        [
            worker_ops.ConnectorError("connection_timeout", "temporary"),
            {"message_id": 804, "verified": True, "created": True},
        ]
    )

    def adapter(**kwargs):
        calls.append(kwargs)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    _patch_delivery_worker(monkeypatch, snapshots=snapshots, adapter=adapter)
    worker_ops.run_queued_workbench_collection_messages_once()
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.close()
    assert worker_ops.run_queued_workbench_collection_messages_once() == 1
    assert len(calls) == 2
    assert {call["idempotency_marker"] for call in calls} == {
        queued["idempotency_marker"]
    }
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "succeeded"
    assert message.attempt_count == 2
    db.close()


def test_preflight_connector_failures_are_bounded_at_three(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    reads = []

    def transient_read(**_kwargs):
        reads.append(True)
        raise worker_ops.ConnectorError("connection_timeout", "temporary")

    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_a, **_k: {})
    monkeypatch.setattr(
        worker_ops,
        "resolve_auth_material",
        lambda *_a, **_k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(worker_ops, "read_invoice_collection_snapshot", transient_read)
    monkeypatch.setattr(
        worker_ops,
        "deliver_invoice_collection_message",
        lambda **_kwargs: pytest.fail("preflight failure must prevent delivery"),
    )
    for _ in range(4):
        db = TestingSession()
        message = db.get(WorkbenchCollectionMessage, queued["message_id"])
        message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        db.close()
        worker_ops.run_queued_workbench_collection_messages_once()
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert len(reads) == 3
    assert message.attempt_count == 3
    assert message.status == "failed"
    db.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_active", False),
        ("status", "disabled"),
        ("last_test_status", "failed"),
        ("selected_transport", "unsupported"),
        ("encrypted_credentials", None),
        ("encryption_version", None),
        ("odoo_company_id", 999),
    ],
)
def test_connection_identity_or_readiness_mismatch_never_calls_adapter(
    seed, monkeypatch, field, value
):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    connection = db.get(Connection, message.connection_id)
    setattr(connection, field, value)
    db.commit()
    db.close()
    calls = []
    _patch_delivery_worker(
        monkeypatch,
        snapshots=snapshots,
        adapter=lambda **kwargs: calls.append(kwargs),
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    assert calls == []


def test_attempt_three_stale_claim_reconciles_existing_result(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    message.status = "sending"
    message.attempt_count = 3
    message.claim_token = "expired-worker"
    message.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    db.close()
    calls = []
    _patch_delivery_worker(
        monkeypatch,
        snapshots=snapshots,
        adapter=lambda **kwargs: calls.append(kwargs)
        or {"message_id": 805, "verified": True, "created": False},
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 1
    assert len(calls) == 1
    assert calls[0]["idempotency_marker"] == queued["idempotency_marker"]
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.status == "succeeded"
    assert message.attempt_count == 3
    db.close()


def test_stale_owner_exception_cannot_overwrite_replacement_claim(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)

    def stale_owner_adapter(**_kwargs):
        db = TestingSession()
        replacement = db.get(WorkbenchCollectionMessage, queued["message_id"])
        replacement.claim_token = "replacement-worker"
        replacement.status = "sending"
        db.commit()
        db.close()
        raise worker_ops.ConnectorError("connection_timeout", "temporary")

    _patch_delivery_worker(
        monkeypatch, snapshots=snapshots, adapter=stale_owner_adapter
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.claim_token == "replacement-worker"
    assert message.status == "sending"
    db.close()


def test_stale_owner_success_cannot_overwrite_replacement_claim(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)

    def stale_owner_adapter(**_kwargs):
        db = TestingSession()
        replacement = db.get(WorkbenchCollectionMessage, queued["message_id"])
        replacement.claim_token = "replacement-worker-success"
        replacement.status = "sending"
        db.commit()
        db.close()
        return {"message_id": 806, "verified": True, "created": True}

    _patch_delivery_worker(
        monkeypatch, snapshots=snapshots, adapter=stale_owner_adapter
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 0
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert message.claim_token == "replacement-worker-success"
    assert message.status == "sending"
    assert message.external_message_id is None
    db.close()


def test_approved_identity_remains_immutable_through_delivery(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    original = (
        queued["approved_content"],
        queued["approved_hash"],
        queued["approved_source_hash"],
        queued["approved_partner_id"],
    )
    _patch_delivery_worker(
        monkeypatch,
        snapshots=snapshots,
        adapter=lambda **_kwargs: {
            "message_id": 803,
            "verified": True,
            "created": True,
        },
    )
    assert worker_ops.run_queued_workbench_collection_messages_once() == 1
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    assert (
        message.approved_content,
        message.approved_hash,
        message.approved_source_hash,
        message.approved_partner_id,
    ) == original
    db.close()


def test_queue_and_retry_handlers_never_call_adapter(seed, monkeypatch):
    snapshots = {1: _snapshot(1)}
    queued = _queue_one(seed, monkeypatch, snapshots=snapshots)
    calls = []
    monkeypatch.setattr(
        chatter,
        "deliver_invoice_collection_message",
        lambda **kwargs: calls.append(kwargs),
    )
    db = TestingSession()
    message = db.get(WorkbenchCollectionMessage, queued["message_id"])
    message.status = "failed"
    message.delivery_error_code = "source_changed_requires_reapproval"
    message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.close()
    # A non-retryable failure cannot be requeued through the API.
    response = queued["manager"].post(
        f"{queued['path']}/agent/communications/{queued['message_id']}/retry",
        json={
            "expected_message_version": message.version + 1,
            "expected_approved_hash": queued["approved_hash"],
            "expected_approved_source_hash": queued["approved_source_hash"],
        },
        headers=_csrf(queued["manager"]),
    )
    assert response.status_code == 409
    assert calls == []