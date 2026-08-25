"""Tests for login rate limiting (brute-force protection)."""

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
from app.services.rate_limit import LoginRateLimiter, login_rate_limiter

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


PASSWORD = "correct-horse-battery"
EMAIL = "rl@example.com"


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret-not-for-production-0123456789")
    from app.core.config import get_settings

    get_settings.cache_clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_rate_limiter.reset()
    previous_override = app.dependency_overrides.get(deps.get_db)
    app.dependency_overrides[deps.get_db] = override_get_db
    yield
    if previous_override is not None:
        app.dependency_overrides[deps.get_db] = previous_override
    else:
        app.dependency_overrides.pop(deps.get_db, None)
    login_rate_limiter.reset()
    get_settings.cache_clear()


@pytest.fixture()
def seed():
    db = TestingSession()
    tenant = Tenant(name="Tenant RL", code="tenant-rl")
    user = User(
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        full_name="RL User",
        is_active=True,
    )
    db.add_all([tenant, user])
    db.flush()
    db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="admin"))
    db.commit()
    db.close()


def _login(client, email=EMAIL, password="wrong-password"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_repeated_failures_get_blocked_with_429(seed):
    client = TestClient(app)
    for _ in range(login_rate_limiter.max_attempts):
        assert _login(client).status_code == 401

    resp = _login(client)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) >= 1

    # Even the correct password is blocked while rate limited.
    resp = _login(client, password=PASSWORD)
    assert resp.status_code == 429


def test_rate_limited_attempt_is_audited(seed):
    client = TestClient(app)
    for _ in range(login_rate_limiter.max_attempts):
        _login(client)
    assert _login(client).status_code == 429

    db = TestingSession()
    entries = db.query(AuditLog).filter(AuditLog.action == "auth.login_rate_limited").all()
    db.close()
    assert len(entries) == 1
    assert entries[0].actor_id == EMAIL


def test_block_expires_and_login_allowed_again(seed, monkeypatch):
    client = TestClient(app)
    fake_now = [1000.0]
    monkeypatch.setattr(LoginRateLimiter, "_now", lambda self: fake_now[0])

    for _ in range(login_rate_limiter.max_attempts):
        _login(client)
    assert _login(client).status_code == 429

    # Advance past the block window: attempts are allowed again.
    fake_now[0] += login_rate_limiter.block_seconds + 1
    resp = _login(client, password=PASSWORD)
    assert resp.status_code == 200


def test_successful_login_resets_counter(seed):
    client = TestClient(app)
    for _ in range(login_rate_limiter.max_attempts - 1):
        assert _login(client).status_code == 401

    # Legitimate login before hitting the limit succeeds and resets the count.
    assert _login(client, password=PASSWORD).status_code == 200
    for _ in range(login_rate_limiter.max_attempts - 1):
        assert _login(client).status_code == 401
    assert _login(client, password=PASSWORD).status_code == 200


def test_other_email_not_affected(seed):
    client = TestClient(app)
    for _ in range(login_rate_limiter.max_attempts):
        _login(client, email="attacker-target@example.com")
    assert _login(client, email="attacker-target@example.com").status_code == 429

    # Same IP, different email: still allowed.
    assert _login(client, password=PASSWORD).status_code == 200
