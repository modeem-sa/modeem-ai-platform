import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.api import workbench as workbench_api
from app.core.security import hash_password
from app.integrations.odoo import invoice_chatter_collection as chatter
from app.models import (
    AuditLog,
    OperationActionExecutionItem,
    TenantMembership,
    User,
    WorkbenchCollectionMessageEvent,
)
from app.operations.workbench_collection_message import (
    EditWorkbenchCommunicationInput,
    PrepareWorkbenchCommunicationInput,
    _same_live_record,
    canonical_grouped_source_identity,
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
from tests.test_workbench_execution import _approved_action


def _source(**overrides):
    value = {
        "tenant_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "service_request_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "action_id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
        "approved_proposal_hash": "a" * 64,
        "connection_id": uuid.UUID("00000000-0000-0000-0000-000000000004"),
        "company_id": 7,
        "partner_id": 55,
        "invoice_records": [
            {"invoice_id": 42, "currency": "SAR", "remaining_amount": "100.00"},
            {"invoice_id": 43, "currency": "USD", "remaining_amount": "25.00"},
        ],
        "execution_evidence": [
            {"item_id": "b", "invoice_id": 43, "external_activity_id": 81},
            {"item_id": "a", "invoice_id": 42, "external_activity_id": 80},
        ],
    }
    value.update(overrides)
    return value


def test_grouped_source_hash_is_deterministic_and_order_independent():
    first = canonical_grouped_source_identity(**_source())
    second = canonical_grouped_source_identity(
        **_source(
            invoice_records=list(reversed(_source()["invoice_records"])),
            execution_evidence=list(reversed(_source()["execution_evidence"])),
        )
    )
    assert first == second
    assert first != canonical_grouped_source_identity(**_source(partner_id=56))


def test_phase4c_request_bodies_cannot_inject_server_owned_identity():
    with pytest.raises(ValidationError):
        PrepareWorkbenchCommunicationInput.model_validate({"tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        EditWorkbenchCommunicationInput.model_validate(
            {
                "expected_message_version": 1,
                "expected_draft_version": 1,
                "expected_draft_hash": "a" * 64,
                "expected_source_version": 1,
                "expected_source_hash": "b" * 64,
                "content": "رسالة تحصيل",
                "partner_id": 55,
            }
        )


def test_legacy_proposal_reference_and_due_date_are_derived_from_approved_facts():
    record = {
        "invoice_id": 42,
        "invoice_number": "INV/0042",
        "customer_id": 55,
        "currency_id": 1,
        "currency": "SAR",
        "remaining_amount": "100.00",
        "days_overdue": 10,
    }
    live = {
        "partner_id": 55,
        "company_id": 7,
        "move_type": "out_invoice",
        "state": "posted",
        "residual": "100.0",
        "currency": "SAR",
        "currency_name": None,
        "due_date": "2026-04-01",
        "reference": "INV/0042",
    }
    assert _same_live_record(record, live, 7, "2026-04-11")
    assert not _same_live_record(
        record, {**live, "reference": "INV/CHANGED"}, 7, "2026-04-11"
    )
    assert not _same_live_record(
        record, {**live, "due_date": "2026-04-02"}, 7, "2026-04-11"
    )
    assert not _same_live_record(record, live, 7, None)


def _snapshot(
    invoice_id: int,
    *,
    partner_id: int = 10,
    customer: str = "Customer 10",
    residual: str = "10.00",
    currency: str = "SAR",
    reference: str | None = None,
    overdue_days: int = 40,
) -> dict:
    return {
        "invoice_id": invoice_id,
        "company_id": 1,
        "partner_id": partner_id,
        "partner_name": customer,
        "move_type": "out_invoice",
        "state": "posted",
        "residual": residual,
        "due_date": (datetime.now(UTC).date() - timedelta(days=overdue_days)).isoformat(),
        "currency": currency,
        "reference": reference or f"INV/{invoice_id:04d}",
    }


def _wire_read_only_snapshots(monkeypatch, snapshots: dict[int, dict]) -> None:
    import app.operations.workbench_collection_message as communication_ops

    monkeypatch.setattr(
        communication_ops,
        "decrypt_credentials",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        communication_ops,
        "resolve_auth_material",
        lambda *_args, **_kwargs: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(
        communication_ops,
        "read_invoice_collection_snapshot",
        lambda **kwargs: snapshots[int(kwargs["invoice_id"])].copy(),
    )


def _succeeded_action(seed, monkeypatch, *, snapshots=None):
    data, path, employee, manager, approved = _approved_action(seed, monkeypatch)
    queued = manager.post(
        f"{path}/agent/actions/{approved['id']}/queue",
        json={
            "expected_action_version": approved["version"],
            "expected_proposal_hash": approved["proposal_hash"],
        },
        headers=_csrf(manager),
    )
    assert queued.status_code == 200, queued.text

    monkeypatch.setattr(worker_ops, "resolve_standard_todo_activity_type", lambda **_: 4)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_a, **_k: {})
    monkeypatch.setattr(
        worker_ops,
        "resolve_auth_material",
        lambda *_a, **_k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(worker_ops, "preflight_invoice_collection_targets", lambda **_: True)
    monkeypatch.setattr(
        worker_ops,
        "reconcile_invoice_activity",
        lambda **kwargs: {
            "activity_id": 700 + int(kwargs["invoice_id"]),
            "idempotency_marker": kwargs["idempotency_marker"],
        },
    )
    monkeypatch.setattr(
        worker_ops,
        "create_invoice_activity",
        lambda **kwargs: {
            "activity_id": 700 + int(kwargs["invoice_id"]),
            "created": True,
            "idempotency_marker": kwargs["idempotency_marker"],
        },
    )
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    assert worker_ops.run_queued_workbench_actions_once() == 1

    if snapshots is None:
        snapshots = {1: _snapshot(1)}
    _wire_read_only_snapshots(monkeypatch, snapshots)
    return data, path, employee, manager, approved


def _succeeded_multi_customer_action(seed, monkeypatch, records):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    monkeypatch.setattr(
        workbench_api,
        "_operations_read_page",
        _single_page(records),
    )
    employee = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}"
    assert employee.post(
        f"{path}/agent/session", json={}, headers=_csrf(employee)
    ).status_code == 200
    read = employee.post(
        f"{path}/agent/tools/execute",
        json={
            "tool_key": "finance.get_overdue_customer_invoices",
            "input": {"minimum_days_overdue": 30, "max_records": 100},
        },
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
        json={
            "expected_action_version": action["version"],
            "expected_proposal_hash": action["proposal_hash"],
        },
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text

    db = TestingSession()
    manager = User(
        email="phase4c-multi-manager@example.com",
        full_name="Phase 4C Manager",
        password_hash=hash_password(PASSWORD),
    )
    db.add(manager)
    db.flush()
    db.add(
        TenantMembership(
            tenant_id=seed["tenant_a"], user_id=manager.id, role="manager"
        )
    )
    db.commit()
    db.close()
    manager_client = _client("phase4c-multi-manager@example.com")
    awaiting = submitted.json()["action"]
    approved = manager_client.post(
        f"{path}/agent/actions/{action['id']}/approve",
        json={
            "expected_action_version": awaiting["version"],
            "expected_proposal_hash": awaiting["proposal_hash"],
        },
        headers=_csrf(manager_client),
    )
    assert approved.status_code == 200, approved.text
    approved_action = approved.json()["action"]
    queued = manager_client.post(
        f"{path}/agent/actions/{approved_action['id']}/queue",
        json={
            "expected_action_version": approved_action["version"],
            "expected_proposal_hash": approved_action["proposal_hash"],
        },
        headers=_csrf(manager_client),
    )
    assert queued.status_code == 200, queued.text

    monkeypatch.setattr(worker_ops, "resolve_standard_todo_activity_type", lambda **_: 4)
    monkeypatch.setattr(worker_ops, "decrypt_credentials", lambda *_a, **_k: {})
    monkeypatch.setattr(
        worker_ops,
        "resolve_auth_material",
        lambda *_a, **_k: SimpleNamespace(login="service", secret="secret"),
    )
    monkeypatch.setattr(worker_ops, "preflight_invoice_collection_targets", lambda **_: True)
    monkeypatch.setattr(
        worker_ops,
        "reconcile_invoice_activity",
        lambda **kwargs: {
            "activity_id": 700 + int(kwargs["invoice_id"]),
            "idempotency_marker": kwargs["idempotency_marker"],
        },
    )
    monkeypatch.setattr(
        worker_ops,
        "create_invoice_activity",
        lambda **kwargs: {
            "activity_id": 700 + int(kwargs["invoice_id"]),
            "created": True,
            "idempotency_marker": kwargs["idempotency_marker"],
        },
    )
    monkeypatch.setattr(worker_ops, "get_session_factory", lambda: TestingSession)
    assert worker_ops.run_queued_workbench_actions_once() == 1
    return data, path, employee, approved_action


def _communication_prepare(
    client, path: str, action_id: str, *, locale: str = "ar", extra: dict | None = None
):
    body = {"locale": locale}
    if extra:
        body.update(extra)
    return client.post(
        f"{path}/agent/actions/{action_id}/communications/prepare",
        json=body,
        headers=_csrf(client),
    )


def _edit_body(message: dict, content: str = "رسالة تحصيل معدلة") -> dict:
    return {
        "expected_message_version": message["version"],
        "expected_draft_version": message["draft_version"],
        "expected_draft_hash": message["draft_hash"],
        "expected_source_version": message["source_version"],
        "expected_source_hash": message["source_hash"],
        "content": content,
    }


def _submit_body(message: dict) -> dict:
    return {
        "expected_message_version": message["version"],
        "expected_draft_version": message["draft_version"],
        "expected_draft_hash": message["draft_hash"],
        "expected_source_version": message["source_version"],
        "expected_source_hash": message["source_hash"],
    }


def test_http_prepare_list_edit_submit_persists_events_and_audits(seed, monkeypatch):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    prepared = _communication_prepare(employee, path, str(approved["id"]))
    assert prepared.status_code == 200, prepared.text
    messages = prepared.json()["messages"]
    assert len(messages) == 1
    draft = messages[0]
    assert draft["status"] == "draft"
    assert draft["can_edit"] and draft["can_submit"]
    assert draft["customer"] == "Customer 10"
    assert draft["invoice_records"][0]["live_snapshot"]["currency"] == "SAR"
    assert draft["source"] == "Verified Phase 4B Odoo execution"

    listed = employee.get(
        f"{path}/agent/actions/{approved['id']}/communications",
    )
    assert listed.status_code == 200
    assert listed.json()["messages"][0]["id"] == draft["id"]

    edited = employee.patch(
        f"{path}/agent/communications/{draft['id']}",
        json=_edit_body(draft),
        headers=_csrf(employee),
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()["message"]
    assert updated["draft_version"] == draft["draft_version"] + 1
    assert updated["draft_hash"] != draft["draft_hash"]
    assert updated["source_hash"] == draft["source_hash"]

    submitted = employee.post(
        f"{path}/agent/communications/{draft['id']}/submit",
        json=_submit_body(updated),
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text
    awaiting = submitted.json()["message"]
    assert awaiting["status"] == "awaiting_approval"
    assert awaiting["can_edit"] is False
    assert awaiting["can_submit"] is False

    db = TestingSession()
    events = db.query(WorkbenchCollectionMessageEvent).all()
    assert {event.event for event in events} >= {
        "generated",
        "policy_checked",
        "regenerated",
        "submitted",
    }
    audits = db.query(AuditLog).all()
    assert {
        "workbench_collection_message.generated",
        "workbench_collection_message.policy_checked",
        "workbench_collection_message.regenerated",
        "workbench_collection_message.submitted",
    } <= {audit.action for audit in audits}
    assert all("رسالة تحصيل معدلة" not in str(audit.metadata_json) for audit in audits)
    db.close()


@pytest.mark.parametrize("status", ["approved", "failed", "executing", "verifying"])
def test_http_prepare_requires_succeeded_fully_verified_correct_workflow(
    seed, monkeypatch, status
):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    db = TestingSession()
    db.execute(
        text("UPDATE operation_actions SET status = :status WHERE id = :id"),
        {"status": status, "id": uuid.UUID(approved["id"]).hex},
    )
    db.commit()
    db.close()
    response = _communication_prepare(employee, path, str(approved["id"]))
    assert response.status_code == 409


def test_http_prepare_rejects_partial_execution_and_wrong_workflow(seed, monkeypatch):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    db = TestingSession()
    item = db.query(OperationActionExecutionItem).one()
    item.status = "failed"
    db.commit()
    db.close()
    assert _communication_prepare(employee, path, str(approved["id"])).status_code == 409

    db = TestingSession()
    db.execute(
        text(
            "UPDATE operation_actions SET status = 'succeeded', workflow_key = 'other.workflow' WHERE id = :id"
        ),
        {"id": uuid.UUID(approved["id"]).hex},
    )
    db.commit()
    db.close()
    assert _communication_prepare(employee, path, str(approved["id"])).status_code == 404


def test_http_customer_and_cross_tenant_employee_cannot_prepare_or_list(seed, monkeypatch):
    _data, path, _employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    for client in (
        _client("workbench-customer@example.com"),
        _client("b@example.com"),
    ):
        assert _communication_prepare(client, path, str(approved["id"])).status_code == 404
        assert (
            client.get(
                f"{path}/agent/actions/{approved['id']}/communications"
            ).status_code
            == 404
        )


def test_http_communication_bodies_reject_every_server_identity_injection(seed, monkeypatch):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    prepared = _communication_prepare(
        employee,
        path,
        str(approved["id"]),
        extra={"tenant_id": str(seed["tenant_b"]), "connection_id": "attacker"},
    )
    assert prepared.status_code == 422
    clean = _communication_prepare(employee, path, str(approved["id"]))
    message = clean.json()["messages"][0]

    edit = employee.patch(
        f"{path}/agent/communications/{message['id']}",
        json={**_edit_body(message), "partner_id": 999, "invoice_id": 999},
        headers=_csrf(employee),
    )
    assert edit.status_code == 422
    submit = employee.post(
        f"{path}/agent/communications/{message['id']}/submit",
        json={**_submit_body(message), "tenant_id": str(seed["tenant_b"])},
        headers=_csrf(employee),
    )
    assert submit.status_code == 422


def test_http_submitted_draft_cannot_be_edited_and_delivery_is_never_called(
    seed, monkeypatch
):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    calls = []
    monkeypatch.setattr(
        chatter,
        "deliver_invoice_collection_message",
        lambda **kwargs: calls.append(kwargs),
    )
    draft = _communication_prepare(employee, path, str(approved["id"])).json()["messages"][0]
    edited = employee.patch(
        f"{path}/agent/communications/{draft['id']}",
        json=_edit_body(draft),
        headers=_csrf(employee),
    ).json()["message"]
    submitted = employee.post(
        f"{path}/agent/communications/{draft['id']}/submit",
        json=_submit_body(edited),
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200
    assert (
        employee.patch(
            f"{path}/agent/communications/{draft['id']}",
            json=_edit_body(edited, "محاولة تعديل بعد التقديم"),
            headers=_csrf(employee),
        ).status_code
        == 409
    )
    assert calls == []
    assert employee.post(
        f"{path}/agent/actions/{approved['id']}/communications/{draft['id']}/approve",
        json=_submit_body(edited),
        headers=_csrf(employee),
    ).status_code == 404
    assert employee.post(
        f"{path}/agent/communications/{draft['id']}/send",
        json={},
        headers=_csrf(employee),
    ).status_code == 404
    assert employee.post(
        f"{path}/agent/communications/{draft['id']}/retry",
        json={},
        headers=_csrf(employee),
    ).status_code == 404


@pytest.mark.parametrize("drift_field", ["residual", "partner_id", "reference"])
def test_http_live_source_drift_blocks_submit(seed, monkeypatch, drift_field):
    snapshots = {1: _snapshot(1)}
    _data, path, employee, _manager, approved = _succeeded_action(
        seed, monkeypatch, snapshots=snapshots
    )
    draft = _communication_prepare(employee, path, str(approved["id"])).json()["messages"][0]
    changed = snapshots[1].copy()
    changed[drift_field] = (
        "99.00" if drift_field == "residual" else 99 if drift_field == "partner_id" else "INV/CHANGED"
    )
    import app.operations.workbench_collection_message as communication_ops

    monkeypatch.setattr(
        communication_ops,
        "read_invoice_collection_snapshot",
        lambda **kwargs: changed.copy(),
    )
    response = employee.post(
        f"{path}/agent/communications/{draft['id']}/submit",
        json=_submit_body(draft),
        headers=_csrf(employee),
    )
    assert response.status_code == 409
    assert "source_changed_requires_review" in response.text


@pytest.mark.parametrize("code", ["contact_opted_out", "policy_unavailable", "outside_contact_hours"])
def test_http_policy_blocks_preparation_fail_closed(seed, monkeypatch, code):
    _data, path, employee, _manager, approved = _succeeded_action(seed, monkeypatch)
    import app.operations.workbench_collection_message as communication_ops

    monkeypatch.setattr(
        communication_ops,
        "read_invoice_collection_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            chatter.CollectionMessagePolicyError("blocked", code=code)
        ),
    )
    response = _communication_prepare(employee, path, str(approved["id"]))
    assert response.status_code == 409
    assert response.json()["detail"] == f"communication_policy_blocked:{code}"


def test_http_multi_customer_drafts_are_separated_and_currency_totals_are_not_merged(
    seed, monkeypatch
):
    records = [
        _invoice(
            1,
            due_date=datetime.now(UTC).date() - timedelta(days=40),
            residual=10,
            customer_id=10,
            currency_id=1,
            currency="SAR",
        ),
        _invoice(
            2,
            due_date=datetime.now(UTC).date() - timedelta(days=41),
            residual=20,
            customer_id=20,
            currency_id=1,
            currency="SAR",
        ),
        _invoice(
            3,
            due_date=datetime.now(UTC).date() - timedelta(days=42),
            residual=30,
            customer_id=10,
            currency_id=2,
            currency="USD",
        ),
    ]
    _data, path, employee, approved = _succeeded_multi_customer_action(
        seed, monkeypatch, records
    )
    _wire_read_only_snapshots(
        monkeypatch,
        {
            1: _snapshot(1, partner_id=10, customer="Customer 10", currency="SAR"),
                2: _snapshot(
                    2, partner_id=20, customer="Customer 20", currency="SAR",
                    residual="20.00",
                    overdue_days=41,
                ),
                3: _snapshot(
                    3, partner_id=10, customer="Customer 10", currency="USD",
                    residual="30.00",
                    overdue_days=42,
                ),
        },
    )
    response = _communication_prepare(employee, path, str(approved["id"]))
    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert len(messages) == 2
    by_customer = {message["customer"]: message for message in messages}
    assert set(by_customer) == {"Customer 10", "Customer 20"}
    assert len(by_customer["Customer 10"]["invoice_records"]) == 2
    assert len(by_customer["Customer 20"]["invoice_records"]) == 1
    customer_10_text = str(by_customer["Customer 10"])
    customer_20_text = str(by_customer["Customer 20"])
    assert "Customer 20" not in customer_10_text
    assert "Customer 10" not in customer_20_text
    currencies = {
        item["live_snapshot"]["currency"]
        for item in by_customer["Customer 10"]["invoice_records"]
    }
    assert currencies == {"SAR", "USD"}