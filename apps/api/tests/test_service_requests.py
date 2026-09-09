"""Security and lifecycle coverage for customer service requests."""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import service_requests as service_requests_api
from app.core.security import hash_password
from app.main import app
from app.models import (
    OperationTask,
    ServiceRequest,
    ServiceRequestAttachment,
    TenantMembership,
    User,
)
from tests.test_auth_security import PASSWORD, TestingSession


def _client(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["modeem_csrf"]}


def _add_user(email: str, name: str, tenant_id: uuid.UUID, role: str) -> uuid.UUID:
    db = TestingSession()
    user = User(
        email=email,
        full_name=name,
        password_hash=hash_password(PASSWORD),
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=role))
    db.commit()
    user_id = user.id
    db.close()
    return user_id


def _service_seed(seed):
    customer_id = _add_user(
        "customer@example.com", "Customer", seed["tenant_a"], "customer"
    )
    other_customer_id = _add_user(
        "other-customer@example.com", "Other Customer", seed["tenant_a"], "customer"
    )
    employee_id = _add_user(
        "employee@example.com", "Employee", seed["tenant_a"], "member"
    )
    viewer_id = _add_user(
        "viewer@example.com", "Viewer", seed["tenant_a"], "viewer"
    )
    return {
        "customer_id": customer_id,
        "other_customer_id": other_customer_id,
        "employee_id": employee_id,
        "viewer_id": viewer_id,
    }


def _create_request(client: TestClient, tenant_id: uuid.UUID, **changes) -> dict:
    body = {
        "tenant_id": str(tenant_id),
        "subject": "تثبيت فاتورة المورد",
        "description": "يرجى مراجعة الملف المرفق وتثبيت الفاتورة.",
        "priority": "medium",
    }
    body.update(changes)
    response = client.post(
        "/api/v1/service-requests", json=body, headers=_csrf(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign(
    client: TestClient, request_id: str, employee_id: uuid.UUID, version: int
) -> dict:
    response = client.post(
        f"/api/v1/service-requests/{request_id}/assignment",
        json={
            "assigned_employee_id": str(employee_id),
            "expected_version": version,
        },
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_customer_create_list_and_detail_are_requester_isolated(seed):
    ids = _service_seed(seed)
    customer = _client("customer@example.com")
    created = _create_request(customer, seed["tenant_a"])

    own_list = customer.get(
        f"/api/v1/service-requests?tenant_id={seed['tenant_a']}"
    )
    assert own_list.status_code == 200
    assert [item["id"] for item in own_list.json()["items"]] == [created["id"]]

    other_customer = _client("other-customer@example.com")
    assert (
        other_customer.get(f"/api/v1/service-requests/{created['id']}").status_code
        == 404
    )
    assert (
        other_customer.get(
            f"/api/v1/service-requests?tenant_id={seed['tenant_a']}"
        ).json()["items"]
        == []
    )

    employee = _client("employee@example.com")
    denied = employee.post(
        "/api/v1/service-requests",
        json={
            "tenant_id": str(seed["tenant_a"]),
            "subject": "Not a customer",
            "description": "Employees cannot impersonate portal customers.",
        },
        headers=_csrf(employee),
    )
    assert denied.status_code == 403
    assert created["requester_id"] == str(ids["customer_id"])


def test_employee_inbox_assignment_detail_messages_and_status(seed):
    ids = _service_seed(seed)
    customer = _client("customer@example.com")
    created = _create_request(customer, seed["tenant_a"])
    employee = _client("employee@example.com")
    manager = _client("a@example.com")

    assert (
        employee.get(
            f"/api/v1/service-requests/inbox?tenant_id={seed['tenant_a']}"
        ).json()["items"]
        == []
    )
    all_items = manager.get(
        f"/api/v1/service-requests/inbox?tenant_id={seed['tenant_a']}&include_all=true"
    )
    assert [item["id"] for item in all_items.json()["items"]] == [created["id"]]

    assigned = _assign(
        manager, created["id"], ids["employee_id"], created["version"]
    )
    inbox = employee.get(
        f"/api/v1/service-requests/inbox?tenant_id={seed['tenant_a']}"
    )
    assert [item["id"] for item in inbox.json()["items"]] == [created["id"]]

    message = employee.post(
        f"/api/v1/service-requests/{created['id']}/messages",
        json={"body": "تم استلام الطلب وبدأت المراجعة."},
        headers=_csrf(employee),
    )
    assert message.status_code == 200
    assert message.json()["messages"][0]["author_name"] == "Employee"

    stale = employee.post(
        f"/api/v1/service-requests/{created['id']}/status",
        json={"status": "in_progress", "expected_version": assigned["version"]},
        headers=_csrf(employee),
    )
    assert stale.status_code == 409
    current = message.json()
    changed = employee.post(
        f"/api/v1/service-requests/{created['id']}/status",
        json={"status": "in_progress", "expected_version": current["version"]},
        headers=_csrf(employee),
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "in_progress"
    assert any(event["event"] == "assigned" for event in changed.json()["events"])

    viewer = _client("viewer@example.com")
    assert (
        viewer.get(
            f"/api/v1/service-requests/inbox?tenant_id={seed['tenant_a']}"
        ).json()["items"]
        == []
    )


def test_arabic_attachment_metadata_download_and_access_control(seed, tmp_path, monkeypatch):
    _service_seed(seed)
    monkeypatch.setattr(
        service_requests_api,
        "get_settings",
        lambda: SimpleNamespace(service_request_upload_dir=str(tmp_path)),
    )
    customer = _client("customer@example.com")
    created = _create_request(customer, seed["tenant_a"])
    uploaded = customer.post(
        f"/api/v1/service-requests/{created['id']}/attachments",
        files={"file": ("فاتورة-سبتمبر.pdf", b"%PDF-1.7\nModeem", "application/pdf")},
        headers=_csrf(customer),
    )
    assert uploaded.status_code == 200, uploaded.text
    attachment = uploaded.json()
    detail = customer.get(f"/api/v1/service-requests/{created['id']}").json()
    assert detail["attachments"][0]["filename"] == "فاتورة-سبتمبر.pdf"
    downloaded = customer.get(
        f"/api/v1/service-requests/{created['id']}/attachments/{attachment['id']}"
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")

    spoofed = customer.post(
        f"/api/v1/service-requests/{created['id']}/attachments",
        files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
        headers=_csrf(customer),
    )
    assert spoofed.status_code == 422

    other = _client("other-customer@example.com")
    assert (
        other.get(
            f"/api/v1/service-requests/{created['id']}/attachments/{attachment['id']}"
        ).status_code
        == 404
    )

    db = TestingSession()
    stored = db.query(ServiceRequestAttachment).one()
    assert stored.sha256 == attachment["sha256"]
    assert (tmp_path / stored.storage_key).is_file()
    db.close()


def test_live_modules_classification_dispatch_and_idempotent_task_link(seed, monkeypatch):
    ids = _service_seed(seed)

    def live_modules(_db, _user, _tenant_id, *, search=None, limit=50, offset=0):
        names = ["account", "hr_payroll"]
        records = [
            {
                "id": index + 1,
                "name": name,
                "shortdesc": name,
                "installed_version": "18.0",
                "application": True,
                "category_id": False,
            }
            for index, name in enumerate(names)
            if search is None or name == search
        ]
        return {
            "resource": "installed_modules",
            "records": records[offset : offset + limit],
            "returned_count": len(records[offset : offset + limit]),
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "next_offset": None,
        }

    monkeypatch.setattr(service_requests_api, "_live_modules", live_modules)
    customer = _client("customer@example.com")
    created = _create_request(
        customer, seed["tenant_a"], requested_module="account"
    )
    modules = customer.get(
        f"/api/v1/service-requests/modules?tenant_id={seed['tenant_a']}"
    )
    assert modules.status_code == 200
    account = next(item for item in modules.json()["records"] if item["name"] == "account")
    assert account["capabilities"] == {
        "installed": True,
        "accepts_requests": True,
        "read_supported": True,
        "execution_supported": True,
    }

    manager = _client("a@example.com")
    assigned = _assign(
        manager, created["id"], ids["employee_id"], created["version"]
    )
    employee = _client("employee@example.com")
    dispatched = employee.post(
        f"/api/v1/service-requests/{created['id']}/dispatch",
        json={
            "workflow_key": "finance.overdue_invoice_followup",
            "workflow_input": {"note": "راجع الفواتير المستحقة"},
            "expected_version": assigned["version"],
        },
        headers=_csrf(employee),
    )
    assert dispatched.status_code == 200, dispatched.text
    body = dispatched.json()
    assert body["automation_status"] == "queued"
    assert body["operation_task_id"]

    repeated = employee.post(
        f"/api/v1/service-requests/{created['id']}/dispatch",
        json={
            "workflow_key": "finance.overdue_invoice_followup",
            "workflow_input": {"note": "must not create another task"},
            "expected_version": body["version"],
        },
        headers=_csrf(employee),
    )
    assert repeated.status_code == 200
    assert repeated.json()["operation_task_id"] == body["operation_task_id"]

    db = TestingSession()
    request = db.get(ServiceRequest, uuid.UUID(created["id"]))
    tasks = db.query(OperationTask).filter_by(source_type="service_request").all()
    assert len(tasks) == 1
    assert request.operation_task_id == tasks[0].id
    assert tasks[0].source_reference == request.public_reference
    db.close()


def test_dispatch_rejects_customer_unknown_unavailable_and_missing_module(seed, monkeypatch):
    ids = _service_seed(seed)
    customer = _client("customer@example.com")
    created = _create_request(customer, seed["tenant_a"])
    assert (
        customer.post(
            f"/api/v1/service-requests/{created['id']}/dispatch",
            json={
                "workflow_key": "finance.overdue_invoice_followup",
                "expected_version": created["version"],
            },
            headers=_csrf(customer),
        ).status_code
        == 404
    )
    manager = _client("a@example.com")
    assigned = _assign(
        manager, created["id"], ids["employee_id"], created["version"]
    )
    employee = _client("employee@example.com")
    unknown = employee.post(
        f"/api/v1/service-requests/{created['id']}/dispatch",
        json={"workflow_key": "odoo.arbitrary_call", "expected_version": assigned["version"]},
        headers=_csrf(employee),
    )
    assert unknown.status_code == 422
    unavailable = employee.post(
        f"/api/v1/service-requests/{created['id']}/dispatch",
        json={"workflow_key": "hr.payroll_report", "expected_version": assigned["version"]},
        headers=_csrf(employee),
    )
    assert unavailable.status_code == 409

    monkeypatch.setattr(
        service_requests_api,
        "_live_modules",
        lambda *_args, **_kwargs: {"records": []},
    )
    missing = employee.post(
        f"/api/v1/service-requests/{created['id']}/dispatch",
        json={
            "workflow_key": "finance.overdue_invoice_followup",
            "expected_version": assigned["version"],
        },
        headers=_csrf(employee),
    )
    assert missing.status_code == 409