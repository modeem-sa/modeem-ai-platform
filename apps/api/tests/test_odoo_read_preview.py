"""Phase 2D tests — safe generic Odoo read adapter (read preview).

No real Odoo/customer servers are contacted: network behavior is mocked
via httpx.MockTransport or by stubbing the reader/adapters.
"""

import json
import uuid
import xmlrpc.client

import httpx
import pytest

from app.integrations.odoo import http as safe_http
from app.integrations.odoo import json2, legacy_xmlrpc, reader, security
from app.integrations.odoo.errors import SAFE_ERROR_CODES, ConnectorError
from app.integrations.odoo.read_policies import get_policy
from app.integrations.odoo.reader import ReadPolicyError
from app.models import AuditLog, Connection
from tests.test_auth_security import _client, _csrf, _login
from tests.test_connections import SECRET, TestingSession, _create

COUNTRIES = [
    {"id": 1, "name": "Saudi Arabia", "code": "SA"},
    {"id": 2, "name": "Egypt", "code": "EG"},
    {"id": 3, "name": "United Arab Emirates", "code": "AE"},
]


def _xmlrpc_response(value) -> bytes:
    return xmlrpc.client.dumps((value,), methodresponse=True).encode()


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture()
def allow_outbound(monkeypatch):
    monkeypatch.setattr(security, "enforce_outbound_policy", lambda url, environment: None)


class FakeOdoo:
    """Fake Odoo server for both transports, recording upstream calls."""

    def __init__(self, records=None):
        self.records = records if records is not None else COUNTRIES
        self.xmlrpc_calls: list[tuple[str, tuple]] = []
        self.json2_calls: list[tuple[str, dict, dict]] = []
        self.raw_search_read_result = None  # override for malformed tests

    def _page(self, kwargs):
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        return [dict(r) for r in self.records[offset : offset + limit]]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/xmlrpc/2/common"):
            params, method = xmlrpc.client.loads(request.content.decode())
            self.xmlrpc_calls.append((method, params))
            if method == "authenticate":
                secret = params[2]
                if secret in (SECRET, "valid-api-key"):
                    return httpx.Response(200, content=_xmlrpc_response(7))
                return httpx.Response(200, content=_xmlrpc_response(False))
        if url.endswith("/xmlrpc/2/object"):
            params, method = xmlrpc.client.loads(request.content.decode())
            self.xmlrpc_calls.append((method, params))
            rpc_method = params[4]
            if rpc_method == "search_read":
                kwargs = params[6] if len(params) > 6 else {}
                result = (
                    self.raw_search_read_result
                    if self.raw_search_read_result is not None
                    else self._page(kwargs)
                )
                return httpx.Response(200, content=_xmlrpc_response(result))
            fault = xmlrpc.client.dumps(
                xmlrpc.client.Fault(2, f"unexpected {rpc_method}"), methodresponse=True
            )
            return httpx.Response(200, content=fault.encode())
        if "/json/2/" in url:
            body = json.loads(request.content.decode())
            headers = {k.lower(): v for k, v in request.headers.items()}
            self.json2_calls.append((url, body, headers))
            if headers.get("authorization") != "bearer valid-api-key":
                return httpx.Response(401, json={"error": "unauthorized"})
            if url.endswith("/search_read"):
                result = (
                    self.raw_search_read_result
                    if self.raw_search_read_result is not None
                    else self._page(body)
                )
                return httpx.Response(200, json=result)
        return httpx.Response(404)


@pytest.fixture()
def fake_odoo(monkeypatch, allow_outbound):
    server = FakeOdoo()
    monkeypatch.setattr(
        safe_http, "build_client", lambda *a, **k: _mock_client(server.handler)
    )
    return server


def _read(transport="xmlrpc", secret=SECRET, **overrides):
    params = {
        "base_url": "https://odoo.example.com",
        "database": "db1",
        "transport": transport,
        "login": "user",
        "secret": secret,
        "environment": "development",
        "resource": "countries",
        "limit": 25,
        "offset": 0,
    }
    params.update(overrides)
    return reader.read_page(**params)


# --- Policy registry (1-3) ------------------------------------------------------


def test_countries_policy_resolves_to_res_country():
    policy = get_policy("countries")
    assert policy.odoo_model == "res.country"
    assert policy.allowed_fields == {"id", "name", "code"}


def test_unknown_resource_rejected_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(resource="res.partner")
    assert fake_odoo.xmlrpc_calls == [] and fake_odoo.json2_calls == []


def test_raw_model_cannot_be_supplied_via_api(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "countries", "odoo_model": "res.partner"},
        headers=_csrf(client),
    )
    assert res.status_code == 422  # extra="forbid"


# --- Field validation (4-6) -----------------------------------------------------


def test_disallowed_field_rejected_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(fields=["id", "vat"])
    assert fake_odoo.xmlrpc_calls == []


def test_default_fields_applied(fake_odoo):
    page = _read(fields=None)
    assert page["fields"] == ["id", "name", "code"]


def test_duplicate_fields_normalized(fake_odoo):
    page = _read(fields=["id", "id", "name"])
    assert page["fields"] == ["id", "name"]


# --- Filter validation (7-10) ----------------------------------------------------


def test_disallowed_filter_field_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "currency_id", "operator": "=", "value": 1}])
    assert fake_odoo.xmlrpc_calls == []


def test_disallowed_filter_operator_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "code", "operator": "child_of", "value": "SA"}])
    assert fake_odoo.xmlrpc_calls == []


def test_raw_domain_syntax_rejected(fake_odoo):
    # OR/AND tokens are not valid filter objects.
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "|", "operator": "=", "value": "x"}])
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "code", "operator": "|", "value": "x"}])
    assert fake_odoo.xmlrpc_calls == []


def test_filter_count_limit_enforced(fake_odoo):
    filters = [{"field": "code", "operator": "=", "value": "SA"}] * 6
    with pytest.raises(ReadPolicyError):
        _read(filters=filters)
    assert fake_odoo.xmlrpc_calls == []

def test_id_filter_rejects_non_int_values(fake_odoo):
    for bad in ["1", 1.5, True, None, {"x": 1}]:
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": "id", "operator": "=", "value": bad}])
    assert fake_odoo.xmlrpc_calls == [] and fake_odoo.json2_calls == []
def test_limit_above_50_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(limit=51)


def test_negative_offset_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(offset=-1)


def test_offset_above_cap_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(offset=1001)


def test_unsafe_order_field_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(order_by="write_date")


def test_unsafe_order_direction_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(order_by="name", order_direction="asc; drop")


# --- Transport correctness (16-22, 25) ---------------------------------------------


def test_xmlrpc_uses_only_policy_model_and_fields(fake_odoo):
    _read(filters=[{"field": "code", "operator": "=", "value": "SA"}], order_by="name")
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert len(execs) == 1
    params = execs[0]
    assert params[3] == "res.country"
    assert params[4] == "search_read"
    assert params[5] == [[["code", "=", "SA"]]]
    kwargs = params[6]
    assert set(kwargs["fields"]) <= {"id", "name", "code"}
    assert kwargs["order"] == "name asc"


def test_json2_uses_only_policy_model_and_fields(fake_odoo):
    _read(transport="json2", secret="valid-api-key", order_by="code", order_direction="desc")
    assert len(fake_odoo.json2_calls) == 1
    url, body, _headers = fake_odoo.json2_calls[0]
    assert url.endswith("/json/2/res.country/search_read")
    assert set(body["fields"]) <= {"id", "name", "code"}
    assert body["order"] == "code desc"
    assert "context" not in body


@pytest.mark.parametrize("major_label", ["odoo16", "odoo18"])
def test_xmlrpc_preview_succeeds(fake_odoo, major_label):
    # Version is NOT rediscovered during reads; transport comes from the
    # stored successful test, so 16 and 18 behave identically here.
    page = _read()
    assert page["returned_count"] == 3
    assert page["transport"] == "xmlrpc"


def test_odoo19_json2_preview_succeeds(fake_odoo):
    page = _read(transport="json2", secret="valid-api-key")
    assert page["transport"] == "json2"
    assert page["records"][0]["code"] == "SA"


def test_odoo19_xmlrpc_selected_connection_works(fake_odoo):
    page = _read(transport="xmlrpc", secret="valid-api-key")
    assert page["transport"] == "xmlrpc"
    assert page["returned_count"] == 3


def test_exactly_one_page_requested_and_no_search_count(fake_odoo):
    _read(limit=2)
    methods = [m for m, _ in fake_odoo.xmlrpc_calls]
    assert methods.count("execute_kw") == 1  # one page, no looping
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert all(p[4] != "search_count" for p in execs)


def test_stale_transport_fails_safely(fake_odoo):
    with pytest.raises(ConnectorError) as exc:
        _read(transport="grpc")
    assert exc.value.code == "invalid_configuration"
    assert fake_odoo.xmlrpc_calls == []


# --- Pagination behavior (23-24) ----------------------------------------------------


def test_limit_plus_one_determines_has_more(fake_odoo):
    page = _read(limit=2)
    # 3 records exist; limit+1=3 returned; page trimmed to 2 with has_more.
    assert page["returned_count"] == 2
    assert page["has_more"] is True
    assert page["next_offset"] == 2
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert execs[0][6]["limit"] == 3  # limit + 1 upstream


def test_response_trimmed_to_requested_limit(fake_odoo):
    page = _read(limit=2)
    assert len(page["records"]) == 2
    last = _read(limit=25, offset=2)
    assert last["returned_count"] == 1
    assert last["has_more"] is False
    assert last["next_offset"] is None


# --- Upstream sanitation (26-28) -----------------------------------------------------


def test_malformed_upstream_list_rejected(fake_odoo):
    fake_odoo.raw_search_read_result = {"not": "a list"}
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"


def test_malformed_record_rejected(fake_odoo):
    fake_odoo.raw_search_read_result = ["not-a-dict"]
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"
    fake_odoo.raw_search_read_result = [{"id": -5, "name": "x"}]
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"


def test_unexpected_extra_upstream_fields_dropped(fake_odoo):
    fake_odoo.raw_search_read_result = [
        {"id": 1, "name": "SA", "code": "SA", "vat_number": "LEAK", "phone": "123"}
    ]
    page = _read()
    assert page["records"] == [{"id": 1, "name": "SA", "code": "SA"}]


# --- Endpoint fixtures ---------------------------------------------------------------


def _tested_connection(client, name="Test Conn") -> str:
    """Create a connection and mark it successfully tested in the DB."""
    cid = _create(client, name=name).json()["id"]
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.last_test_status = "success"
    conn.selected_transport = "xmlrpc"
    conn.detected_odoo_version = "18.0"
    conn.detected_odoo_major = 18
    conn.detected_edition = "community"
    from datetime import UTC, datetime

    conn.last_tested_at = datetime.now(UTC)
    conn.capabilities_json = json.dumps({"legacy_xmlrpc": True})
    db.commit()
    db.close()
    return cid


@pytest.fixture()
def stub_page(monkeypatch):
    page = {
        "resource": "countries",
        "fields": ["id", "name", "code"],
        "records": [{"id": 1, "name": "Saudi Arabia", "code": "SA"}],
        "limit": 25,
        "offset": 0,
        "returned_count": 1,
        "has_more": False,
        "next_offset": None,
        "transport": "xmlrpc",
    }
    import app.integrations.odoo.reader as reader_mod

    calls = {"kwargs": None}

    def fake_read_page(**kwargs):
        calls["kwargs"] = kwargs
        return dict(page)

    monkeypatch.setattr(reader_mod, "read_page", fake_read_page)
    return calls


def _preview(client, cid, body=None):
    payload = {"resource": "countries"}
    if body:
        payload.update(body)
    return client.post(
        f"/api/v1/connections/{cid}/read-preview", json=payload, headers=_csrf(client)
    )


# --- Endpoint: response/audit safety (29-32) --------------------------------------------


def test_response_never_contains_credentials(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _preview(client, cid)
    assert res.status_code == 200
    assert SECRET not in res.text
    assert "password_or_api_key" not in res.text
    assert "uid" not in res.json()


def test_audit_never_contains_credentials_records_or_filters(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _preview(
        client,
        cid,
        {"filters": [{"field": "code", "operator": "=", "value": "SECRETFILTER"}]},
    )
    assert res.status_code == 200
    db = TestingSession()
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.action == "connection.read_preview_succeeded")
        .all()
    )
    assert entries
    for entry in entries:
        dump = str(entry.metadata_json)
        assert SECRET not in dump
        assert "SECRETFILTER" not in dump  # filter values never audited
        assert "Saudi Arabia" not in dump  # record content never audited
    db.close()


# --- Endpoint: roles (33-37) ----------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_admin_can_preview(roles_seed, stub_page, role):
    client = _client()
    _login(client, f"{role}@example.com")
    cid = _tested_connection(client, name=f"P {role}")
    assert _preview(client, cid).status_code == 200


@pytest.mark.parametrize("role", ["manager", "member", "viewer"])
def test_other_roles_cannot_preview(roles_seed, stub_page, role):
    owner = _client()
    _login(owner, "owner@example.com")
    cid = _tested_connection(owner)
    client = _client()
    _login(client, f"{role}@example.com")
    assert _preview(client, cid).status_code == 403


# --- Endpoint: CSRF / tenancy / state (38-42) --------------------------------------------


def test_preview_requires_csrf(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview", json={"resource": "countries"}
    )
    assert res.status_code == 403


def test_cross_tenant_preview_404(roles_seed, stub_page):
    client_a = _client()
    _login(client_a, "owner@example.com")
    cid = _tested_connection(client_a)
    client_b = _client()
    _login(client_b, "owner-b@example.com")
    assert _preview(client_b, cid).status_code == 404


def test_disabled_connection_cannot_preview(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    client.delete(f"/api/v1/connections/{cid}", headers=_csrf(client))
    assert _preview(client, cid).status_code == 409


def test_never_tested_connection_cannot_preview(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    res = _preview(client, cid)
    assert res.status_code == 409


def test_failed_test_connection_cannot_preview(roles_seed, stub_page):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.last_test_status = "error"
    db.commit()
    db.close()
    assert _preview(client, cid).status_code == 409


# --- Test-metadata invalidation (43-47) ----------------------------------------------


def _patch(client, cid, body):
    return client.patch(f"/api/v1/connections/{cid}", json=body, headers=_csrf(client))


def _test_status(cid):
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    result = (
        conn.last_test_status,
        conn.selected_transport,
        conn.detected_odoo_version,
        conn.capabilities_json,
        conn.last_tested_at,
    )
    db.close()
    return result


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://other.example.com"},
        {"database_name": "other-db"},
        {"auth_mode": "api_key"},
        {"credentials": {"password_or_api_key": "new-secret-value"}},
    ],
)
def test_connectivity_change_invalidates_test_metadata(roles_seed, change):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    assert _patch(client, cid, change).status_code == 200
    assert _test_status(cid) == (None, None, None, None, None)


def test_name_only_change_keeps_test_metadata(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    assert _patch(client, cid, {"name": "Renamed Conn"}).status_code == 200
    status_, transport, version, caps, tested_at = _test_status(cid)
    assert status_ == "success" and transport == "xmlrpc" and version == "18.0"
    assert caps is not None and tested_at is not None


def test_unchanged_connectivity_values_keep_test_metadata(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    # PATCHing the same base_url/auth_mode values does not invalidate.
    assert _patch(
        client, cid, {"base_url": "https://example.odoo.com", "auth_mode": "auto"}
    ).status_code == 200
    assert _test_status(cid)[0] == "success"


# --- Error mapping (48-50) --------------------------------------------------------------


def test_access_error_maps_to_access_denied_without_raw_text(allow_outbound, monkeypatch):
    marker = "You are not allowed to access 'res.country' SECRET-TRACE"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/xmlrpc/2/common"):
            return httpx.Response(200, content=_xmlrpc_response(7))
        fault = xmlrpc.client.dumps(
            xmlrpc.client.Fault(3, marker), methodresponse=True
        )
        return httpx.Response(200, content=fault.encode())

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "access_denied"
    assert exc.value.code in SAFE_ERROR_CODES
    assert "SECRET-TRACE" not in exc.value.code


def test_xmlrpc_raw_fault_never_reaches_api(roles_seed, monkeypatch):
    import app.integrations.odoo.reader as reader_mod

    def boom(**kwargs):
        raise ConnectorError("access_denied", "raw fault detail NEVER-SHOWN")

    monkeypatch.setattr(reader_mod, "read_page", boom)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _preview(client, cid)
    assert res.status_code == 502
    assert res.json()["detail"] == {"error_code": "access_denied"}
    assert "NEVER-SHOWN" not in res.text


def test_json2_raw_error_body_never_reaches_api(allow_outbound, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": "AccessError", "traceback": "REMOTE-TRACE"}
        )

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    with pytest.raises(ConnectorError) as exc:
        _read(transport="json2", secret="valid-api-key")
    assert exc.value.code == "access_denied"


# --- Security continuity (51-52) --------------------------------------------------------


def test_ssrf_policy_applies_to_reads():
    with pytest.raises(ConnectorError) as exc:
        reader.read_page(
            base_url="http://127.0.0.1:8069",
            database="db",
            transport="xmlrpc",
            login="u",
            secret="s",
            environment="development",
            resource="countries",
            limit=25,
            offset=0,
        )
    assert exc.value.code == "blocked_destination"


def test_oversized_read_response_stopped_by_streaming_cap(allow_outbound, monkeypatch):
    served = {"chunks": 0}

    def endless():
        chunk = b"x" * 65536
        while True:
            served["chunks"] += 1
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/xmlrpc/2/common"):
            return httpx.Response(200, content=_xmlrpc_response(7))
        return httpx.Response(200, content=endless())

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    with pytest.raises(ConnectorError):
        _read()
    assert served["chunks"] < 32


# --- No writes / no persistence (53-54) --------------------------------------------------


def test_no_write_operations_exist():
    import inspect

    for module in (reader, legacy_xmlrpc, json2):
        source = inspect.getsource(module)
        for banned in ('"create"', '"write"', '"unlink"', "'create'", "'write'", "'unlink'"):
            assert banned not in source, (module.__name__, banned)
    from app.api.connections import router

    for route in router.routes:
        for banned in ("create-record", "write", "unlink", "sync"):
            assert banned not in route.path.lower()


def test_no_local_odoo_record_persistence():
    """No sync tables / no country model exists in the Modeem DB layer."""
    from app import models

    names = [n.lower() for n in dir(models)]
    for banned in ("country", "partner", "invoice", "employee", "syncrecord"):
        assert not any(banned in n for n in names), banned

def test_id_filter_rejects_out_of_range_ints(fake_odoo):
    for bad in [0, -1, 2**31]:
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": "id", "operator": "=", "value": bad}])
    assert fake_odoo.xmlrpc_calls == []

def test_id_filter_accepts_valid_int(fake_odoo):
    page = _read(filters=[{"field": "id", "operator": "=", "value": 1}])
    assert page["returned_count"] >= 0
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert execs[0][5] == [[["id", "=", 1]]]

def test_code_filter_rejects_non_string_and_bad_pattern(fake_odoo):
    for bad in [1, True, None, [1], "SA1", "S A", "TOOLONG", "sa%", ""]:
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": "code", "operator": "=", "value": bad}])
    assert fake_odoo.xmlrpc_calls == []

def test_code_filter_accepts_short_letters(fake_odoo):
    page = _read(filters=[{"field": "code", "operator": "=", "value": "SA"}])
    assert page["transport"] == "xmlrpc"

def test_name_filter_rejects_control_chars_and_wildcards(fake_odoo):
    for bad in [123, "a\x00b", "a\nb", "x" * 101, "Sau%di", "Sa_udi", "a\\b", ""]:
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": "name", "operator": "ilike", "value": bad}])
    assert fake_odoo.xmlrpc_calls == []

def test_every_policy_filter_field_has_explicit_spec():
    from app.integrations.odoo.read_policies import READ_POLICIES

    for policy in READ_POLICIES.values():
        assert policy.allowed_filter_fields <= set(policy.fields)
        for spec in policy.fields.values():
            assert spec.value_type in (
                "integer",
                "string",
                "boolean",
                "number",
                "date",
                "many2one",
            )

def test_endpoint_rejects_bad_value_type_with_422(roles_seed, fake_odoo):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _preview(
        client,
        cid,
        {"filters": [{"field": "id", "operator": "=", "value": "not-an-int"}]},
    )
    assert res.status_code == 422
    assert fake_odoo.xmlrpc_calls == [] and fake_odoo.json2_calls == []

def test_bool_no_longer_accepted_as_generic_scalar(fake_odoo):
    # Previously booleans passed the generic scalar check; each field now
    # has an explicit type and countries has no bool-typed filter field.
    for fld in ["id", "name", "code"]:
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": fld, "operator": "=", "value": True}])
    assert fake_odoo.xmlrpc_calls == []

def test_in_filter_validates_every_list_item_type(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "in", "value": [1, "2", 3]}])
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "code", "operator": "in", "value": ["SA", 5]}])
    assert fake_odoo.xmlrpc_calls == []

def test_ilike_not_allowed_on_int_fields(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "ilike", "value": "1"}])
    assert fake_odoo.xmlrpc_calls == []


# --- Approved customer and invoice summaries ---------------------------------


def test_customers_policy_is_read_only_customer_subset():
    policy = get_policy("customers")
    assert policy.odoo_model == "res.partner"
    assert policy.base_domain == (("customer_rank", ">", 0),)
    assert "comment" not in policy.allowed_fields
    assert "bank_ids" not in policy.allowed_fields
    assert "credit_limit" not in policy.allowed_fields


def test_customer_read_uses_server_owned_domain(fake_odoo):
    fake_odoo.records = [
        {
            "id": 10,
            "name": "Acme Customer",
            "email": "customer@example.com",
            "phone": False,
            "mobile": "+966500000000",
            "vat": False,
            "company_type": "company",
            "active": True,
        }
    ]
    page = _read(resource="customers", order_by="name")
    assert page["records"][0]["phone"] is None
    assert page["records"][0]["vat"] is None
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert execs[0][3] == "res.partner"
    assert ["customer_rank", ">", 0] in execs[0][5][0]
    assert execs[0][4] == "search_read"


def test_invoices_policy_excludes_vendor_bills_and_lines():
    policy = get_policy("invoices")
    assert policy.odoo_model == "account.move"
    assert policy.base_domain == (
        ("move_type", "in", ("out_invoice", "out_refund")),
    )
    assert "invoice_line_ids" not in policy.allowed_fields
    assert "line_ids" not in policy.allowed_fields
    assert "narration" not in policy.allowed_fields
    assert policy.required_module == "account"
    assert policy.requires_company_scope is True


def test_invoice_company_scope_required_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError, match="company_id is required"):
        _read(resource="invoices")
    assert fake_odoo.xmlrpc_calls == []


def test_invoice_read_sanitizes_dates_and_relations(fake_odoo):
    fake_odoo.records = [
        {
            "id": 20,
            "name": "INV/2026/0001",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2026-08-26",
            "invoice_date_due": False,
            "partner_id": [10, "Acme Customer"],
            "currency_id": [2, "SAR"],
            "company_id": [15, "جمعية الاختبار"],
            "amount_total": 1150.0,
            "amount_residual": 0.0,
            "payment_state": "paid",
            "invoice_line_ids": [1, 2, 3],
        }
    ]
    page = _read(
        resource="invoices",
        company_id=15,
        order_by="invoice_date",
        order_direction="desc",
    )
    record = page["records"][0]
    assert record["invoice_date_due"] is None
    assert record["partner_id"] == [10, "Acme Customer"]
    assert "invoice_line_ids" not in record
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert execs[1][3] == "account.move"
    assert ["move_type", "in", ["out_invoice", "out_refund"]] in execs[1][5][0]
    assert ["company_id", "=", 15] in execs[1][5][0]


def test_invoice_json2_uses_allowlisted_model_and_domain(fake_odoo, monkeypatch):
    fake_odoo.records = []
    original = json2.search_read

    def installed_account(*args, model, **kwargs):
        if model == "ir.module.module":
            return [{"name": "account"}]
        return original(*args, model=model, **kwargs)

    monkeypatch.setattr(json2, "search_read", installed_account)
    _read(
        resource="invoices",
        transport="json2",
        secret="valid-api-key",
        company_id=15,
        order_by="name",
    )
    url, body, _headers = fake_odoo.json2_calls[0]
    assert url.endswith("/json/2/account.move/search_read")
    assert ["move_type", "in", ["out_invoice", "out_refund"]] in body["domain"]
    assert ["company_id", "=", 15] in body["domain"]
    assert "invoice_line_ids" not in body["fields"]


def test_malformed_invoice_relation_is_rejected(fake_odoo):
    fake_odoo.records = [
        {
            "id": 20,
            "name": "INV/1",
            "move_type": "out_invoice",
            "state": "posted",
            "invoice_date": "2026-08-26",
            "invoice_date_due": False,
            "partner_id": ["bad-id", "Customer"],
            "currency_id": [2, "SAR"],
            "company_id": [15, "جمعية الاختبار"],
            "amount_total": 10.0,
            "amount_residual": 10.0,
            "payment_state": "not_paid",
        }
    ]
    with pytest.raises(ConnectorError) as exc:
        _read(resource="invoices", company_id=15)
    assert exc.value.code == "unsupported_response"


def test_installed_modules_policy_is_inventory_only():
    policy = get_policy("installed_modules")
    assert policy.odoo_model == "ir.module.module"
    assert policy.base_domain == (("state", "=", "installed"),)
    assert "state" not in policy.allowed_filter_fields
    assert "latest_version" not in policy.allowed_fields


def test_installed_module_read_uses_fixed_installed_domain(fake_odoo):
    fake_odoo.records = [
        {
            "id": 100,
            "name": "modeem_bms",
            "shortdesc": "Modeem Beneficiary Management",
            "installed_version": "16.0.1.0.0",
            "application": True,
            "category_id": [1, "Services"],
        }
    ]
    page = _read(resource="installed_modules", order_by="name")
    assert page["records"][0]["name"] == "modeem_bms"
    execs = [p for m, p in fake_odoo.xmlrpc_calls if m == "execute_kw"]
    assert execs[0][3] == "ir.module.module"
    assert ["state", "=", "installed"] in execs[0][5][0]
