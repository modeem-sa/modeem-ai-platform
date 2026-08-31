"""Focused lifecycle and tenancy coverage for operations tasks."""

import uuid
from types import SimpleNamespace

from app.api import operations as operations_api
from app.core.security import hash_password
from app.models import (
    AuditLog,
    Connection,
    OperationTask,
    OperationTaskHistory,
    TenantMembership,
    User,
)
from tests.test_auth_security import PASSWORD, TestingSession, _client, _csrf, _login


def _create(client, tenant_id, assigned_user_id=None, due_at=None):
    return client.post(
        "/api/v1/operations/tasks",
        json={
            "tenant_id": str(tenant_id),
            "title": "Reconcile invoices",
            "category": "financial",
            "priority": "high",
            "assigned_user_id": str(assigned_user_id) if assigned_user_id else None,
            "due_at": due_at,
        },
        headers=_csrf(client),
    )


def test_full_lifecycle_records_history_and_safe_audit(seed):
    db = TestingSession()
    worker = User(
        email="worker@example.com", full_name="Worker", password_hash=hash_password(PASSWORD)
    )
    db.add(worker)
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_a"], user_id=worker.id, role="member"))
    db.commit()
    worker_id = worker.id
    db.close()

    admin = _client()
    _login(admin, "a@example.com")
    created = _create(admin, seed["tenant_a"], worker_id, "2030-01-02T03:04:05Z")
    assert created.status_code == 201
    task = created.json()
    assert task["due_at"].startswith("2030-01-02T03:04:05")

    worker_client = _client()
    _login(worker_client, "worker@example.com")
    started = worker_client.post(
        f"/api/v1/operations/tasks/{task['id']}/start",
        json={"expected_version": 1},
        headers=_csrf(worker_client),
    )
    assert started.status_code == 200 and started.json()["status"] == "in_progress"
    completed = worker_client.post(
        f"/api/v1/operations/tasks/{task['id']}/complete",
        json={"expected_version": 2},
        headers=_csrf(worker_client),
    )
    submitted = worker_client.post(
        f"/api/v1/operations/tasks/{task['id']}/submit-for-approval",
        json={"expected_version": 3},
        headers=_csrf(worker_client),
    )
    assert completed.status_code == submitted.status_code == 200
    approved = admin.post(
        f"/api/v1/operations/tasks/{task['id']}/approve",
        json={"expected_version": 4},
        headers=_csrf(admin),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_at"] is not None
    assert approved.json()["decision_note"] is None

    db = TestingSession()
    assert db.query(OperationTaskHistory).filter_by(task_id=uuid.UUID(task["id"])).count() == 5
    actions = [row.action for row in db.query(AuditLog).filter_by(resource_id=task["id"]).all()]
    assert {"task.created", "task.started", "task.completed", "task.submitted_for_approval", "task.approved"} <= set(actions)
    db.close()


def test_stale_invalid_roles_assignee_and_cross_tenant_are_denied(seed):
    admin = _client()
    _login(admin, "a@example.com")
    # User B has no membership in tenant A, so cannot be assigned there.
    invalid_assignee = _create(admin, seed["tenant_a"], seed["user_b"])
    assert invalid_assignee.status_code == 422
    created = _create(admin, seed["tenant_a"])
    task_id = created.json()["id"]
    # An unassigned task cannot be started by an ordinary member in tenant B,
    # and a foreign task id is deliberately indistinguishable from missing.
    member = _client()
    _login(member, "b@example.com")
    assert member.get(f"/api/v1/operations/tasks/{task_id}").status_code == 404
    stale = admin.post(
        f"/api/v1/operations/tasks/{task_id}/start",
        json={"expected_version": 2},
        headers=_csrf(admin),
    )
    assert stale.status_code == 409
    invalid = admin.post(
        f"/api/v1/operations/tasks/{task_id}/complete",
        json={"expected_version": 1},
        headers=_csrf(admin),
    )
    assert invalid.status_code == 409


def test_rejection_requires_reason_and_rejected_task_can_reopen(seed):
    client = _client()
    _login(client, "a@example.com")
    task_id = _create(client, seed["tenant_a"]).json()["id"]
    for endpoint, version in (("start", 1), ("complete", 2), ("submit-for-approval", 3)):
        response = client.post(
            f"/api/v1/operations/tasks/{task_id}/{endpoint}",
            json={"expected_version": version},
            headers=_csrf(client),
        )
        assert response.status_code == 200
    for note in (None, "   "):
        response = client.post(
            f"/api/v1/operations/tasks/{task_id}/reject",
            json={"expected_version": 4, "note": note},
            headers=_csrf(client),
        )
        assert response.status_code == 422
    rejected = client.post(
        f"/api/v1/operations/tasks/{task_id}/reject",
        json={"expected_version": 4, "note": "Missing evidence"},
        headers=_csrf(client),
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    reopened = client.post(
        f"/api/v1/operations/tasks/{task_id}/start",
        json={"expected_version": 5},
        headers=_csrf(client),
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "in_progress"
    db = TestingSession()
    assert db.query(AuditLog).filter_by(resource_id=task_id, action="task.reopened").count() == 1
    assert db.query(OperationTaskHistory).filter_by(task_id=uuid.UUID(task_id), action="reopened").count() == 1
    db.close()


def test_list_uses_all_active_memberships_and_excludes_inactive(seed):
    db = TestingSession()
    user = db.get(User, seed["user_a"])
    db.add(TenantMembership(tenant_id=seed["tenant_b"], user_id=user.id, role="manager"))
    db.add(
        OperationTask(
            tenant_id=seed["tenant_a"], title="A", category="administrative",
            priority="low", created_by_user_id=user.id,
        )
    )
    db.add(
        OperationTask(
            tenant_id=seed["tenant_b"], title="B", category="financial",
            priority="urgent", created_by_user_id=user.id,
        )
    )
    db.commit()
    db.close()
    client = _client()
    _login(client, "a@example.com")
    listed = client.get("/api/v1/operations/tasks")
    assert listed.status_code == 200
    assert {item["tenant_name"] for item in listed.json()["items"]} == {"Tenant A", "Tenant B"}

    db = TestingSession()
    db.query(TenantMembership).filter_by(user_id=seed["user_a"], tenant_id=seed["tenant_b"]).update(
        {"is_active": False}
    )
    db.commit()
    db.close()
    assert client.get("/api/v1/operations/tasks").json()["total"] == 1


def test_bootstrap_manager_members_exclude_inactive_records(seed):
    db = TestingSession()
    manager = User(
        email="manager-operations@example.com",
        full_name="Operations Manager",
        password_hash=hash_password(PASSWORD),
    )
    worker = User(
        email="active-worker@example.com",
        full_name="Active Worker",
        password_hash=hash_password(PASSWORD),
    )
    inactive_user = User(
        email="disabled-worker@example.com",
        full_name="Disabled Worker",
        password_hash=hash_password(PASSWORD),
        is_active=False,
    )
    inactive_membership_user = User(
        email="inactive-membership@example.com",
        full_name="Inactive Membership",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([manager, worker, inactive_user, inactive_membership_user])
    db.flush()
    db.add_all(
        [
            TenantMembership(tenant_id=seed["tenant_a"], user_id=manager.id, role="manager"),
            TenantMembership(tenant_id=seed["tenant_a"], user_id=worker.id, role="member"),
            TenantMembership(tenant_id=seed["tenant_a"], user_id=inactive_user.id, role="member"),
            TenantMembership(
                tenant_id=seed["tenant_a"],
                user_id=inactive_membership_user.id,
                role="member",
                is_active=False,
            ),
        ]
    )
    db.commit()
    db.close()
    client = _client()
    _login(client, "manager-operations@example.com")
    response = client.get("/api/v1/operations/bootstrap")
    assert response.status_code == 200
    tenant = response.json()["tenants"][0]
    assert tenant["role"] == "manager" and tenant["can_create"] is True
    emails = {member["email"] for member in tenant["members"]}
    assert "active-worker@example.com" in emails
    assert "disabled-worker@example.com" not in emails
    assert "inactive-membership@example.com" not in emails


def test_bootstrap_superuser_without_membership_can_create_and_assign(seed):
    db = TestingSession()
    superuser = User(
        email="superuser@example.com",
        full_name="Platform Admin",
        password_hash=hash_password(PASSWORD),
        is_superuser=True,
    )
    assignee = User(
        email="tenant-b-worker@example.com",
        full_name="Tenant B Worker",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([superuser, assignee])
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_b"], user_id=assignee.id, role="member"))
    db.commit()
    assignee_id = assignee.id
    db.close()
    client = _client()
    _login(client, "superuser@example.com")
    bootstrap = client.get("/api/v1/operations/bootstrap")
    assert bootstrap.status_code == 200
    tenants = bootstrap.json()["tenants"]
    assert {tenant["name"] for tenant in tenants} == {"Tenant A", "Tenant B"}
    assert all(tenant["role"] == "superuser" and tenant["can_create"] for tenant in tenants)
    tenant_b = next(tenant for tenant in tenants if tenant["name"] == "Tenant B")
    assert any(member["email"] == "tenant-b-worker@example.com" for member in tenant_b["members"])
    created = _create(client, seed["tenant_b"], assignee_id)
    assert created.status_code == 201

def test_active_member_can_open_self_assigned_human_resources_request(seed):
    db = TestingSession()
    worker = User(
        email="hr-requester@example.com",
        full_name="HR Requester",
        password_hash=hash_password(PASSWORD),
    )
    db.add(worker)
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_a"], user_id=worker.id, role="member"))
    db.commit()
    worker_id = worker.id
    db.close()

    client = _client()
    _login(client, "hr-requester@example.com")
    bootstrap = client.get("/api/v1/operations/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["tenants"][0]["can_create"] is True
    assert bootstrap.json()["tenants"][0]["members"] == []

    response = client.post(
        "/api/v1/operations/tasks",
        json={
            "tenant_id": str(seed["tenant_a"]),
            "title": "Prepare payroll",
            "description": "August payroll",
            "category": "human_resources",
            "procedure_type": "prepare_payroll",
            "request_data": {"period": "2026-08", "details": "Review all employees"},
            "priority": "medium",
        },
        headers=_csrf(client),
    )

    assert response.status_code == 201
    request = response.json()
    assert request["assigned_user_id"] == str(worker_id)
    assert request["created_by_user_id"] == str(worker_id)
    assert request["category"] == "human_resources"
    assert request["procedure_type"] == "prepare_payroll"
    assert request["request_data"]["period"] == "2026-08"
    assert request["source_type"] == "manual"

def test_hr_review_task_persists_only_server_approved_reference(seed):
    db = TestingSession()
    connection = Connection(
        tenant_id=seed["tenant_a"],
        name="HR Odoo",
        provider="odoo",
        base_url="https://example.odoo.com",
        status="configured",
        is_active=True,
        last_test_status="success",
        odoo_company_id=15,
        created_by_user_id=seed["user_a"],
    )
    db.add(connection)
    db.commit()
    connection_id = connection.id
    db.close()

    client = _client()
    _login(client, "a@example.com")
    payload = {
        "tenant_id": str(seed["tenant_a"]),
        "connection_id": str(connection_id),
        "resource": "payroll_summary",
        "record_id": 88,
        "employee_id": 7,
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "priority": "high",
    }
    response = client.post(
        "/api/v1/operations/hr-review-tasks",
        json=payload,
        headers=_csrf(client),
    )
    assert response.status_code == 201
    task = response.json()
    assert task["source_type"] == "odoo"
    assert task["source_record_id"] == 88
    assert task["source_snapshot"] == {
        "resource": "payroll_summary",
        "record_id": 88,
        "employee_id": 7,
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "company_id": 15,
    }
    assert "salary" not in task["description"].lower()
    assert client.post(
        "/api/v1/operations/hr-review-tasks",
        json={**payload, "description": "Net salary: SECRET"},
        headers=_csrf(client),
    ).status_code == 422


def _operations_odoo_connection(tenant_id, *, company_id=41):
    db = TestingSession()
    connection = Connection(
        tenant_id=tenant_id,
        name=f"Operations Odoo {tenant_id}",
        provider="odoo",
        base_url="https://odoo.example.test",
        database_name="odoo",
        username="odoo-user",
        encrypted_credentials=b"encrypted",
        encryption_version=1,
        odoo_company_id=company_id,
        last_test_status="success",
        selected_transport="xmlrpc",
    )
    db.add(connection)
    db.commit()
    db.close()
    return connection


def _mock_operations_odoo(monkeypatch, calls, *, module_installed=True):
    monkeypatch.setattr(
        operations_api, "decrypt_credentials", lambda *_args, **_kwargs: {"password_or_api_key": "secret"}
    )
    monkeypatch.setattr(
        operations_api,
        "resolve_auth_material",
        lambda *_args, **_kwargs: SimpleNamespace(login="odoo-user", secret="secret"),
    )

    def fake_read_page(**kwargs):
        calls.append(kwargs)
        if kwargs["resource"] == "installed_modules":
            return {"records": [{"id": 1, "name": "account"}] if module_installed else []}
        return {
            "resource": kwargs["resource"],
            "fields": ["id"],
            "records": [{"id": 9}],
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "returned_count": 1,
            "has_more": False,
            "next_offset": None,
            "transport": "xmlrpc",
        }

    monkeypatch.setattr(operations_api, "read_page", fake_read_page)


def test_operations_catalog_allows_assigned_member_and_uses_live_module(seed, monkeypatch):
    _operations_odoo_connection(seed["tenant_b"])
    calls = []
    _mock_operations_odoo(monkeypatch, calls)
    client = _client()
    _login(client, "b@example.com")

    response = client.get(f"/api/v1/operations/catalog?tenant_id={seed['tenant_b']}")

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(seed["tenant_b"])
    assert response.json()["modules"] == [
        {
            "key": "finance",
            "label": "Finance",
            "services": [
                {"key": "accounting_entries", "label": "Accounting entries"},
                {"key": "journal_items", "label": "Journal items"},
                {"key": "payments_summary", "label": "Payments"},
                {"key": "journals_summary", "label": "Journals"},
                {"key": "invoices", "label": "Invoices"},
                {"key": "vendor_bills", "label": "Vendor bills"},
            ],
        }
    ]
    assert calls[0]["resource"] == "installed_modules"
    assert calls[0]["filters"] == [{"field": "name", "operator": "=", "value": "account"}]
    assert calls[0]["company_id"] is None


def test_operations_finance_read_forces_connection_company_and_rejects_extra_scope(
    seed, monkeypatch
):
    _operations_odoo_connection(seed["tenant_b"], company_id=73)
    calls = []
    _mock_operations_odoo(monkeypatch, calls)
    client = _client()
    _login(client, "b@example.com")

    response = client.post(
        "/api/v1/operations/finance/read",
        json={
            "tenant_id": str(seed["tenant_b"]),
            "service": "journal_items",
            "limit": 7,
            "offset": 3,
        },
        headers=_csrf(client),
    )

    assert response.status_code == 200
    assert calls == [
        {
            "base_url": "https://odoo.example.test",
            "database": "odoo",
            "transport": "xmlrpc",
            "login": "odoo-user",
            "secret": "secret",
            "environment": "development",
            "resource": "journal_items",
            "filters": None,
            "limit": 7,
            "offset": 3,
            "company_id": 73,
        }
    ]
    rejected = client.post(
        "/api/v1/operations/finance/read",
        json={
            "tenant_id": str(seed["tenant_b"]),
            "service": "journal_items",
            "company_id": 999,
        },
        headers=_csrf(client),
    )
    assert rejected.status_code == 422
    assert len(calls) == 1


def test_operations_endpoints_hide_cross_tenant_and_allow_superuser(seed, monkeypatch):
    _operations_odoo_connection(seed["tenant_a"])
    db = TestingSession()
    superuser = User(
        email="operations-superuser@example.com",
        full_name="Operations Superuser",
        password_hash=hash_password(PASSWORD),
        is_superuser=True,
    )
    db.add(superuser)
    db.commit()
    db.close()
    calls = []
    _mock_operations_odoo(monkeypatch, calls)

    member = _client()
    _login(member, "b@example.com")
    assert (
        member.get(f"/api/v1/operations/catalog?tenant_id={seed['tenant_a']}").status_code
        == 404
    )

    admin = _client()
    _login(admin, "operations-superuser@example.com")
    response = admin.get(f"/api/v1/operations/catalog?tenant_id={seed['tenant_a']}")
    assert response.status_code == 200
    assert calls and calls[0]["resource"] == "installed_modules"

def test_service_request_contract_rejects_browser_bypass_payloads(seed):
    client = _client()
    _login(client, "a@example.com")
    base = {
        "tenant_id": str(seed["tenant_a"]),
        "title": "Prepare payroll",
        "category": "human_resources",
        "priority": "medium",
    }

    cases = [
        base,
        {**base, "procedure_type": "prepare_payroll"},
        {
            **base,
            "procedure_type": "prepare_payroll",
            "request_data": {"period": "2026-08"},
        },
        {
            **base,
            "procedure_type": "prepare_payroll",
            "request_data": {
                "period": "2026-08",
                "details": "Review payroll",
                "unexpected": "not allowed",
            },
        },
        {
            **base,
            "procedure_type": "review_journal_entry",
            "request_data": {
                "reference": "JV-1",
                "period": "2026-08",
                "details": "Review entry",
            },
        },
    ]

    for payload in cases:
        response = client.post(
            "/api/v1/operations/tasks",
            json=payload,
            headers=_csrf(client),
        )
        assert response.status_code == 422

def test_hr_review_task_rejects_cross_tenant_connection(seed):
    db = TestingSession()
    connection = Connection(
        tenant_id=seed["tenant_b"],
        name="Foreign HR Odoo",
        provider="odoo",
        base_url="https://example.odoo.com",
        status="configured",
        is_active=True,
        last_test_status="success",
        odoo_company_id=99,
        created_by_user_id=seed["user_b"],
    )
    db.add(connection)
    db.commit()
    connection_id = connection.id
    db.close()

    client = _client()
    _login(client, "a@example.com")
    response = client.post(
        "/api/v1/operations/hr-review-tasks",
        json={
            "tenant_id": str(seed["tenant_a"]),
            "connection_id": str(connection_id),
            "resource": "employees_summary",
            "record_id": 1,
            "priority": "medium",
        },
        headers=_csrf(client),
    )
    assert response.status_code == 404
