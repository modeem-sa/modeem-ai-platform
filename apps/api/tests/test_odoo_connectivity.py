"""Phase 2C tests — secure Odoo connectivity detection.

No real servers are contacted: network behavior is mocked at the httpx
transport layer (httpx.MockTransport) or the connector layer.
"""

import ipaddress
import json
import uuid
import xmlrpc.client

import httpx
import pytest

from app.integrations.odoo import connector, security
from app.integrations.odoo import http as safe_http
from app.integrations.odoo.errors import SAFE_ERROR_CODES, ConnectorError
from app.integrations.odoo.schemas import TestOutcome
from app.models import AuditLog, Connection
from tests.test_auth_security import _client, _csrf, _login
from tests.test_connections import SECRET, TestingSession, _create


def _xmlrpc_response(value) -> bytes:
    return xmlrpc.client.dumps((value,), methodresponse=True).encode()


def _version_payload(major: int) -> dict:
    return {
        "server_version": f"{major}.0",
        "server_version_info": [major, 0, 0, "final", 0, ""],
        "server_serie": f"{major}.0",
        "protocol_version": 1,
    }


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


def _make_handler(*, major=18, auth_uid=7, enterprise_count=0, json2_status=None):
    """Standard fake Odoo server handler."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/xmlrpc/2/common"):
            params, method = xmlrpc.client.loads(request.content.decode())
            if method == "version":
                return httpx.Response(200, content=_xmlrpc_response(_version_payload(major)))
            if method == "authenticate":
                _db, _login_v, secret, _ = params
                if secret == SECRET or secret == "valid-api-key":
                    return httpx.Response(200, content=_xmlrpc_response(auth_uid))
                return httpx.Response(200, content=_xmlrpc_response(False))
        if url.endswith("/xmlrpc/2/object"):
            return httpx.Response(200, content=_xmlrpc_response(enterprise_count))
        if "/json/2/" in url:
            if json2_status is not None:
                return httpx.Response(json2_status, json={"error": "denied"})
            auth = request.headers.get("Authorization", "")
            if auth == "bearer valid-api-key":
                return httpx.Response(200, json=0)
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(404)

    return handler


@pytest.fixture()
def allow_outbound(monkeypatch):
    """Bypass DNS/IP checks for pure transport tests (tested separately)."""
    monkeypatch.setattr(
        security, "enforce_outbound_policy", lambda url, environment: None
    )


@pytest.fixture()
def mock_transport(monkeypatch, allow_outbound):
    """Route the connector's client through a fake Odoo server."""
    state = {"handler": _make_handler()}
    monkeypatch.setattr(
        safe_http, "build_client", lambda *a, **k: _mock_client(lambda r: state["handler"](r))
    )
    return state


def _run_test(auth_mode="auto", login="user", secret=SECRET, database="db1"):
    return connector.test_connection(
        base_url="https://odoo.example.com",
        database=database,
        auth_mode=auth_mode,
        login=login,
        secret=secret,
        environment="development",
    )


# --- 1-3: version detection ---------------------------------------------------


@pytest.mark.parametrize("major", [16, 18, 19])
def test_version_detection(mock_transport, major):
    mock_transport["handler"] = _make_handler(major=major)
    out = _run_test()
    assert out.success is True
    assert out.odoo_version == f"{major}.0"
    assert out.odoo_major == major


# --- 4-5: legacy auth -----------------------------------------------------------


def test_legacy_password_authentication(mock_transport):
    out = _run_test(auth_mode="password", secret=SECRET)
    assert out.success and out.transport == "xmlrpc"


def test_legacy_api_key_authentication(mock_transport):
    """API keys usable in the password position on Odoo 16/18."""
    mock_transport["handler"] = _make_handler(major=16)
    out = _run_test(auth_mode="api_key", secret="valid-api-key")
    assert out.success and out.transport == "xmlrpc"


# --- 6-8: transport selection ---------------------------------------------------


def test_odoo19_json2_selected_for_api_key(mock_transport):
    mock_transport["handler"] = _make_handler(major=19)
    out = _run_test(auth_mode="api_key", secret="valid-api-key")
    assert out.success and out.transport == "json2"
    assert out.capabilities.get("json2") is True


def test_odoo19_password_mode_stays_legacy(mock_transport):
    mock_transport["handler"] = _make_handler(major=19)
    out = _run_test(auth_mode="password", secret=SECRET)
    assert out.success and out.transport == "xmlrpc"


def test_auto_mode_never_sends_bearer(mock_transport):
    """auto must not guess the secret is an API key / JSON-2 bearer token."""
    seen_bearer = []
    base = _make_handler(major=19)

    def spy(request: httpx.Request) -> httpx.Response:
        if "/json/2/" in str(request.url):
            seen_bearer.append(request.headers.get("Authorization"))
        return base(request)

    mock_transport["handler"] = spy
    out = _run_test(auth_mode="auto", secret=SECRET)
    assert out.success and out.transport == "xmlrpc"
    assert seen_bearer == []  # no JSON-2 request was ever made


def test_json2_unavailable_falls_back_to_legacy(mock_transport):
    mock_transport["handler"] = _make_handler(major=19, json2_status=404)
    out = _run_test(auth_mode="api_key", secret="valid-api-key")
    assert out.success and out.transport == "xmlrpc"
    assert out.capabilities.get("json2") is False
    assert out.capabilities.get("json2_fallback") == "legacy_xmlrpc"


# --- 9-10: version handling ------------------------------------------------------


def test_unknown_major_handled_by_capabilities(mock_transport):
    mock_transport["handler"] = _make_handler(major=21)
    out = _run_test()
    assert out.success is True
    assert out.odoo_major == 21
    assert out.capabilities.get("version_support") == "best_effort"


def test_invalid_version_response_rejected(mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_xmlrpc_response({"something": "else"})
        )

    mock_transport["handler"] = handler
    out = _run_test()
    assert out.success is False
    assert out.error_code == "unsupported_response"


# --- 11-12: failure safety --------------------------------------------------------


def test_authentication_failure_safe_code(mock_transport):
    out = _run_test(secret="wrong-secret")
    assert out.success is False
    assert out.error_code == "authentication_failed"
    assert out.error_code in SAFE_ERROR_CODES


def test_raw_upstream_error_never_leaks(mock_transport):
    marker = "SUPER-SECRET-UPSTREAM-TRACEBACK-XYZ"

    def handler(request: httpx.Request) -> httpx.Response:
        fault = xmlrpc.client.dumps(
            xmlrpc.client.Fault(1, f"Traceback: {marker}"), methodresponse=True
        )
        return httpx.Response(200, content=fault.encode())

    mock_transport["handler"] = handler
    out = _run_test()
    assert out.success is False
    assert out.error_code in SAFE_ERROR_CODES
    assert marker not in json.dumps(out.__dict__, default=str)


# --- SSRF / outbound policy (20-25) ------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8069",
        "http://127.0.0.1:8069",
        "http://[::1]:8069",
    ],
)
def test_loopback_destinations_blocked(url):
    with pytest.raises(ConnectorError) as exc:
        security.enforce_outbound_policy(url, environment="development")
    assert exc.value.code == "blocked_destination"


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.5", "172.16.1.1", "192.168.1.10", "169.254.169.254", "169.254.0.9"],
)
def test_private_and_metadata_ips_blocked(ip):
    assert security._is_blocked_ip(ipaddress.ip_address(ip)) is True


def test_private_hostname_blocked(monkeypatch):
    monkeypatch.setattr(
        security.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.0.10", 443))],
    )
    with pytest.raises(ConnectorError) as exc:
        security.enforce_outbound_policy(
            "https://internal.example.com", environment="development"
        )
    assert exc.value.code == "blocked_destination"


def test_mixed_dns_with_private_ip_blocked(monkeypatch):
    monkeypatch.setattr(
        security.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.5", 443)),
        ],
    )
    with pytest.raises(ConnectorError) as exc:
        security.enforce_outbound_policy(
            "https://mixed.example.com", environment="development"
        )
    assert exc.value.code == "blocked_destination"


def test_dns_error_maps_to_safe_code(monkeypatch):
    def boom(*a, **k):
        raise security.socket.gaierror("nope")

    monkeypatch.setattr(security.socket, "getaddrinfo", boom)
    out = connector.test_connection(
        base_url="https://does-not-resolve.example.invalid",
        database="db",
        auth_mode="auto",
        login="u",
        secret="s",
        environment="development",
    )
    assert out.success is False
    assert out.error_code == "dns_resolution_failed"


# --- 26-28: client hardening --------------------------------------------------------


def test_redirects_not_followed(allow_outbound, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    out = _run_test()
    assert out.success is False
    assert out.error_code in SAFE_ERROR_CODES


def test_client_config_hardened():
    client = safe_http.build_client("development")
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
        assert client.headers["User-Agent"].startswith("Modeem-AI-Platform/")
        # The per-request security hook is always installed.
        assert client.event_hooks["request"], "outbound policy hook missing"
    finally:
        client.close()
    # No API exists to disable TLS verification.
    import inspect

    params = inspect.signature(safe_http.build_client).parameters
    assert "verify" not in params
    assert "verify=True" in inspect.getsource(safe_http.build_client)


def test_timeout_maps_to_safe_error(allow_outbound, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    out = _run_test()
    assert out.success is False
    assert out.error_code == "connection_timeout"


# --- Hardening round: per-request validation, default-deny, ports ---------------


@pytest.mark.parametrize(
    "ip",
    ["100.64.0.1", "100.100.100.200", "100.127.255.254", "198.18.0.1", "127.0.0.1", "::1"],
)
def test_cgnat_and_special_networks_blocked(ip):
    assert security._is_blocked_ip(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"])
def test_globally_routable_ips_allowed(ip):
    assert security._is_blocked_ip(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize(
    "url",
    ["https://example.com:99999", "https://example.com:notaport", "https://example.com:0"],
)
def test_invalid_ports_are_invalid_configuration(url):
    with pytest.raises(ConnectorError) as exc:
        security.validate_outbound_url(url, environment="development")
    assert exc.value.code == "invalid_configuration"


def test_invalid_port_maps_to_safe_code_via_connector():
    out = connector.test_connection(
        base_url="https://example.com:99999",
        database="db",
        auth_mode="auto",
        login="u",
        secret="s",
        environment="development",
    )
    assert out.success is False
    assert out.error_code == "invalid_configuration"


def test_custom_valid_port_not_rejected_by_shape_check():
    """Self-hosted Odoo on a custom port must pass URL/port validation."""
    security.validate_outbound_url("https://example.com:8069", environment="production")


def test_dns_rebinding_blocked_before_second_request(monkeypatch):
    """First resolution is global; the resolver then rebinds to 127.0.0.1.
    The per-request hook must block the SECOND request BEFORE its transport
    executes, so credentials are never sent to the rebound destination."""
    resolutions = {"n": 0}

    def rebinding_getaddrinfo(*a, **k):
        resolutions["n"] += 1
        ip = "93.184.216.34" if resolutions["n"] == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (ip, 443))]

    monkeypatch.setattr(security.socket, "getaddrinfo", rebinding_getaddrinfo)

    transport_hits = {"n": 0}
    seen_bodies: list[bytes] = []
    base = _make_handler(major=18)

    def handler(request: httpx.Request) -> httpx.Response:
        transport_hits["n"] += 1
        seen_bodies.append(request.content)
        return base(request)

    real_client = safe_http.build_client(
        "development", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: real_client)

    out = connector.test_connection(
        base_url="https://rebind.example.com",
        database="db1",
        auth_mode="password",
        login="user",
        secret=SECRET,
        environment="development",
    )
    assert out.success is False
    assert out.error_code == "blocked_destination"
    # Connector-level check consumed resolution #1 (global) — the version
    # probe's own per-request hook then saw 127.0.0.1 and blocked it, so
    # AT MOST the first request reached the transport and the credentials
    # were never sent anywhere.
    assert transport_hits["n"] <= 1
    assert all(SECRET.encode() not in body for body in seen_bodies)


def test_per_request_hook_validates_every_request(monkeypatch):
    """Each outbound request triggers its own DNS/IP validation."""
    calls: list[str] = []
    real_enforce = security.enforce_outbound_policy

    def counting_enforce(url, *, environment):
        calls.append(url)
        # Treat the test hostname as globally routable.

    monkeypatch.setattr(security, "enforce_outbound_policy", counting_enforce)
    handler = _make_handler(major=18)
    real_client = safe_http.build_client(
        "development", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: real_client)

    out = connector.test_connection(
        base_url="https://odoo.example.com",
        database="db1",
        auth_mode="password",
        login="user",
        secret=SECRET,
        environment="development",
    )
    assert out.success is True
    # 1 connector-level check + one check per actual HTTP request
    # (version probe, authenticate, capability/edition probes).
    assert len(calls) >= 4
    assert real_enforce is not None  # keep a reference; silences linters


def test_oversized_xmlrpc_stream_halted_at_cap(allow_outbound, monkeypatch):
    """Chunked oversized response (no Content-Length) must be aborted at the
    byte cap while streaming — never fully buffered."""
    served = {"chunks": 0}

    def endless():
        chunk = b"x" * 65536
        while True:
            served["chunks"] += 1
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=endless())

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    out = _run_test()
    assert out.success is False
    assert out.error_code == "unsupported_response"
    # Halted right past 1 MB (~16 chunks), not after gigabytes.
    assert served["chunks"] < 32


def test_oversized_json2_stream_halted_at_cap(allow_outbound, monkeypatch):
    served = {"chunks": 0}

    def endless():
        chunk = b"j" * 65536
        while True:
            served["chunks"] += 1
            yield chunk

    base = _make_handler(major=19)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/json/2/" in str(request.url):
            return httpx.Response(200, content=endless())
        return base(request)

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    out = _run_test(auth_mode="api_key", secret="valid-api-key")
    assert out.success is False
    assert out.error_code in SAFE_ERROR_CODES
    assert served["chunks"] < 32


def test_declared_oversized_content_length_rejected_before_read(
    allow_outbound, monkeypatch
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": str(50_000_000)}, content=b""
        )

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    out = _run_test()
    assert out.success is False
    assert out.error_code == "unsupported_response"


# --- Endpoint tests (13-19, 30-32) ----------------------------------------------------


def _stub_outcome(monkeypatch, outcome: TestOutcome):
    import app.integrations.odoo.connector as conn_mod

    monkeypatch.setattr(conn_mod, "test_connection", lambda **kw: outcome)


_SUCCESS = TestOutcome(
    success=True,
    odoo_version="18.0",
    odoo_major=18,
    edition="community",
    transport="xmlrpc",
    capabilities={"legacy_xmlrpc": True},
)


def test_endpoint_success_persists_metadata(roles_seed, monkeypatch):
    _stub_outcome(monkeypatch, _SUCCESS)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["odoo_version"] == "18.0"
    assert body["transport"] == "xmlrpc"
    assert SECRET not in res.text

    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    assert conn.last_test_status == "success"
    assert conn.last_tested_at is not None
    assert conn.detected_odoo_version == "18.0"
    assert conn.detected_odoo_major == 18
    assert conn.selected_transport == "xmlrpc"
    assert conn.last_test_error_code is None
    assert json.loads(conn.capabilities_json)["legacy_xmlrpc"] is True
    db.close()


def test_endpoint_failure_preserves_previous_metadata(roles_seed, monkeypatch):
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    _stub_outcome(monkeypatch, _SUCCESS)
    assert client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client)).status_code == 200

    _stub_outcome(
        monkeypatch, TestOutcome(success=False, error_code="server_unreachable")
    )
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 200
    assert res.json()["success"] is False
    assert res.json()["error_code"] == "server_unreachable"

    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    assert conn.last_test_status == "error"
    assert conn.last_test_error_code == "server_unreachable"
    # Previously detected good metadata is preserved.
    assert conn.detected_odoo_version == "18.0"
    assert conn.selected_transport == "xmlrpc"
    db.close()


def test_edition_unknown_does_not_fail_connection(mock_transport):
    """Edition check failing → unknown, but the test still succeeds."""

    base = _make_handler(major=18)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/xmlrpc/2/object"):
            fault = xmlrpc.client.dumps(
                xmlrpc.client.Fault(3, "Access Denied"), methodresponse=True
            )
            return httpx.Response(200, content=fault.encode())
        return base(request)

    mock_transport["handler"] = handler
    out = _run_test()
    assert out.success is True
    assert out.edition == "unknown"


def test_endpoint_credentials_never_in_response_or_audit(roles_seed, monkeypatch):
    _stub_outcome(monkeypatch, _SUCCESS)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert SECRET not in res.text
    assert "Authorization" not in res.text
    db = TestingSession()
    for entry in db.query(AuditLog).all():
        dump = str(entry.metadata_json)
        assert SECRET not in dump
        assert "password_or_api_key" not in dump
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "connection.test_succeeded")
        .one()
    )
    assert audit.resource_id == cid
    db.close()


def test_endpoint_cross_tenant_404(roles_seed, monkeypatch):
    _stub_outcome(monkeypatch, _SUCCESS)
    client_a = _client()
    _login(client_a, "owner@example.com")
    cid = _create(client_a).json()["id"]
    client_b = _client()
    _login(client_b, "owner-b@example.com")
    res = client_b.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client_b))
    assert res.status_code == 404


@pytest.mark.parametrize("role", ["viewer", "member", "manager"])
def test_endpoint_read_roles_cannot_test(roles_seed, monkeypatch, role):
    _stub_outcome(monkeypatch, _SUCCESS)
    owner = _client()
    _login(owner, "owner@example.com")
    cid = _create(owner).json()["id"]
    client = _client()
    _login(client, f"{role}@example.com")
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_endpoint_owner_admin_can_test(roles_seed, monkeypatch, role):
    _stub_outcome(monkeypatch, _SUCCESS)
    client = _client()
    _login(client, f"{role}@example.com")
    cid = _create(client, name=f"T {role}").json()["id"]
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 200


def test_endpoint_requires_csrf(roles_seed, monkeypatch):
    _stub_outcome(monkeypatch, _SUCCESS)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    assert client.post(f"/api/v1/connections/{cid}/test").status_code == 403
    assert (
        client.post(
            f"/api/v1/connections/{cid}/test", headers={"X-CSRF-Token": "forged"}
        ).status_code
        == 403
    )


def test_endpoint_disabled_connection_rejected(roles_seed, monkeypatch):
    _stub_outcome(monkeypatch, _SUCCESS)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    client.delete(f"/api/v1/connections/{cid}", headers=_csrf(client))
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 409


# --- 33: no business-data endpoints ------------------------------------------------


def test_only_explicit_overdue_invoice_sync_endpoint_exists():
    """Only the fixed, tenant-scoped overdue-invoice signal sync is exposed."""
    from app.api.connections import router

    paths = [r.path for r in router.routes]
    assert paths  # sanity
    allowed = "/api/v1/connections/{connection_id}/sync-overdue-invoices"
    assert allowed in paths
    for path in paths:
        if path == allowed:
            continue
        for banned in ("partner", "invoice", "employee", "sync", "sale", "stock", "record"):
            assert banned not in path.lower(), path


def test_auth_mode_persisted_and_validated(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    payload = {
        "name": "AK Conn",
        "provider": "odoo",
        "base_url": "https://ak.example.com",
        "database_name": "db",
        "username": "u",
        "auth_mode": "api_key",
        "credentials": {"password_or_api_key": SECRET},
    }
    res = client.post("/api/v1/connections", json=payload, headers=_csrf(client))
    assert res.status_code == 201
    assert res.json()["auth_mode"] == "api_key"
    cid = res.json()["id"]
    # default is auto
    res2 = _create(client, name="Default Conn")
    assert res2.json()["auth_mode"] == "auto"
    # invalid mode rejected
    payload["name"] = "Bad"
    payload["auth_mode"] = "bearer"
    assert (
        client.post("/api/v1/connections", json=payload, headers=_csrf(client)).status_code
        == 422
    )
    # patchable
    res = client.patch(
        f"/api/v1/connections/{cid}", json={"auth_mode": "password"}, headers=_csrf(client)
    )
    assert res.json()["auth_mode"] == "password"

class _CaptureTransport(httpx.BaseTransport):
    """Fake inner transport recording exactly what would hit the network."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, content=b"ok")

    def close(self):
        pass

def test_pinning_blocks_private_resolution_before_any_connection(monkeypatch):
    def evil_getaddrinfo(host, port, *a, **k):
        return [(2, 1, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(security.socket, "getaddrinfo", evil_getaddrinfo)
    transport, capture = _pinning_transport(monkeypatch)
    request = httpx.Request("POST", "https://metadata.attacker.example/")
    with pytest.raises(ConnectorError) as exc:
        transport.handle_request(request)
    assert exc.value.code == "blocked_destination"
    assert capture.requests == [], "nothing may reach the network"

def test_build_client_uses_pinning_transport_by_default():
    client = safe_http.build_client("development")
    try:
        assert isinstance(client._transport, safe_http.PinningTransport)
    finally:
        client.close()

def _pinning_transport(monkeypatch, environment="development"):
    transport = safe_http.PinningTransport(environment)
    capture = _CaptureTransport()
    monkeypatch.setattr(transport, "_inner", capture)
    return transport, capture

def test_pinning_connects_to_exact_validated_ip(monkeypatch):
    """Adversarial rebinding: DNS returns a global IP on the validation
    lookup, then rebinds to 127.0.0.1 for every later lookup. Because the
    transport resolves ONCE and rewrites the URL host to that validated IP,
    the connection target is the validated IP — the rebound answer can
    never be used."""
    calls = {"n": 0}

    def rebinding_getaddrinfo(host, port, *a, **k):
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (ip, port))]

    monkeypatch.setattr(security.socket, "getaddrinfo", rebinding_getaddrinfo)
    transport, capture = _pinning_transport(monkeypatch)
    request = httpx.Request("POST", "https://odoo.example.com:8069/xmlrpc/2/common")
    response = transport.handle_request(request)
    assert response.status_code == 200
    sent = capture.requests[0]
    # Connection target is the pinned, validated IP — not a re-resolved name.
    assert sent.url.host == "93.184.216.34"
    assert calls["n"] == 1, "transport must resolve exactly once (no TOCTOU window)"
    # Host header and TLS SNI keep the ORIGINAL hostname for cert verification.
    assert sent.headers["Host"] == "odoo.example.com:8069"
    assert sent.extensions["sni_hostname"] == "odoo.example.com"
    assert sent.url.port == 8069
    assert sent.url.path == "/xmlrpc/2/common"

def test_pinning_transport_rejects_bad_url_shape(monkeypatch):
    transport, capture = _pinning_transport(monkeypatch, environment="production")
    with pytest.raises(ConnectorError) as exc:
        transport.handle_request(httpx.Request("GET", "http://odoo.example.com/"))
    assert exc.value.code == "invalid_configuration"  # https required in production
    assert capture.requests == []

def test_pinning_ip_literal_blocked_or_passed(monkeypatch):
    # Private literal: blocked, no DNS involved, nothing sent.
    transport, capture = _pinning_transport(monkeypatch)
    with pytest.raises(ConnectorError) as exc:
        transport.handle_request(httpx.Request("POST", "http://127.0.0.1:8069/"))
    assert exc.value.code == "blocked_destination"
    assert capture.requests == []
    # Global literal: passes through unchanged (already pinned by nature).
    def no_dns(*a, **k):
        raise AssertionError("no DNS lookup should happen for IP literals")

    monkeypatch.setattr(security.socket, "getaddrinfo", no_dns)
    transport2, capture2 = _pinning_transport(monkeypatch)
    transport2.handle_request(httpx.Request("GET", "http://93.184.216.34/"))
    assert capture2.requests[0].url.host == "93.184.216.34"

def test_pinning_prefers_ipv4_and_falls_back_to_ipv6(monkeypatch):
    def dual_getaddrinfo(host, port, *a, **k):
        return [
            (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0)),
            (2, 1, 6, "", ("93.184.216.34", port)),
        ]

    monkeypatch.setattr(security.socket, "getaddrinfo", dual_getaddrinfo)
    transport, capture = _pinning_transport(monkeypatch)
    transport.handle_request(httpx.Request("GET", "https://odoo.example.com/"))
    assert capture.requests[0].url.host == "93.184.216.34"

    def v6_only_getaddrinfo(host, port, *a, **k):
        return [(10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0))]

    monkeypatch.setattr(security.socket, "getaddrinfo", v6_only_getaddrinfo)
    transport6, capture6 = _pinning_transport(monkeypatch)
    transport6.handle_request(httpx.Request("GET", "https://odoo.example.com/"))
    assert capture6.requests[0].url.host == "2606:2800:220:1:248:1893:25c8:1946"
    assert capture6.requests[0].extensions["sni_hostname"] == "odoo.example.com"

def test_pinning_mixed_answer_blocked_entirely(monkeypatch):
    def mixed_getaddrinfo(host, port, *a, **k):
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("10.0.0.5", port)),
        ]

    monkeypatch.setattr(security.socket, "getaddrinfo", mixed_getaddrinfo)
    transport, capture = _pinning_transport(monkeypatch)
    with pytest.raises(ConnectorError) as exc:
        transport.handle_request(httpx.Request("POST", "https://odoo.example.com/"))
    assert exc.value.code == "blocked_destination"
    assert capture.requests == []
