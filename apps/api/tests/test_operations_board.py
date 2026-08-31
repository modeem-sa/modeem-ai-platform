"""Coverage for the multi-association operations board."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_session_token
from app.main import app
from app.models import OperationsTask, Tenant, TenantMembership, User
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