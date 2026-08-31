"""Coverage for the multi-association operations board."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_session_token
from app.main import app
from app.models import AuditLog, OperationsTask, Tenant, TenantMembership, User
from tests.test_auth_security import TestingSession

INTERNAL_TOKEN = os.environ["SESSION_SECRET"]


@pytest.fixture()
def operations_seed():
    db = TestingSession()
    user = User(
        email=f"operator-{uuid.uuid4().hex[:8]}@example.com",
        full_name="موظف الخدمات المشتركة",
        password_hash="not-used",
        is_active=True,
    )
    outsider = User(
        email=f"outsider-{uuid.uuid4().hex[:8]}@example.com",
        full_name="موظف آخر",
        password_hash="not-used",
        is_active=True,
    )
    db.add_all([user, outsider])
    db.flush()

    tenants = [
        Tenant(name=f"جمعية الاختبار {index + 1}", code=f"ops-{uuid.uuid4().hex}")
        for index in range(15)
    ]
    hidden_tenant = Tenant(name="جمعية غير مكلّف بها", code=f"ops-hidden-{uuid.uuid4().hex}")
    db.add_all([*tenants, hidden_tenant])
    db.flush()
    db.add_all(
        [
            TenantMembership(
                tenant_id=tenant.id, user_id=user.id, role="manager", is_active=True
            )
            for tenant in tenants
        ]
    )
    now = datetime.now(UTC)
    tasks = [
        OperationsTask(
            tenant_id=tenant.id,
            title=f"مهمة {index + 1}",
            work_type="financial" if index % 2 else "administrative",
            status=("overdue", "awaiting_approval", "needs_intervention", "upcoming")[
                index % 4
            ],
            priority="urgent" if index % 3 == 0 else "normal",
            due_at=now + timedelta(days=index - 3),
            assignee_name=user.full_name,
            source="test",
        )
        for index, tenant in enumerate(tenants)
    ]
    hidden_task = OperationsTask(
        tenant_id=hidden_tenant.id,
        title="يجب ألا تظهر",
        work_type="financial",
        status="overdue",
        priority="urgent",
        due_at=now,
        assignee_name=outsider.full_name,
        source="test",
    )
    db.add_all([*tasks, hidden_task])
    db.commit()
    yield user, tenants, hidden_tenant
    db.close()


def _client_for(user: User, tenant_id: uuid.UUID) -> TestClient:
    client = TestClient(app)
    client.cookies.set("modeem_session", create_session_token(user.id, tenant_id))
    return client


def _action_headers(client: TestClient) -> dict[str, str]:
    token = "operations-board-csrf"
    client.cookies.set("modeem_csrf", token)
    return {
        "X-Internal-Token": INTERNAL_TOKEN,
        "X-CSRF-Token": token,
    }


def test_board_aggregates_only_assigned_associations(operations_seed) -> None:
    user, tenants, _hidden = operations_seed
    response = _client_for(user, tenants[0].id).get(
        "/api/v1/operations/board",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 15
    assert len(payload["associations"]) == 15
    assert {item["tenant_id"] for item in payload["items"]} == {
        str(tenant.id) for tenant in tenants
    }
    assert all(item["title"] != "يجب ألا تظهر" for item in payload["items"])


def test_board_filters_and_rejects_unassigned_tenant(operations_seed) -> None:
    user, tenants, hidden_tenant = operations_seed
    client = _client_for(user, tenants[0].id)
    filtered = client.get(
        f"/api/v1/operations/board?tenant_id={tenants[1].id}&work_type=financial",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["tenant_id"] == str(tenants[1].id)

    forbidden = client.get(
        f"/api/v1/operations/board?tenant_id={hidden_tenant.id}",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert forbidden.status_code == 403


def test_board_requires_internal_token_and_user_session(operations_seed) -> None:
    user, _tenants, _hidden = operations_seed
    assert (
        _client_for(user, _tenants[0].id).get("/api/v1/operations/board").status_code
        == 401
    )
    assert (
        TestClient(app)
        .get(
            "/api/v1/operations/board",
            headers={"X-Internal-Token": INTERNAL_TOKEN},
        )
        .status_code
        == 401
    )


def test_board_task_actions_update_summary_and_record_safe_audit(operations_seed) -> None:
    user, tenants, _hidden = operations_seed
    client = _client_for(user, tenants[0].id)
    headers = _action_headers(client)
    board = client.get(
        "/api/v1/operations/board", headers={"X-Internal-Token": INTERNAL_TOKEN}
    ).json()
    upcoming = next(item for item in board["items"] if item["status"] == "upcoming")

    completed = client.post(
        f"/api/v1/operations/board/tasks/{upcoming['id']}/complete",
        json={"expected_version": upcoming["version"]},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["available_actions"] == ["submit_for_approval"]

    submitted = client.post(
        f"/api/v1/operations/board/tasks/{upcoming['id']}/submit_for_approval",
        json={"expected_version": completed.json()["version"]},
        headers=headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "awaiting_approval"
    assert submitted.json()["approval_state"] == "pending"

    approved = client.post(
        f"/api/v1/operations/board/tasks/{upcoming['id']}/approve",
        json={"expected_version": submitted.json()["version"], "note": "Reviewed"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["approval_state"] == "approved"
    assert approved.json()["available_actions"] == []

    refreshed = client.get(
        "/api/v1/operations/board", headers={"X-Internal-Token": INTERNAL_TOKEN}
    ).json()
    assert refreshed["summary"]["total_active"] == board["summary"]["total_active"] - 1

    db = TestingSession()
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.resource_id == upcoming["id"])
        .order_by(AuditLog.created_at)
        .all()
    )
    assert [row.action for row in audit_rows] == [
        "operations_board.task_complete",
        "operations_board.task_submit_for_approval",
        "operations_board.task_approve",
    ]
    assert all(row.tenant_id == uuid.UUID(upcoming["tenant_id"]) for row in audit_rows)
    assert all(row.actor_id == str(user.id) for row in audit_rows)
    assert "Reviewed" not in str([row.metadata_json for row in audit_rows])
    db.close()


def test_board_rejection_intervention_and_cross_tenant_guards(operations_seed) -> None:
    user, tenants, hidden_tenant = operations_seed
    client = _client_for(user, tenants[0].id)
    headers = _action_headers(client)
    board = client.get(
        "/api/v1/operations/board", headers={"X-Internal-Token": INTERNAL_TOKEN}
    ).json()
    awaiting = next(item for item in board["items"] if item["status"] == "awaiting_approval")
    overdue = next(item for item in board["items"] if item["status"] == "overdue")

    missing_reason = client.post(
        f"/api/v1/operations/board/tasks/{awaiting['id']}/reject",
        json={"expected_version": awaiting["version"]},
        headers=headers,
    )
    assert missing_reason.status_code == 422
    rejected = client.post(
        f"/api/v1/operations/board/tasks/{awaiting['id']}/reject",
        json={"expected_version": awaiting["version"], "note": "Needs correction"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "needs_intervention"
    assert rejected.json()["approval_state"] == "rejected"

    intervened = client.post(
        f"/api/v1/operations/board/tasks/{overdue['id']}/record_intervention",
        json={"expected_version": overdue["version"], "note": "Called the association"},
        headers=headers,
    )
    assert intervened.status_code == 200
    assert intervened.json()["status"] == "needs_intervention"

    db = TestingSession()
    hidden_id = str(
        db.query(OperationsTask.id)
        .filter(OperationsTask.tenant_id == hidden_tenant.id)
        .scalar()
    )
    db.close()
    hidden = client.post(
        f"/api/v1/operations/board/tasks/{hidden_id}/complete",
        json={"expected_version": 1},
        headers=headers,
    )
    assert hidden.status_code == 404

    stale = client.post(
        f"/api/v1/operations/board/tasks/{overdue['id']}/complete",
        json={"expected_version": overdue["version"]},
        headers=headers,
    )
    assert stale.status_code == 409