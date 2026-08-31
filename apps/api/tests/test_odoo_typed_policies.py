"""Phase 2E tests — typed field policies + canonical Odoo login.

All network behavior is mocked; no real Odoo server is contacted.
"""

import json
import uuid
import xmlrpc.client

import httpx
import pytest

from app.integrations.odoo import http as safe_http
from app.integrations.odoo import json2, legacy_xmlrpc, reader, security
from app.integrations.odoo.errors import ConnectorError
from app.integrations.odoo.read_policies import READ_POLICIES, get_policy
from app.integrations.odoo.reader import ReadPolicyError
from app.models import AuditLog, Connection
from app.schemas.connections import OdooCredentials
from app.services.connection_auth import AuthMaterialError, resolve_auth_material
from tests.test_auth_security import _client, _csrf, _login
from tests.test_connections import SECRET, TestingSession, _create, _payload
from tests.test_odoo_read_preview import (
    COUNTRIES,
    FakeOdoo,
    _mock_client,
    _read,
    _tested_connection,
    _xmlrpc_response,
)

# re-exported fixtures come via conftest (roles_seed, etc.)


@pytest.fixture()
def allow_outbound(monkeypatch):
    monkeypatch.setattr(security, "enforce_outbound_policy", lambda url, environment: None)


@pytest.fixture()
def fake_odoo(monkeypatch, allow_outbound):
    server = FakeOdoo()
    monkeypatch.setattr(
        safe_http, "build_client", lambda *a, **k: _mock_client(server.handler)
    )
    return server


# --- Registry & typed policy (1-4) -------------------------------------------------


def test_registry_contains_exactly_approved_resources():
    assert set(READ_POLICIES) == {
        "countries",
        "beneficiaries_summary",
        "customers",
        "invoices",
        "installed_modules",
        "companies",
        "employees_summary",
        "departments_summary",
        "vendor_bills",
        "payments_summary",
        "journals_summary",
    }


def test_country_id_field_policy_is_integer():
    policy = get_policy("countries")
    assert policy.fields["id"].value_type == "integer"
    assert policy.fields["id"].nullable is False


def test_country_name_field_policy_is_string():
    policy = get_policy("countries")
    assert policy.fields["name"].value_type == "string"
    assert policy.fields["name"].max_length is not None


def test_country_code_field_policy_is_string():
    policy = get_policy("countries")
    assert policy.fields["code"].value_type == "string"
    assert policy.fields["code"].max_length is not None


# --- Output value validation (5-10) -------------------------------------------------


def _with_upstream(fake_odoo, rows):
    fake_odoo.raw_search_read_result = rows


def test_integer_field_rejects_bool_upstream(fake_odoo):
    _with_upstream(fake_odoo, [{"id": True, "name": "X", "code": "XX"}])
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"


def test_integer_field_rejects_string_upstream(fake_odoo):
    # A non-"id" integer check: use id in a non-id-key position is not
    # possible for countries, so exercise via the id field with a string.
    _with_upstream(fake_odoo, [{"id": "123", "name": "X", "code": "XX"}])
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"
    assert "123" not in str(exc.value)  # no raw value leaks


def test_string_field_rejects_integer_upstream(fake_odoo):
    _with_upstream(fake_odoo, [{"id": 1, "name": 123, "code": "XX"}])
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"


def test_overlength_string_rejected(fake_odoo):
    _with_upstream(fake_odoo, [{"id": 1, "name": "x" * 500, "code": "XX"}])
    with pytest.raises(ConnectorError) as exc:
        _read()
    assert exc.value.code == "unsupported_response"


def test_valid_country_response_succeeds(fake_odoo):
    page = _read()
    assert page["returned_count"] == len(COUNTRIES)
    assert page["records"][0] == COUNTRIES[0]


def test_extra_fields_still_dropped(fake_odoo):
    _with_upstream(fake_odoo, [{"id": 1, "name": "SA", "code": "SA", "vat": "LEAK"}])
    page = _read()
    assert page["records"] == [{"id": 1, "name": "SA", "code": "SA"}]


def test_null_nonnullable_field_rejected():
    # XML-RPC cannot marshal None, so exercise the sanitizer directly.
    policy = get_policy("countries")
    with pytest.raises(ConnectorError) as exc:
        reader._sanitize_records(
            [{"id": 1, "name": None, "code": "SA"}],
            policy,
            ["id", "name", "code"],
            max_expected=5,
        )
    assert exc.value.code == "unsupported_response"


# --- Filter type validation (11-19) ---------------------------------------------------


def test_filter_id_integer_accepted(fake_odoo):
    page = _read(filters=[{"field": "id", "operator": "=", "value": 5}])
    assert page["transport"] == "xmlrpc"


def test_filter_id_string_rejected_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "=", "value": "5"}])
    assert fake_odoo.xmlrpc_calls == []


def test_filter_name_string_accepted(fake_odoo):
    page = _read(filters=[{"field": "name", "operator": "=", "value": "Egypt"}])
    assert page is not None


def test_filter_name_integer_rejected_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "name", "operator": "=", "value": 123}])
    assert fake_odoo.xmlrpc_calls == []


def test_ilike_allowed_for_string_field(fake_odoo):
    page = _read(filters=[{"field": "name", "operator": "ilike", "value": "Saudi"}])
    assert page is not None


def test_ilike_rejected_for_integer_field(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "ilike", "value": "5"}])
    assert fake_odoo.xmlrpc_calls == []


def test_integer_in_list_accepted(fake_odoo):
    page = _read(filters=[{"field": "id", "operator": "in", "value": [1, 2, 3]}])
    assert page is not None


def test_mixed_type_in_list_rejected(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "in", "value": [1, "2"]}])
    assert fake_odoo.xmlrpc_calls == []


def test_all_policy_errors_before_network(fake_odoo):
    bad = [
        {"filters": [{"field": "id", "operator": "=", "value": "5"}]},
        {"filters": [{"field": "id", "operator": "ilike", "value": "x"}]},
        {"filters": [{"field": "name", "operator": "=", "value": True}]},
        {"filters": [{"field": "id", "operator": "in", "value": [True]}]},
        {"fields": ["vat"]},
        {"order_by": "vat"},
    ]
    for overrides in bad:
        with pytest.raises(ReadPolicyError):
            _read(**overrides)
    assert fake_odoo.xmlrpc_calls == [] and fake_odoo.json2_calls == []


def test_bool_not_accepted_for_integer_filter(fake_odoo):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "=", "value": True}])
    assert fake_odoo.xmlrpc_calls == []


# --- Credential schema (20-24) ---------------------------------------------------------


def test_odoo_credentials_rejects_login():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OdooCredentials(login="x", password_or_api_key="y")


def test_credentials_extra_fields_rejected(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    payload = _payload()
    payload["credentials"] = {"password_or_api_key": SECRET, "login": "smuggled"}
    res = client.post("/api/v1/connections", json=payload, headers=_csrf(client))
    assert res.status_code == 422


def test_connection_create_requires_username(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    payload = _payload()
    del payload["username"]
    res = client.post("/api/v1/connections", json=payload, headers=_csrf(client))
    assert res.status_code == 422


def test_whitespace_only_username_rejected(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    payload = _payload()
    payload["username"] = "   "
    res = client.post("/api/v1/connections", json=payload, headers=_csrf(client))
    assert res.status_code == 422


def test_username_is_trimmed(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    payload = _payload(name="Trimmed User Conn")
    payload["username"] = "  api-user  "
    res = client.post("/api/v1/connections", json=payload, headers=_csrf(client))
    assert res.status_code == 201
    assert res.json()["username"] == "api-user"


# --- Username update semantics (25-27) ---------------------------------------------------


def _patch(client, cid, body):
    return client.patch(f"/api/v1/connections/{cid}", json=body, headers=_csrf(client))


def test_update_omitting_username_preserves_it(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client).json()["id"]
    res = _patch(client, cid, {"name": "Renamed"})
    assert res.json()["username"] == "api-user"


def test_same_normalized_username_does_not_invalidate(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _patch(client, cid, {"username": "  api-user  "})
    assert res.status_code == 200
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    assert conn.last_test_status == "success"
    assert conn.selected_transport == "xmlrpc"
    db.close()


def test_username_change_invalidates_test_metadata(roles_seed):
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client)
    res = _patch(client, cid, {"username": "other-user"})
    assert res.status_code == 200
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    assert conn.last_test_status is None
    assert conn.selected_transport is None
    assert conn.detected_odoo_version is None
    assert conn.capabilities_json is None
    db.close()


# --- Canonical login usage (28-34) ---------------------------------------------------------


def _set_encrypted_payload(cid: str, payload: dict) -> None:
    from app.services.credential_crypto import encrypt_credentials

    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    blob, version = encrypt_credentials(
        payload, tenant_id=conn.tenant_id, connection_id=conn.id
    )
    conn.encrypted_credentials = blob
    conn.encryption_version = version
    db.commit()
    db.close()


def _capture_xmlrpc_logins(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params, method = xmlrpc.client.loads(request.content.decode())
        if url.endswith("/xmlrpc/2/common") and method == "version":
            return httpx.Response(
                200,
                content=_xmlrpc_response(
                    {"server_version": "18.0", "server_version_info": [18, 0, 0]}
                ),
            )
        if url.endswith("/xmlrpc/2/common") and method == "authenticate":
            seen.append(params[1])
            return httpx.Response(200, content=_xmlrpc_response(7))
        if url.endswith("/xmlrpc/2/object"):
            rpc_method = params[4]
            if rpc_method == "search_read":
                return httpx.Response(
                    200, content=_xmlrpc_response([dict(r) for r in COUNTRIES[:1]])
                )
            return httpx.Response(200, content=_xmlrpc_response(0))
        return httpx.Response(404)

    monkeypatch.setattr(safe_http, "build_client", lambda *a, **k: _mock_client(handler))
    monkeypatch.setattr(security, "enforce_outbound_policy", lambda url, environment: None)
    return seen


def test_test_connection_uses_connection_username(roles_seed, monkeypatch):
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client, name="Canon Test").json()["id"]
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 200 and res.json()["success"] is True
    assert seen and all(login == "api-user" for login in seen)


def test_read_preview_uses_connection_username(roles_seed, monkeypatch):
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="Canon Preview")
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "countries"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    assert seen and all(login == "api-user" for login in seen)


def test_legacy_encrypted_login_ignored(roles_seed, monkeypatch):
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="Legacy Payload")
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.username = "canonical@example.com"
    db.commit()
    db.close()
    _set_encrypted_payload(
        cid, {"login": "wrong@example.com", "password_or_api_key": SECRET}
    )
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "countries"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    assert seen and all(login == "canonical@example.com" for login in seen)
    assert "wrong@example.com" not in res.text


def test_legacy_login_never_in_outbound_request(roles_seed, monkeypatch):
    # Same scenario via Test Connection: the wire login must be canonical.
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client, name="Legacy Wire").json()["id"]
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.username = "canonical@example.com"
    db.commit()
    db.close()
    _set_encrypted_payload(
        cid, {"login": "wrong@example.com", "password_or_api_key": SECRET}
    )
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 200
    assert "wrong@example.com" not in seen
    assert seen and all(login == "canonical@example.com" for login in seen)


def test_missing_username_test_fails_before_network(roles_seed, monkeypatch):
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client, name="No Username").json()["id"]
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.username = None  # historical nullable record
    db.commit()
    db.close()
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert res.status_code == 409
    assert seen == []  # no network activity


def test_missing_username_preview_fails_before_network(roles_seed, monkeypatch):
    seen = _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="No Username Preview")
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    conn.username = None
    db.commit()
    db.close()
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "countries"},
        headers=_csrf(client),
    )
    assert res.status_code == 409
    assert seen == []


def test_secret_only_from_encrypted_payload():
    material = resolve_auth_material(
        "canonical@example.com",
        {"login": "wrong@example.com", "password_or_api_key": "s3cret"},
    )
    assert material.login == "canonical@example.com"
    assert material.secret == "s3cret"
    with pytest.raises(AuthMaterialError):
        resolve_auth_material("user", {"login": "x"})  # missing secret
    with pytest.raises(AuthMaterialError):
        resolve_auth_material("   ", {"password_or_api_key": "s"})


# --- Secret / audit hygiene (35-37) ----------------------------------------------------------


def test_responses_never_contain_secret(roles_seed, monkeypatch):
    _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client, name="Hygiene").json()["id"]
    res = client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    assert SECRET not in res.text
    res = client.get("/api/v1/connections")
    assert SECRET not in res.text


def test_audit_never_contains_secret_or_username(roles_seed, monkeypatch):
    _capture_xmlrpc_logins(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="Audit Hygiene")
    client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "countries"},
        headers=_csrf(client),
    )
    client.post(f"/api/v1/connections/{cid}/test", headers=_csrf(client))
    db = TestingSession()
    for entry in db.query(AuditLog).all():
        dump = str(entry.metadata_json)
        assert SECRET not in dump
        assert "api-user" not in dump  # canonical username not audited
    db.close()


# --- Scope guards (38-41) ---------------------------------------------------------------------


def test_only_approved_resources_are_registered():
    assert list(READ_POLICIES) == [
        "countries",
        "beneficiaries_summary",
        "customers",
        "invoices",
        "installed_modules",
        "companies",
        "employees_summary",
        "departments_summary",
        "vendor_bills",
        "payments_summary",
        "journals_summary",
    ]
    policy = READ_POLICIES["countries"]
    assert policy.odoo_model == "res.country"
    assert set(policy.fields) == {"id", "name", "code"}


def test_operational_resources_require_expected_modules_and_company_scope():
    expected = {
        "employees_summary": "hr",
        "departments_summary": "hr",
        "vendor_bills": "account",
        "payments_summary": "account",
        "journals_summary": "account",
    }
    for resource, module in expected.items():
        policy = READ_POLICIES[resource]
        assert policy.required_module == module
        assert policy.requires_company_scope is True


def test_company_scope_required_before_network(fake_odoo):
    with pytest.raises(ReadPolicyError, match="company_id is required"):
        _read(resource="employees_summary")
    assert fake_odoo.xmlrpc_calls == []


def test_employee_preview_checks_module_and_enforces_company_domain(fake_odoo):
    fake_odoo.records = [
        {
            "id": 7,
            "name": "موظف تجريبي",
            "job_title": "محاسب",
            "department_id": [3, "المالية"],
            "company_id": [15, "جمعية الاختبار"],
            "active": True,
        }
    ]
    page = _read(resource="employees_summary", company_id=15)
    assert page["records"][0]["company_id"] == [15, "جمعية الاختبار"]
    execs = [params for method, params in fake_odoo.xmlrpc_calls if method == "execute_kw"]
    assert len(execs) == 2
    assert execs[0][3] == "ir.module.module"
    assert execs[0][5] == [[["name", "=", "hr"], ["state", "=", "installed"]]]
    assert execs[1][3] == "hr.employee"
    assert ["company_id", "=", 15] in execs[1][5][0]


def test_missing_required_module_rejected_safely(fake_odoo, monkeypatch):
    from app.integrations.odoo.reader import ResourceUnavailableError

    original = legacy_xmlrpc.search_read

    def missing_module(*args, model, **kwargs):
        if model == "ir.module.module":
            return []
        return original(*args, model=model, **kwargs)

    monkeypatch.setattr(legacy_xmlrpc, "search_read", missing_module)
    with pytest.raises(ResourceUnavailableError, match="not installed"):
        _read(resource="vendor_bills", company_id=9)


def test_no_write_operations_exist_2e():
    import inspect

    for module in (reader, legacy_xmlrpc, json2):
        source = inspect.getsource(module)
        for banned in ('"create"', '"write"', '"unlink"', "'create'", "'write'", "'unlink'"):
            assert banned not in source


def test_no_local_record_persistence_2e():
    from app import models

    names = [n.lower() for n in dir(models)]
    for banned in ("country", "partner", "invoice", "employee", "syncrecord"):
        assert not any(banned in n for n in names)


def test_migration_chain_is_linear():
    """The alembic version graph must have exactly one head (no duplicate ids)."""
    import pathlib

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1


@pytest.mark.parametrize(
    ("existing_tables", "expected_upgrade"),
    [
        ({"operation_tasks", "operation_task_history"}, False),
        (set(), True),
    ],
)
def test_legacy_0007_operation_schema_is_converged(
    monkeypatch, existing_tables, expected_upgrade
):
    import pathlib

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    migration = ScriptDirectory.from_config(cfg).get_revision("0007").module
    calls = []
    monkeypatch.setattr(migration, "_table_names", lambda: existing_tables)
    monkeypatch.setattr(
        migration, "_upgrade_operation_schema", lambda: calls.append("singular")
    )

    migration.upgrade()

    assert ("singular" in calls) is expected_upgrade


def test_0008_ensures_singular_execution_schema_before_source_fields(monkeypatch):
    import pathlib
    from types import SimpleNamespace

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    migration = ScriptDirectory.from_config(cfg).get_revision("0008").module
    calls = []
    spec = SimpleNamespace(
        loader=SimpleNamespace(
            exec_module=lambda loaded: setattr(
                loaded, "upgrade", lambda: calls.append("singular")
            )
        )
    )
    monkeypatch.setattr(migration, "spec_from_file_location", lambda *_args: spec)
    monkeypatch.setattr(migration, "module_from_spec", lambda _spec: SimpleNamespace())

    migration._ensure_operation_schema()

    assert calls == ["singular"]


def test_capabilities_json_shape_unchanged(roles_seed):
    # Sanity: stored capabilities remain valid JSON after Phase 2E edits.
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="Caps Sanity")
    db = TestingSession()
    conn = db.get(Connection, uuid.UUID(cid))
    assert isinstance(json.loads(conn.capabilities_json), dict)
    db.close()
