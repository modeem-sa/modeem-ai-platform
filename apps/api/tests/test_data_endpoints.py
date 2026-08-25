"""Tests for protected data endpoints.

Covers:
  1. Unauthenticated / wrong-token requests → 401.
  2. Cross-tenant isolation: rows seeded for tenant A are invisible to tenant B.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Connection, Tenant
from tests.test_auth_security import TestingSession

client = TestClient(app, raise_server_exceptions=False)

# The real SESSION_SECRET is available in the test environment.
VALID_TOKEN: str = os.environ["SESSION_SECRET"]

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

# NOTE: /api/v1/connections is intentionally NOT here — connection
# management is served by the cookie-authenticated router in
# app.api.connections (covered by tests/test_connections.py). A duplicate
# internal-token listing was removed to avoid a route collision.
DATA_ENDPOINTS = [
    "/api/v1/stats",
    "/api/v1/workflows",
    "/api/v1/executions",
    "/api/v1/audit-logs",
]


def _auth(tenant_id: uuid.UUID = TENANT_A, token: str = VALID_TOKEN) -> dict[str, str]:
    return {
        "X-Internal-Token": token,
        "X-Tenant-ID": str(tenant_id),
    }


# ---------------------------------------------------------------------------
# 1. Auth guard — every data endpoint refuses unauthenticated requests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_no_token_returns_401(path: str) -> None:
    """Missing X-Internal-Token header → 401."""
    resp = client.get(path, headers={"X-Tenant-ID": str(TENANT_A)})
    assert resp.status_code == 401, f"{path}: expected 401, got {resp.status_code}"


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_wrong_token_returns_401(path: str) -> None:
    """Wrong X-Internal-Token value → 401."""
    resp = client.get(
        path,
        headers={"X-Internal-Token": "wrong-secret", "X-Tenant-ID": str(TENANT_A)},
    )
    assert resp.status_code == 401, f"{path}: expected 401, got {resp.status_code}"


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_no_tenant_id_returns_400(path: str) -> None:
    """Valid token but missing X-Tenant-ID → 400."""
    resp = client.get(path, headers={"X-Internal-Token": VALID_TOKEN})
    assert resp.status_code == 400, f"{path}: expected 400, got {resp.status_code}"


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_valid_auth_returns_200(path: str) -> None:
    """Valid token + valid tenant → 200."""
    resp = client.get(path, headers=_auth())
    assert resp.status_code == 200, f"{path}: expected 200, got {resp.status_code}"


def test_open_endpoints_need_no_auth() -> None:
    """health and info are open — no headers required."""
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/info").status_code == 200


# ---------------------------------------------------------------------------
# 2. Tenant isolation — connection rows are scoped to their tenant
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_tenant_connections():
    """Seed one Connection per tenant; clean up after the test."""
    session = TestingSession()
    created_tenants = []
    for tid, code in ((TENANT_A, "test-tenant-a"), (TENANT_B, "test-tenant-b")):
        if session.get(Tenant, tid) is None:
            t = Tenant(id=tid, name=f"Test {code}", code=code, is_active=True)
            session.add(t)
            created_tenants.append(t)
    session.commit()
    conn_a = Connection(
        id=uuid.uuid4(),
        tenant_id=TENANT_A,
        name=f"Tenant-A-conn-{uuid.uuid4().hex[:8]}",
        provider="odoo",
        base_url="https://a.example.odoo.com",
        is_active=True,
    )
    conn_b = Connection(
        id=uuid.uuid4(),
        tenant_id=TENANT_B,
        name=f"Tenant-B-conn-{uuid.uuid4().hex[:8]}",
        provider="odoo",
        base_url="https://b.example.odoo.com",
        is_active=True,
    )
    session.add_all([conn_a, conn_b])
    session.commit()
    yield conn_a, conn_b
    session.delete(conn_a)
    session.delete(conn_b)
    for t in created_tenants:
        session.delete(t)
    session.commit()
    session.close()


def test_connection_counts_isolated_per_tenant(two_tenant_connections) -> None:
    """Each tenant's stats count only their own connection rows."""
    resp_a = client.get("/api/v1/stats", headers=_auth(TENANT_A))
    resp_b = client.get("/api/v1/stats", headers=_auth(TENANT_B))
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    assert resp_a.json()["connected_systems"] >= 1
    assert resp_b.json()["connected_systems"] >= 1
    # A tenant with no rows sees zero, proving counts are tenant-scoped.
    resp_v = client.get("/api/v1/stats", headers=_auth(uuid.uuid4()))
    assert resp_v.json()["connected_systems"] == 0


def test_stats_scoped_to_tenant(two_tenant_connections) -> None:
    """Stats counts only rows belonging to the requesting tenant."""
    resp_a = client.get("/api/v1/stats", headers=_auth(TENANT_A))
    assert resp_a.status_code == 200
    # connected_systems counts active connections for this tenant only.
    data = resp_a.json()
    assert data["connected_systems"] >= 1, "Should count at least the seeded connection"

    # A fresh UUID that has no rows should see zero connected systems.
    virgin_tenant = uuid.uuid4()
    resp_v = client.get("/api/v1/stats", headers=_auth(virgin_tenant))
    assert resp_v.status_code == 200
    assert resp_v.json()["connected_systems"] == 0
