"""Direct Phase 4B execution safety tests.

These tests stay below the HTTP layer so the bounded external-call contract is
asserted without depending on a real Odoo server.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.api import workbench as workbench_api
from app.core.security import hash_password
from app.integrations.odoo import activity_writer
from app.models import (
    AuditLog,
    OperationAction,
    OperationActionExecutionItem,
    OperationActionHistory,
    TenantMembership,
    User,
)
from app.operations.workbench_actions import (
    CollectionProposal,
    canonical_collection_proposal,
)
from app.workers import operations as worker_ops
from tests.test_auth_security import PASSWORD, TestingSession
from tests.test_request_workbench import (
    _client,
    _csrf,
    _enable_finance_connection,
    _fixture,
    _invoice,
    _single_page,
)


def _target(invoice_id: int, amount: str = "10.00") -> dict:
    return {
        "invoice_id": invoice_id,
        "customer_id": 7,
        "currency_id": 1,
        "remaining_amount": amount,
    }


def _row(invoice_id: int, amount) -> dict:
    today = datetime.now(UTC).date()
    return {
        "id": invoice_id,
        "company_id": [3, "Company"],
        "partner_id": [7, "Customer"],
        "currency_id": [1, "USD"],
        "amount_residual": amount,
        "invoice_date_due": (today - timedelta(days=1)).isoformat(),
        "state": "posted",
        "payment_state": "partial",
    }


def test_preflight_reads_full_bounded_set_and_normalizes_numeric_residual(monkeypatch):
    targets = [_target(1, "10.00"), _target(2, "20.10"), _target(3, "30")]
    seen = {}

    def read(*_args, **kwargs):
        seen.update(kwargs)
        return [_row(1, 10.0), _row(2, Decimal("20.10")), _row(3, "30.00")]

    monkeypatch.setattr(activity_writer.json2, "search_read", read)
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(activity_writer.safe_http, "build_client", lambda *_: _Client())
    assert activity_writer.preflight_invoice_collection_targets(
        base_url="https://odoo.example",
        database="db",
        transport="json2",
        login="user",
        secret="secret",
        environment="test",
        company_id=3,
        targets=targets,
        execution_date=datetime.now(UTC).date().isoformat(),
    )
    assert seen["limit"] == 200


def test_preflight_rejects_incomplete_set_and_every_stale_identity(monkeypatch):
    targets = [_target(1), _target(2), _target(3)]
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *a, **k: None)
    monkeypatch.setattr(activity_writer.safe_http, "build_client", lambda *_: _Client())

    monkeypatch.setattr(activity_writer, "_search_read", lambda *_a, **_k: [_row(1, "10")])
    assert not activity_writer.preflight_invoice_collection_targets(
        base_url="https://odoo.example", database=None, transport="json2",
        login="u", secret="s", environment="test", company_id=3,
        targets=targets, execution_date=datetime.now(UTC).date().isoformat(),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payment_state", "paid"),
        ("amount_residual", "9.99"),
        ("state", "cancelled"),
        ("partner_id", [99, "Other"]),
        ("currency_id", [2, "EUR"]),
        ("company_id", [4, "Other company"]),
        ("invoice_date_due", "2999-01-01"),
    ],
)
def test_preflight_rejects_each_stale_invoice_identity_without_writing(
    monkeypatch, field, value
):
    """Every preflight outcome is a hard stop before the writer is reachable."""
    targets = [_target(1), _target(2)]
    rows = [_row(1, "10"), _row(2, "10")]
    rows[0][field] = value
    monkeypatch.setattr(activity_writer, "_search_read", lambda *_a, **_k: rows)
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *_a, **_k: None)
    monkeypatch.setattr(activity_writer.safe_http, "build_client", lambda *_a: _Client())
    writer = pytest.MonkeyPatch()
    writer.setattr(activity_writer, "_create_one_activity", lambda *_a, **_k: pytest.fail("write"))
    assert not activity_writer.preflight_invoice_collection_targets(
        base_url="https://odoo.example", database="db", transport="json2",
        login="u", secret="s", environment="test", company_id=3,
        targets=targets, execution_date=datetime.now(UTC).date().isoformat(),
    )
    writer.undo()


def test_preflight_rejects_one_stale_invoice_even_when_other_targets_are_fresh(monkeypatch):
    targets = [_target(1), _target(2), _target(3)]
    rows = [_row(1, "10"), _row(2, "20"), _row(3, "30")]
    rows[1]["amount_residual"] = "19.00"
    monkeypatch.setattr(activity_writer, "_search_read", lambda *_a, **_k: rows)
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *_a, **_k: None)
    assert not activity_writer.preflight_invoice_collection_targets(
        base_url="https://odoo.example", database=None, transport="json2",
        login="u", secret="s", environment="test", company_id=3,
        targets=targets, execution_date=datetime.now(UTC).date().isoformat(),
    )


def test_writer_rejects_invalid_server_owned_fields_before_any_odoo_call(monkeypatch):
    calls = []
    monkeypatch.setattr(activity_writer, "_invoice_model_preconditions",
                        lambda *_a, **_k: calls.append("precondition"))
    common = {
        "base_url": "https://odoo.example", "database": "db", "transport": "json2",
        "login": "u", "secret": "s", "environment": "test", "company_id": 3,
        "invoice_id": 1, "activity_type_id": 4, "summary": "Collection follow-up",
        "date_deadline": "2999-01-01", "idempotency_marker": "bad marker",
    }
    with pytest.raises(activity_writer.ActivityWritePolicyError):
        activity_writer.create_invoice_activity(**common)
    assert calls == []
    with pytest.raises(activity_writer.ActivityWritePolicyError):
        activity_writer.create_invoice_activity(
            **{**common, "idempotency_marker": "marker-12345678", "company_id": "3"}
        )
    assert calls == []


def test_writer_emits_exact_fixed_activity_values_and_reconciles(monkeypatch):
    seen = []
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *_a, **_k: None)
    monkeypatch.setattr(activity_writer.safe_http, "build_client", lambda *_a: _Client())
    monkeypatch.setattr(activity_writer, "_invoice_model_preconditions", lambda *_a, **_k: 88)
    monkeypatch.setattr(
        activity_writer,
        "_search_read",
        lambda _client, **kwargs: (
            [{"id": 4}] if kwargs["model"] == "mail.activity.type"
            else [] if kwargs["model"] == "mail.activity"
            else [{"id": 88, "model": "account.move"}]
            if kwargs["model"] == "ir.model"
            else [{"id": 1, "company_id": [3, "Company"], "move_type": "out_invoice"}]
        ),
    )
    monkeypatch.setattr(
        activity_writer,
        "_create_one_activity",
        lambda _client, **kwargs: seen.append(kwargs["values"]) or 712,
    )
    # The final reconciliation must observe the activity just created.
    reads = {"count": 0}
    original = activity_writer._search_read
    def read(_client, **kwargs):
        if kwargs["model"] == "mail.activity":
            reads["count"] += 1
            return [] if reads["count"] == 1 else [{
                "id": 712, "res_model_id": [88, "account.move"], "res_id": 1,
                "summary": "Collection follow-up [Modeem:marker-12345678]",
            }]
        if kwargs["model"] == "ir.model":
            return [{"id": 88, "model": "account.move"}]
        return original(_client, **kwargs)
    monkeypatch.setattr(activity_writer, "_search_read", read)
    result = activity_writer.create_invoice_activity(
        base_url="https://odoo.example", database="db", transport="json2",
        login="u", secret="s", environment="test", company_id=3, invoice_id=1,
        activity_type_id=4, summary="Collection follow-up", date_deadline="2999-01-01",
        idempotency_marker="marker-12345678",
    )
    assert result["created"] is True
    assert result["activity_id"] == 712
    assert seen == [{
        "activity_type_id": 4, "res_model_id": 88, "res_id": 1,
        "summary": "Collection follow-up [Modeem:marker-12345678]",
        "date_deadline": "2999-01-01",
    }]


def test_writer_reconciles_existing_marker_without_duplicate_create(monkeypatch):
    created = []
    monkeypatch.setattr(activity_writer.security, "enforce_outbound_policy", lambda *_a, **_k: None)
    monkeypatch.setattr(activity_writer.safe_http, "build_client", lambda *_a: _Client())
    monkeypatch.setattr(activity_writer, "_invoice_model_preconditions", lambda *_a, **_k: 88)
    monkeypatch.setattr(
        activity_writer, "_search_read",
        lambda _client, **kwargs: (
            [{"id": 4}] if kwargs["model"] == "mail.activity.type"
            else [{"id": 99, "res_model_id": [88, "account.move"], "res_id": 1,
                   "summary": "Changed title [Modeem:marker-12345678]"}]
        ),
    )
    monkeypatch.setattr(activity_writer, "_create_one_activity", lambda *_a, **_k: created.append(1))
    result = activity_writer.create_invoice_activity(
        base_url="https://odoo.example", database="db", transport="json2",
        login="u", secret="s", environment="test", company_id=3, invoice_id=1,
        activity_type_id=4, summary="Collection follow-up", date_deadline="2999-01-01",
        idempotency_marker="marker-12345678",
    )
    assert result["created"] is False and result["activity_id"] == 99
    assert created == []


def test_collection_proposal_is_strict_and_canonical_hash_is_deterministic():
    payload = {
        "action_key": "finance.prepare_collection_followup",
        "approval_policy": "internal_manager",
        "service_request_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "tenant_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "connection_id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
        "company_id": 3,
        "source_tool_call_id": uuid.UUID("00000000-0000-0000-0000-000000000004"),
        "requested_source_tool_call_id": uuid.UUID("00000000-0000-0000-0000-000000000005"),
        "source_snapshot_hash": "a" * 64, "source_as_of": "2026-01-01",
        "source_tool_input": {"max_records": 10}, "target_records": [_target(1)],
        "totals_by_currency": [], "followup_type": "email", "draft_message": "Follow up",
        "internal_note": "", "reverify_before_execution": True,
    }
    proposal = CollectionProposal.model_validate(payload)
    first = canonical_collection_proposal(proposal)
    second = canonical_collection_proposal(CollectionProposal.model_validate(payload))
    assert first == second
    with pytest.raises(ValidationError):
        CollectionProposal.model_validate({**payload, "invoice_id": 1})

class _Client:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _approved_action(seed, monkeypatch):
    """Create the real request-bound action through the existing HTTP flow."""
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = datetime.now(UTC).date()
    monkeypatch.setattr(
        workbench_api, "_operations_read_page",
        _single_page([_invoice(1, due_date=as_of - timedelta(days=40), residual=10)]),
    )
    employee = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}"
    assert employee.post(f"{path}/agent/session", json={}, headers=_csrf(employee)).status_code == 200
    read = employee.post(
        f"{path}/agent/tools/execute",
        json={"tool_key": "finance.get_overdue_customer_invoices",
              "input": {"minimum_days_overdue": 30, "max_records": 100}},
        headers=_csrf(employee),
    )
    assert read.status_code == 200, read.text
    prepared = employee.post(
        f"{path}/agent/actions/prepare",
        json={"source_tool_call_id": read.json()["tool_calls"][0]["id"]},
        headers=_csrf(employee),
    )
    assert prepared.status_code == 200, prepared.text
    action = prepared.json()["action"]
    submitted = employee.post(
        f"{path}/agent/actions/{action['id']}/submit",
        json={"expected_action_version": action["version"],
              "expected_proposal_hash": action["proposal_hash"]},
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text
    db = TestingSession()
    manager = User(email="phase4b-manager@example.com", full_name="Manager",
                   password_hash=hash_password(PASSWORD))
    db.add(manager)
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_a"], user_id=manager.id, role="manager"))
    db.commit()
    db.close()
    manager_client = _client("phase4b-manager@example.com")
    awaiting = submitted.json()["action"]
    approved = manager_client.post(
        f"{path}/agent/actions/{action['id']}/approve",
        json={"expected_action_version": awaiting["version"],
              "expected_proposal_hash": awaiting["proposal_hash"]},
        headers=_csrf(manager_client),
    )
    assert approved.status_code == 200, approved.text
    return data, path, employee, manager_client, approved.json()["action"]


def test_manager_queue_is_server_bound_and_never_calls_writer(seed, monkeypatch):
    _, path, _, manager, approved = _approved_action(seed, monkeypatch)
    monkeypatch.setattr(activity_writer, "create_invoice_activity",
                        lambda **_: pytest.fail("HTTP handler must not write"))
    response = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"],
              "invoice_id": 999, "tenant_id": str(seed["tenant_b"])},
        headers=_csrf(manager),
    )
    assert response.status_code == 422  # strict transition schema
    response = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"]},
        headers=_csrf(manager),
    )
    assert response.status_code == 200, response.text
    body = response.json()["action"]
    assert body["status"] == "queued"
    assert body["execution_item_count"] == body["target_count"] == 1
    item = body["execution_items"][0]
    assert item["status"] == "pending" and item["attempt_count"] == 0
    assert body["can_queue_execution"] is False
    db = TestingSession()
    stored_action = db.query(OperationAction).one()
    stored_item = db.query(OperationActionExecutionItem).one()
    assert stored_action.execution_policy_id == "internal_invoice_activity_v1"
    assert stored_action.execution_deadline == (
        datetime.now(UTC).date() + timedelta(days=7)
    ).isoformat()
    assert len(stored_item.idempotency_marker) == 64
    assert stored_item.idempotency_marker == sha256(
        f"{stored_action.id}:{stored_item.invoice_id}:internal_invoice_activity_v1".encode()
    ).hexdigest()
    assert db.query(AuditLog).filter_by(action="agent_action_queued").count() == 1
    db.close()


@pytest.mark.parametrize("actor", ["employee", "customer", "cross_tenant"])
def test_only_other_tenant_manager_can_queue_approved_action(seed, monkeypatch, actor):
    _, path, employee, _, approved = _approved_action(seed, monkeypatch)
    client = employee
    if actor == "customer":
        client = _client("workbench-customer@example.com")
    elif actor == "cross_tenant":
        client = _client("b@example.com")
    response = client.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"]},
        headers=_csrf(client),
    )
    assert response.status_code in (403, 404)


@pytest.mark.parametrize("mutation", ["status", "version", "hash", "approval_fields"])
def test_queue_rejects_stale_or_unapproved_action_identity(seed, monkeypatch, mutation):
    _, path, _, manager, approved = _approved_action(seed, monkeypatch)
    db = TestingSession()
    row = db.query(OperationAction).one()
    if mutation == "status":
        row.status = "awaiting_approval"
    elif mutation == "version":
        row.version += 1
    elif mutation == "hash":
        db.execute(text("UPDATE operation_actions SET proposal_hash = :hash WHERE id = :id"),
                   {"hash": "0" * 64, "id": row.id.hex})
    else:
        db.execute(text("UPDATE operation_actions SET approved_at = NULL WHERE id = :id"),
                   {"id": row.id.hex})
    db.commit()
    db.close()
    response = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"]},
        headers=_csrf(manager),
    )
    assert response.status_code == 409


def test_worker_verifies_each_item_and_parent_only_succeeds_when_all_verified(seed, monkeypatch):
    _, path, _, manager, approved = _approved_action(seed, monkeypatch)
    queued = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"]},
        headers=_csrf(manager),
    )
    assert queued.status_code == 200
    calls = {"create": 0, "reconcile": 0}
    monkeypatch.setattr(worker_ops, "resolve_standard_todo_activity_type", lambda **_: 4)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_, **__: {"password": "secret"})
    monkeypatch.setattr(worker_ops, "resolve_auth_material",
                        lambda *_: SimpleNamespace(login="user", secret="secret"))
    monkeypatch.setattr(worker_ops, "preflight_invoice_collection_targets", lambda **_: True)
    def reconcile(**kwargs):
        calls["reconcile"] += 1
        return {
            "activity_id": None if calls["reconcile"] == 1 else 701,
            "idempotency_marker": kwargs["idempotency_marker"],
        }

    monkeypatch.setattr(worker_ops, "reconcile_invoice_activity", reconcile)
    def create(**kwargs):
        calls["create"] += 1
        return {"activity_id": 701, "created": True,
                "idempotency_marker": kwargs["idempotency_marker"]}
    monkeypatch.setattr(worker_ops, "create_invoice_activity", create)
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    assert worker_ops.run_queued_workbench_actions_once() == 1
    db = TestingSession()
    action = db.query(OperationAction).one()
    item = db.query(OperationActionExecutionItem).one()
    assert action.status == "succeeded" and action.verified_at is not None
    assert item.status == "succeeded" and item.external_activity_id == 701
    assert item.receipt_json and item.verified_at is not None
    assert calls["create"] == 1
    assert {h.event for h in db.query(OperationActionHistory).all()} >= {
        "target_started", "target_verified", "succeeded",
    }
    db.close()


def test_worker_reconcile_existing_skips_create_and_preserves_marker(seed, monkeypatch):
    _, path, _, manager, approved = _approved_action(seed, monkeypatch)
    queued = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={"expected_action_version": approved["version"],
              "expected_proposal_hash": approved["proposal_hash"]},
        headers=_csrf(manager),
    )
    assert queued.status_code == 200
    marker = queued.json()["action"]["execution_items"][0]["idempotency_marker"]
    monkeypatch.setattr(worker_ops, "resolve_standard_todo_activity_type", lambda **_: 4)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_, **__: {"password": "secret"})
    monkeypatch.setattr(worker_ops, "resolve_auth_material",
                        lambda *_: SimpleNamespace(login="user", secret="secret"))
    monkeypatch.setattr(worker_ops, "preflight_invoice_collection_targets", lambda **_: True)
    monkeypatch.setattr(worker_ops, "reconcile_invoice_activity",
                        lambda **_: {"activity_id": 702, "idempotency_marker": marker})
    monkeypatch.setattr(worker_ops, "create_invoice_activity",
                        lambda **_: pytest.fail("existing activity must be reused"))
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    assert worker_ops.run_queued_workbench_actions_once() == 1
    db = TestingSession()
    item = db.query(OperationActionExecutionItem).one()
    assert item.idempotency_marker == marker and item.external_activity_id == 702
    db.close()