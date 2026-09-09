"""Focused membership-administration contract tests (Task 53)."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Tenant, TenantMembership, User
from tests.test_auth_security import PASSWORD, TestingSession, engine


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["modeem_csrf"]}


def _login(client: TestClient, email: str):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def _membership(db, tenant, user, role, **kwargs):
    member = TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role, **kwargs)
    db.add(member)
    return member


def _fixture_data():
    db = TestingSession()
    tenant_a = Tenant(name="Permissions A", code="permissions-a")
    tenant_b = Tenant(name="Permissions B", code="permissions-b")
    users = {
        "owner": User(email="owner-permissions@example.com", full_name="Owner", password_hash=hash_password(PASSWORD)),
        "manager": User(email="manager-permissions@example.com", full_name="Manager", password_hash=hash_password(PASSWORD)),
        "scoped": User(email="scoped-manager@example.com", full_name="Scoped Manager", password_hash=hash_password(PASSWORD)),
        "other": User(email="other-tenant@example.com", full_name="Other Tenant", password_hash=hash_password(PASSWORD)),
        "existing": User(email="existing-account@example.com", full_name="Existing Account", password_hash=hash_password(PASSWORD)),
        "target": User(email="target-account@example.com", full_name="Target Account", password_hash=hash_password(PASSWORD)),
    }
    db.add_all([tenant_a, tenant_b, *users.values()])
    db.flush()
    _membership(db, tenant_a, users["owner"], "owner")
    _membership(db, tenant_a, users["manager"], "manager")
    _membership(db, tenant_a, users["scoped"], "manager", service_scope_json='["tenant_memberships"]')
    _membership(db, tenant_b, users["other"], "owner")
    db.commit()
    result = {"tenant_a": tenant_a.id, "tenant_b": tenant_b.id}
    result.update({name: user.id for name, user in users.items()})
    db.close()
    return result


def _create_existing(client, data, *, role="member", tenants=None, **extra):
    tenants = tenants or [data["tenant_a"]]
    response = client.post(
        "/api/v1/permissions",
        json={
            "user_id": str(data["existing"]),
            "memberships": [
                {"tenant_id": str(tenant), "role": role, **extra} for tenant in tenants
            ],
        },
        headers=_csrf(client),
    )
    return response


def test_owner_can_administer_and_existing_visible_accounts_can_be_assigned(_fresh_db):
    data = _fixture_data()
    db = TestingSession()
    _membership(db, db.get(Tenant, data["tenant_a"]), db.get(User, data["existing"]), "member")
    _membership(db, db.get(Tenant, data["tenant_b"]), db.get(User, data["owner"]), "owner")
    db.commit()
    db.close()
    client = TestClient(app)
    _login(client, "owner-permissions@example.com")

    listing = client.get("/api/v1/permissions")
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()["tenants"]} == {
        str(data["tenant_a"]), str(data["tenant_b"])
    }
    assert any(item["id"] == str(data["existing"]) for item in listing.json()["users"])

    response = _create_existing(client, data, role="member", tenants=[data["tenant_b"]])
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == str(data["existing"])


def test_manager_without_membership_scope_is_denied_and_cross_tenant_is_hidden(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "manager-permissions@example.com")
    assert client.get("/api/v1/permissions").status_code == 403
    denied = _create_existing(client, data)
    assert denied.status_code == 404

    owner = TestClient(app)
    _login(owner, "owner-permissions@example.com")
    assert owner.get("/api/v1/permissions").status_code == 200
    cross = owner.post(
        "/api/v1/permissions",
        json={"user_id": str(data["existing"]), "memberships": [{"tenant_id": str(data["tenant_b"]), "role": "member"}]},
        headers=_csrf(owner),
    )
    assert cross.status_code == 404


def test_authorized_manager_can_assign_but_not_owner_or_admin(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "scoped-manager@example.com")
    success = _create_existing(
        client, data, odoo_module_scope=[], service_scope=[]
    )
    assert success.status_code == 201, success.text
    for role in ("owner", "admin"):
        response = _create_existing(client, data, role=role)
        assert response.status_code in (403, 409)


def test_multi_tenant_assignment_and_scopes_are_persisted_and_returned(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "owner-permissions@example.com")
    # Give the actor authority in both tenants, then assign one visible
    # account to both in a single request.
    db = TestingSession()
    _membership(db, db.get(Tenant, data["tenant_b"]), db.get(User, data["owner"]), "owner")
    db.commit()
    db.close()
    multi = _create_existing(
        client,
        data,
        tenants=[data["tenant_a"], data["tenant_b"]],
        odoo_module_scope=["hr", "account", "hr"],
        service_scope=["financial"],
    )
    assert multi.status_code == 201, multi.text

    rows = [item for item in client.get("/api/v1/permissions").json()["memberships"] if item["user_id"] == str(data["existing"])]
    assert len(rows) == 2
    assert all(row["odoo_module_scope"] == ["account", "hr"] for row in rows)
    assert all(row["service_scope"] == ["financial"] for row in rows)


def test_duplicate_membership_returns_conflict(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "owner-permissions@example.com")
    assert _create_existing(client, data).status_code == 201
    assert _create_existing(client, data).status_code == 409


def test_legacy_null_scopes_are_preserved(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "owner-permissions@example.com")
    created = _create_existing(client, data)
    assert created.status_code == 201
    membership = created.json()["memberships"][0]["id"]
    response = client.patch(
        f"/api/v1/permissions/memberships/{membership}",
        json={"role": "viewer"},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    assert response.json()["odoo_module_scope"] is None
    assert response.json()["service_scope"] is None


def test_self_lockout_requires_alternative_manager_and_last_owner_is_protected(_fresh_db):
    data = _fixture_data()
    db = TestingSession()
    tenant_c = Tenant(name="Permissions C", code="permissions-c")
    db.add(tenant_c)
    db.flush()
    _membership(db, tenant_c, db.get(User, data["scoped"]), "manager", service_scope_json='["tenant_memberships"]')
    db.commit()
    tenant_c_membership = db.query(TenantMembership).filter_by(tenant_id=tenant_c.id, user_id=data["scoped"]).one().id
    db.close()
    client = TestClient(app)
    _login(client, "scoped-manager@example.com")
    blocked = client.patch(
        f"/api/v1/permissions/memberships/{tenant_c_membership}",
        json={"service_scope": []},
        headers=_csrf(client),
    )
    assert blocked.status_code == 409

    owner = TestClient(app)
    _login(owner, "owner-permissions@example.com")
    owner_id = TestingSession().query(TenantMembership).filter_by(user_id=data["owner"]).one().id
    demote = owner.patch(
        f"/api/v1/permissions/memberships/{owner_id}",
        json={"role": "member"},
        headers=_csrf(owner),
    )
    assert demote.status_code == 409
    deactivate = owner.patch(
        f"/api/v1/permissions/memberships/{owner_id}",
        json={"is_active": False},
        headers=_csrf(owner),
    )
    assert deactivate.status_code == 409


def test_audits_distinguish_new_user_from_existing_user(_fresh_db):
    data = _fixture_data()
    client = TestClient(app)
    _login(client, "owner-permissions@example.com")
    assert _create_existing(client, data).status_code == 201
    new = client.post(
        "/api/v1/permissions",
        json={
            "email": "brand-new-permissions@example.com",
            "full_name": "Brand New",
            "password": PASSWORD,
            "memberships": [{"tenant_id": str(data["tenant_a"]), "role": "member"}],
        },
        headers=_csrf(client),
    )
    assert new.status_code == 201, new.text
    db = TestingSession()
    actions = [row.action for row in db.scalars(select(AuditLog)).all()]
    db.close()
    assert actions.count("membership.created") == 2
    assert actions.count("user.created") == 1