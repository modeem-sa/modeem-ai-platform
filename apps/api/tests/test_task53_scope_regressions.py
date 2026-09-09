"""Regression coverage for fixed service/module authorization boundaries."""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import require_odoo_module_scope, require_service_scope
from app.api.invoices import _require_financial_scope
from app.api.connections import _require_read_scopes
from app.api.operations import _require_category_scope, _require_workflow_scope
from app.api.service_requests import _require_request_scope
from app.api.permissions import SCOPE_MODULES, SCOPE_SERVICES
from app.core.security import hash_password
from app.main import app
from app.models import InvoiceDocument, Tenant, TenantMembership, User
from app.operations.automation_catalog import get_workflow
from tests.test_auth_security import PASSWORD, TestingSession


def _tenant_user(*, module_scope=None, service_scope=None):
    db = TestingSession()
    tenant = Tenant(name=f"Scope {uuid.uuid4().hex[:8]}", code=uuid.uuid4().hex[:8])
    user = User(
        email=f"scope-{uuid.uuid4().hex}@example.com",
        full_name="Scope tester",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([tenant, user])
    db.flush()
    db.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role="member",
            odoo_module_scope_json=module_scope,
            service_scope_json=service_scope,
        )
    )
    db.commit()
    result = tenant.id, user.email
    db.close()
    return result


def test_grantable_modules_are_catalog_and_resource_derived():
    from app.api.deps import RESOURCE_MODULES
    from app.operations.automation_catalog import CATALOG

    expected = set(RESOURCE_MODULES.values()) | {
        item.required_odoo_module for item in CATALOG if item.required_odoo_module
    }
    assert set(SCOPE_MODULES) == expected
    assert "purchase" in SCOPE_MODULES
    assert "purchasing" in SCOPE_SERVICES


@pytest.mark.parametrize(
    ("module_scope", "service_scope"),
    [
        ('["hr"]', '["financial"]'),
        ("[]", "[]"),
    ],
)
def test_invoice_scope_requires_both_fixed_capabilities(_fresh_db, module_scope, service_scope):
    tenant_id, email = _tenant_user(module_scope=module_scope, service_scope=service_scope)
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    with pytest.raises(HTTPException) as error:
        _require_financial_scope(db, user, tenant_id)
    assert error.value.status_code == 403
    db.close()


def test_null_scopes_allow_invoice_scope_and_automation(_fresh_db):
    tenant_id, email = _tenant_user()
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    _require_financial_scope(db, user, tenant_id)
    workflow = get_workflow("purchasing.purchase_request_review")
    _require_workflow_scope(db, user, tenant_id, workflow)
    _require_category_scope(db, user, tenant_id, "purchasing")
    db.close()


def test_restricted_automation_and_recurring_capabilities_are_denied(_fresh_db):
    tenant_id, email = _tenant_user(module_scope='["account"]', service_scope='["financial"]')
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    workflow = get_workflow("purchasing.purchase_request_review")
    with pytest.raises(HTTPException):
        _require_workflow_scope(db, user, tenant_id, workflow)
    with pytest.raises(HTTPException):
        _require_category_scope(db, user, tenant_id, "purchasing")
    db.close()


def test_purchase_scope_reaches_module_check_not_service_scope_rejection(_fresh_db):
    tenant_id, email = _tenant_user(module_scope='["account"]', service_scope='["purchasing"]')
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    workflow = get_workflow("purchasing.purchase_request_review")
    with pytest.raises(HTTPException) as error:
        _require_workflow_scope(db, user, tenant_id, workflow)
    # The fixed purchasing service was accepted; only purchase module is absent.
    assert error.value.detail == "Odoo module scope does not permit this resource"
    db.close()


def test_empty_and_unrelated_odoo_reads_are_denied_null_is_allowed(_fresh_db):
    tenant_id, email = _tenant_user(module_scope="[]", service_scope="[]")
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    with pytest.raises(HTTPException):
        require_service_scope(db, user, tenant_id, "financial")
    with pytest.raises(HTTPException):
        require_odoo_module_scope(db, user, tenant_id, "account")
    db.close()

    tenant_id, email = _tenant_user()
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    require_service_scope(db, user, tenant_id, "financial")
    require_odoo_module_scope(db, user, tenant_id, "account")
    db.close()


def _login(client: TestClient, email: str) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_invoice_automation_and_recurring_endpoints_observe_scopes(_fresh_db):
    tenant_id, email = _tenant_user(module_scope="[]", service_scope="[]")
    client = TestClient(app)
    _login(client, email)
    tenant = str(tenant_id)
    assert client.get(f"/api/v1/invoices?tenant_id={tenant}").status_code == 403
    assert client.get(f"/api/v1/operations/automation/catalog?tenant_id={tenant}").status_code == 200
    assert client.get("/api/v1/operations/recurring-templates").status_code == 200

    tenant_id, email = _tenant_user()
    client = TestClient(app)
    _login(client, email)
    tenant = str(tenant_id)
    assert client.get(f"/api/v1/invoices?tenant_id={tenant}").status_code == 200
    # NULL legacy scopes expose all fixed workflows and recurring templates.
    catalog = client.get(f"/api/v1/operations/automation/catalog?tenant_id={tenant}")
    assert catalog.status_code == 200
    assert catalog.json()["workflows"]


@pytest.mark.parametrize(
    ("resource", "service"),
    [
        ("customers", "administrative"),
        ("beneficiaries_summary", "administrative"),
        ("countries", "administrative"),
        ("companies", "administrative"),
        ("installed_modules", "administrative"),
        ("invoices", "financial"),
        ("employees_summary", "human_resources"),
    ],
)
def test_every_preview_resource_requires_its_server_owned_service(_fresh_db, resource, service):
    tenant_id, email = _tenant_user(module_scope=None, service_scope="[]")
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    with pytest.raises(HTTPException) as error:
        _require_read_scopes(db, user, tenant_id, resource)
    assert error.value.status_code == 403
    assert service in {"administrative", "financial", "human_resources"}
    db.close()


def test_service_request_scope_maps_module_and_null_legacy_access(_fresh_db):
    tenant_id, email = _tenant_user(module_scope='["purchase"]', service_scope='["financial"]')
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    with pytest.raises(HTTPException) as error:
        _require_request_scope(db, user, tenant_id, "purchase")
    assert error.value.detail == "Service scope does not permit this operation"
    db.close()

    tenant_id, email = _tenant_user()
    db = TestingSession()
    user = db.query(User).filter_by(email=email).one()
    _require_request_scope(db, user, tenant_id, "purchase")
    db.close()


def test_inventory_offset_is_resource_specific():
    from app.integrations.odoo.reader import ReadPolicyError, _validate_pagination
    from app.integrations.odoo.read_policies import get_policy
    from app.schemas.odoo_read import ReadPreviewRequest

    assert ReadPreviewRequest(resource="installed_modules", offset=100000).offset == 100000
    _validate_pagination(get_policy("installed_modules"), 25, 100000)
    with pytest.raises(ReadPolicyError, match="offset out of range"):
        _validate_pagination(get_policy("beneficiaries_summary"), 25, 1001)


def test_customer_is_denied_every_invoice_route_with_null_scopes(_fresh_db):
    db = TestingSession()
    tenant = Tenant(name="Customer invoice boundary", code="customer-invoice-boundary")
    customer = User(
        email="invoice-customer@example.com",
        full_name="Invoice Customer",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([tenant, customer])
    db.flush()
    db.add(TenantMembership(tenant_id=tenant.id, user_id=customer.id, role="customer"))
    invoice = InvoiceDocument(
        tenant_id=tenant.id,
        uploaded_by_user_id=customer.id,
        filename="private-invoice.pdf",
        storage_key=f"{tenant.id}/{uuid.uuid4()}.pdf",
        content_type="application/pdf",
        file_size=5,
        sha256="a" * 64,
        status="submitted",
        version=1,
        idempotency_marker=f"invoice-{uuid.uuid4().hex}",
    )
    db.add(invoice)
    db.commit()
    tenant_id, invoice_id, customer_email = tenant.id, invoice.id, customer.email
    db.close()

    client = TestClient(app)
    _login(client, customer_email)
    csrf = {"X-CSRF-Token": client.cookies["modeem_csrf"]}
    review = {
        "invoice_type": "customer",
        "partner_id": 1,
        "invoice_date": "2026-01-01",
        "lines": [{"description": "Line", "quantity": 1, "unit_price": 1}],
        "expected_version": 1,
    }
    calls = [
        client.get(f"/api/v1/invoices?tenant_id={tenant_id}"),
        client.get(f"/api/v1/invoices/{invoice_id}"),
        client.post(
            "/api/v1/invoices/upload",
            data={"tenant_id": str(tenant_id)},
            files={"file": ("new.pdf", b"%PDF-", "application/pdf")},
            headers=csrf,
        ),
        client.put(f"/api/v1/invoices/{invoice_id}", json=review, headers=csrf),
        client.post(f"/api/v1/invoices/{invoice_id}/submit", json={"expected_version": 1}, headers=csrf),
        client.post(f"/api/v1/invoices/{invoice_id}/reject", json={"expected_version": 1, "note": "No"}, headers=csrf),
        client.post(
            f"/api/v1/invoices/{invoice_id}/approve",
            json={"expected_version": 1, "expected_hash": "b" * 64},
            headers=csrf,
        ),
        client.get(f"/api/v1/invoices/{invoice_id}/download"),
    ]
    assert all(response.status_code == 403 for response in calls)
    assert all("private-invoice.pdf" not in response.text for response in calls)