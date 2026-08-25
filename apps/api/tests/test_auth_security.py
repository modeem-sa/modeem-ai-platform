"""Security tests for authentication and tenant isolation (Phase 2A)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.core.security import hash_password
from app.db.base import Base
from app.main import app
from app.models import AuditLog, Tenant, TenantMembership, User

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


app.dependency_overrides[deps.get_db] = override_get_db

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret-not-for-production-0123456789")
    from app.core.config import get_settings

    get_settings.cache_clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    get_settings.cache_clear()


@pytest.fixture()
def seed():
    db = TestingSession()
    tenant_a = Tenant(name="Tenant A", code="tenant-a")
    tenant_b = Tenant(name="Tenant B", code="tenant-b")
    user_a = User(
        email="a@example.com",
        full_name="User A",
        password_hash=hash_password(PASSWORD),
    )
    user_b = User(
        email="b@example.com",
        full_name="User B",
        password_hash=hash_password(PASSWORD),
    )
    inactive_user = User(
        email="inactive@example.com",
        full_name="Inactive",
        password_hash=hash_password(PASSWORD),
        is_active=False,
    )
    inactive_member = User(
        email="inactive-member@example.com",
        full_name="Inactive Member",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([tenant_a, tenant_b, user_a, user_b, inactive_user, inactive_member])
    db.flush()
    db.add_all(
        [
            TenantMembership(tenant_id=tenant_a.id, user_id=user_a.id, role="admin"),
            TenantMembership(tenant_id=tenant_b.id, user_id=user_b.id, role="member"),
            TenantMembership(
                tenant_id=tenant_a.id,
                user_id=inactive_member.id,
                role="member",
                is_active=False,
            ),
        ]
    )
    db.commit()
    ids = {
        "tenant_a": tenant_a.id,
        "tenant_b": tenant_b.id,
        "user_a": user_a.id,
        "user_b": user_b.id,
    }
    db.close()
    return ids


def _client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("modeem_csrf")
    return {"X-CSRF-Token": token} if token else {}


def test_correct_password_login_succeeds(seed):
    client = _client()
    res = _login(client, "a@example.com")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "a@example.com"
    assert body["current_tenant"]["name"] == "Tenant A"
    assert "modeem_session" in res.cookies


def test_incorrect_password_fails_generically(seed):
    client = _client()
    res = _login(client, "a@example.com", "wrong-password")
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"
    # No hint about whether the account exists.
    res2 = _login(client, "nobody@example.com", "wrong-password")
    assert res2.status_code == 401
    assert res2.json()["detail"] == "Invalid email or password"


def test_me_requires_authentication(seed):
    client = _client()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_protected_api_rejects_unauthenticated(seed):
    client = _client()
    assert client.get("/api/v1/tenant-context").status_code == 401


def test_tenant_a_user_cannot_access_tenant_b(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/tenant",
        json={"tenant_id": str(seed["tenant_b"])},
        headers=_csrf(client),
    )
    assert res.status_code == 403


def test_inactive_membership_rejected(seed):
    client = _client()
    res = _login(client, "inactive-member@example.com")
    assert res.status_code == 200
    # Only inactive membership exists → no tenant context.
    res2 = client.get("/api/v1/tenant-context")
    assert res2.status_code == 403


def test_inactive_user_rejected(seed):
    client = _client()
    res = _login(client, "inactive@example.com")
    assert res.status_code == 401


def test_valid_member_accesses_their_tenant(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.get("/api/v1/tenant-context")
    assert res.status_code == 200
    body = res.json()
    assert body["tenant_id"] == str(seed["tenant_a"])
    assert body["tenant_name"] == "Tenant A"
    assert body["role"] == "admin"


def test_logout_invalidates_browser_auth(seed):
    client = _client()
    _login(client, "a@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    res = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert res.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_hash_never_returned(seed):
    client = _client()
    res = _login(client, "a@example.com")
    text = res.text.lower()
    assert "password" not in text
    assert "argon2" not in text
    me = client.get("/api/v1/auth/me")
    assert "password" not in me.text.lower()


def test_audit_log_created_for_login_events(seed):
    client = _client()
    _login(client, "a@example.com")
    _login(client, "a@example.com", "wrong")
    db = TestingSession()
    actions = [a.action for a in db.query(AuditLog).all()]
    db.close()
    assert "auth.login_success" in actions
    assert "auth.login_failed" in actions


def test_change_password_success_and_login_with_new_password(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-Sup3r-secret"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    assert res.json() == {"status": "password_changed"}
    # Old password no longer works; new one does.
    fresh = _client()
    assert _login(fresh, "a@example.com", PASSWORD).status_code == 401
    assert _login(fresh, "a@example.com", "new-Sup3r-secret").status_code == 200
    db = TestingSession()
    actions = [a.action for a in db.query(AuditLog).all()]
    db.close()
    assert "auth.password_changed" in actions


def test_change_password_wrong_current_password(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "new-Sup3r-secret"},
        headers=_csrf(client),
    )
    assert res.status_code == 400
    # Original password still works.
    fresh = _client()
    assert _login(fresh, "a@example.com", PASSWORD).status_code == 200
    db = TestingSession()
    actions = [a.action for a in db.query(AuditLog).all()]
    db.close()
    assert "auth.password_change_failed" in actions


def test_change_password_requires_csrf(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-Sup3r-secret"},
    )
    assert res.status_code == 403


def test_change_password_requires_authentication(seed):
    client = _client()
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-Sup3r-secret"},
    )
    assert res.status_code in (401, 403)


def test_change_password_rejects_short_new_password(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=_csrf(client),
    )
    assert res.status_code == 422


def test_change_password_rejects_same_password(seed):
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=_csrf(client),
    )
    assert res.status_code == 400


def test_tenant_uuid_manipulation_cannot_bypass_membership(seed):
    client = _client()
    _login(client, "a@example.com")
    # Try switching to a random UUID and to tenant B directly.
    for tid in (uuid.uuid4(), seed["tenant_b"]):
        res = client.post(
            "/api/v1/auth/tenant", json={"tenant_id": str(tid)}, headers=_csrf(client)
        )
        assert res.status_code == 403
    # Context is still tenant A.
    res = client.get("/api/v1/tenant-context")
    assert res.json()["tenant_id"] == str(seed["tenant_a"])
