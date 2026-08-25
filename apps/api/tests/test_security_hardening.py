"""Tests for the Phase 2A security hardening round."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import (
    hash_password,
    validate_auth_secret_for_production,
    verify_dummy_password,
)
from app.models import Tenant, TenantMembership, User
from tests.test_auth_security import (
    PASSWORD,
    TestingSession,
    _client,
    _csrf,
    _fresh_db,  # noqa: F401 — autouse fixture reuse
    _login,
    seed,  # noqa: F401 — fixture reuse
)


@pytest.fixture()
def multi_tenant_user(seed):  # noqa: F811
    db = TestingSession()
    user = User(
        email="multi@example.com",
        full_name="Multi Tenant",
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.flush()
    db.add_all(
        [
            TenantMembership(tenant_id=seed["tenant_a"], user_id=user.id, role="member"),
            TenantMembership(tenant_id=seed["tenant_b"], user_id=user.id, role="viewer"),
        ]
    )
    db.commit()
    db.close()
    return seed


# --- Multi-tenant selection ---------------------------------------------


def test_single_membership_auto_selected(seed):  # noqa: F811
    client = _client()
    res = _login(client, "a@example.com")
    assert res.status_code == 200
    assert res.json()["current_tenant"]["name"] == "Tenant A"


def test_multiple_memberships_not_auto_selected(multi_tenant_user):
    client = _client()
    res = _login(client, "multi@example.com")
    assert res.status_code == 200
    assert res.json()["current_tenant"] is None
    # Tenant-scoped endpoint demands explicit selection.
    ctx = client.get("/api/v1/tenant-context")
    assert ctx.status_code == 403
    assert ctx.json()["detail"] == "Tenant selection required"


def test_explicit_tenant_selection_works(multi_tenant_user):
    client = _client()
    _login(client, "multi@example.com")
    res = client.post(
        "/api/v1/auth/tenant",
        json={"tenant_id": str(multi_tenant_user["tenant_b"])},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    assert res.json()["current_tenant"]["name"] == "Tenant B"
    ctx = client.get("/api/v1/tenant-context")
    assert ctx.status_code == 200
    assert ctx.json()["tenant_name"] == "Tenant B"


# --- Role integrity -------------------------------------------------------


def test_invalid_role_rejected_at_model_level(seed):  # noqa: F811
    with pytest.raises(ValueError, match="Invalid role"):
        TenantMembership(
            tenant_id=seed["tenant_a"], user_id=seed["user_a"], role="superadmin"
        )


def test_invalid_role_rejected_by_database_check(seed):  # noqa: F811
    db = TestingSession()
    tenant = db.query(Tenant).first()
    user = db.query(User).filter(User.email == "b@example.com").one()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO tenant_memberships (id, tenant_id, user_id, role, is_active,"
                " created_at) VALUES (:id, :t, :u, 'hacker', 1, CURRENT_TIMESTAMP)"
            ),
            {"id": "11111111-1111-1111-1111-111111111111", "t": str(tenant.id).replace("-", ""), "u": str(user.id).replace("-", "")},
        )
        db.commit()
    db.rollback()
    db.close()


# --- Login timing hardening ----------------------------------------------


def test_unknown_and_known_login_paths_both_verify(seed, monkeypatch):  # noqa: F811
    import app.api.auth as auth_module

    calls = {"dummy": 0, "real": 0}
    real_verify = auth_module.verify_password

    def spy_dummy(pw):
        calls["dummy"] += 1
        return verify_dummy_password(pw)

    def spy_real(h, pw):
        calls["real"] += 1
        return real_verify(h, pw)

    monkeypatch.setattr(auth_module, "verify_dummy_password", spy_dummy)
    monkeypatch.setattr(auth_module, "verify_password", spy_real)

    client = _client()
    assert _login(client, "ghost@example.com", "whatever").status_code == 401
    assert _login(client, "a@example.com").status_code == 200
    assert calls["dummy"] == 1
    assert calls["real"] == 1


def test_pathological_password_length_rejected(seed):  # noqa: F811
    client = _client()
    res = _login(client, "a@example.com", "x" * 10_000)
    assert res.status_code == 422


# --- CSRF -----------------------------------------------------------------


def test_missing_csrf_rejects_state_changing_requests(seed):  # noqa: F811
    client = _client()
    _login(client, "a@example.com")
    res = client.post("/api/v1/auth/tenant", json={"tenant_id": str(seed["tenant_a"])})
    assert res.status_code == 403
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 403


def test_invalid_csrf_rejected(seed):  # noqa: F811
    client = _client()
    _login(client, "a@example.com")
    res = client.post(
        "/api/v1/auth/tenant",
        json={"tenant_id": str(seed["tenant_a"])},
        headers={"X-CSRF-Token": "forged-token"},
    )
    assert res.status_code == 403


def test_valid_csrf_allows_tenant_switch_and_logout(seed):  # noqa: F811
    client = _client()
    res = _login(client, "a@example.com")
    assert "modeem_csrf" in res.cookies
    ok = client.post(
        "/api/v1/auth/tenant",
        json={"tenant_id": str(seed["tenant_a"])},
        headers=_csrf(client),
    )
    assert ok.status_code == 200
    out = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert out.status_code == 200


def test_logout_clears_both_cookies(seed):  # noqa: F811
    client = _client()
    _login(client, "a@example.com")
    res = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert res.status_code == 200
    assert not client.cookies.get("modeem_session")
    assert not client.cookies.get("modeem_csrf")


# --- Production AUTH_SECRET safety -----------------------------------------


def test_production_rejects_missing_auth_secret():
    with pytest.raises(RuntimeError, match="explicitly configured"):
        validate_auth_secret_for_production("production", "")


def test_production_rejects_weak_auth_secret():
    with pytest.raises(RuntimeError, match="at least"):
        validate_auth_secret_for_production("production", "short-secret")


def test_production_accepts_strong_auth_secret():
    validate_auth_secret_for_production("production", "x" * 48)


def test_development_allows_fallback():
    validate_auth_secret_for_production("development", "")
