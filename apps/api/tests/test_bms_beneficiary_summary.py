"""Phase 2F tests — BMS beneficiary summary read resource.

READ-ONLY policy-driven access to a privacy-approved SUMMARY subset of
modeem.bms.beneficiary. All network behavior is mocked; no real
Odoo/customer server is contacted.
"""

import json
import pathlib

import pytest

from app.integrations.odoo import http as safe_http
from app.integrations.odoo import reader, security
from app.integrations.odoo.errors import ConnectorError
from app.integrations.odoo.read_policies import READ_POLICIES, get_policy
from app.integrations.odoo.reader import ReadPolicyError
from app.models import AuditLog
from tests.test_auth_security import _client, _csrf, _login
from tests.test_connections import SECRET, TestingSession
from tests.test_odoo_read_preview import FakeOdoo, _mock_client
from tests.test_odoo_typed_policies import _tested_connection

BENEFICIARIES = [
    {
        "id": 10,
        "name": "Beneficiary One",
        "is_family": False,
        "total_draft_supports": 500,
        "total_paid_supports": 1000.5,
    },
    {
        "id": 11,
        "name": "Beneficiary Two",
        "is_family": True,
        "total_draft_supports": 0,
        "total_paid_supports": 0,
    },
]

SENSITIVE_FIELDS = {
    "id_type",
    "id_number",
    "birth_date",
    "age",
    "phone_number",
    "nationality",
    "gender",
    "family_id",
    "family_member_ids",
    "relationship_type",
    "beneficiary_type",
    "support_ids",
    "active",
    "create_uid",
    "write_uid",
    "create_date",
    "write_date",
    "message_ids",
    "activity_ids",
    "avatar_128",
    "image_1920",
}


@pytest.fixture()
def fake_bms(monkeypatch):
    monkeypatch.setattr(
        security, "enforce_outbound_policy", lambda url, environment: None
    )
    server = FakeOdoo(records=BENEFICIARIES)
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
        "resource": "beneficiaries_summary",
        "limit": 25,
        "offset": 0,
    }
    params.update(overrides)
    return reader.read_page(**params)


# --- Registry & field policy (spec 1-19) -------------------------------------


def test_registry_keeps_beneficiary_resource_registered():
    assert {"countries", "beneficiaries_summary"} <= set(READ_POLICIES)


def test_maps_exactly_to_bms_beneficiary_model():
    assert get_policy("beneficiaries_summary").odoo_model == "modeem.bms.beneficiary"


def test_approved_fields_exactly_five():
    policy = get_policy("beneficiaries_summary")
    assert policy.allowed_fields == {
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    }


def test_id_policy_integer_non_null():
    f = get_policy("beneficiaries_summary").fields["id"]
    assert f.value_type == "integer" and f.nullable is False


def test_name_policy_string_non_null_max_255():
    f = get_policy("beneficiaries_summary").fields["name"]
    assert f.value_type == "string" and f.nullable is False and f.max_length == 255


def test_is_family_policy_boolean_non_null():
    f = get_policy("beneficiaries_summary").fields["is_family"]
    assert f.value_type == "boolean" and f.nullable is False


def test_draft_total_policy_number_non_null():
    f = get_policy("beneficiaries_summary").fields["total_draft_supports"]
    assert f.value_type == "number" and f.nullable is False


def test_paid_total_policy_number_non_null():
    f = get_policy("beneficiaries_summary").fields["total_paid_supports"]
    assert f.value_type == "number" and f.nullable is False


@pytest.mark.parametrize("sensitive", sorted(SENSITIVE_FIELDS))
def test_sensitive_field_not_in_policy(sensitive):
    policy = get_policy("beneficiaries_summary")
    assert sensitive not in policy.allowed_fields
    assert sensitive not in policy.allowed_filter_fields
    assert sensitive not in policy.allowed_order_fields
    assert sensitive not in policy.default_fields


def test_default_fields_are_the_approved_five():
    assert get_policy("beneficiaries_summary").default_fields == (
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    )


def test_sensitive_field_request_rejected_before_network(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(fields=["id", "id_number"])
    assert fake_bms.xmlrpc_calls == [] and fake_bms.json2_calls == []


# --- Filters (spec 20-27) -----------------------------------------------------


def test_filter_id_integer_accepted(fake_bms):
    page = _read(filters=[{"field": "id", "operator": "=", "value": 10}])
    assert page["returned_count"] == len(BENEFICIARIES)


def test_filter_id_string_rejected_before_network(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "=", "value": "42"}])
    assert fake_bms.xmlrpc_calls == []


def test_filter_name_ilike_string_accepted(fake_bms):
    _read(filters=[{"field": "name", "operator": "ilike", "value": "Ahmed"}])


def test_filter_name_equals_string_accepted(fake_bms):
    _read(filters=[{"field": "name", "operator": "=", "value": "Ahmed"}])


def test_filter_name_integer_rejected_before_network(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "name", "operator": "=", "value": 123}])
    assert fake_bms.xmlrpc_calls == []


def test_filter_is_family_true_and_false_accepted(fake_bms):
    _read(filters=[{"field": "is_family", "operator": "=", "value": True}])
    _read(filters=[{"field": "is_family", "operator": "=", "value": False}])


def test_filter_is_family_integer_rejected(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "is_family", "operator": "=", "value": 1}])
    assert fake_bms.xmlrpc_calls == []


def test_filter_id_ilike_rejected(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "ilike", "value": "42"}])
    assert fake_bms.xmlrpc_calls == []


def test_mixed_in_list_rejected_before_network(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(filters=[{"field": "id", "operator": "in", "value": [1, "2"]}])
    assert fake_bms.xmlrpc_calls == []


def test_financial_totals_not_filterable(fake_bms):
    for fld in ("total_draft_supports", "total_paid_supports"):
        with pytest.raises(ReadPolicyError):
            _read(filters=[{"field": fld, "operator": "=", "value": 100}])
    assert fake_bms.xmlrpc_calls == []


# --- Ordering (spec 28-30) ------------------------------------------------------


def test_order_by_id_accepted(fake_bms):
    _read(order_by="id")


def test_order_by_name_accepted(fake_bms):
    _read(order_by="name")


def test_order_by_id_number_rejected(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(order_by="id_number")
    assert fake_bms.xmlrpc_calls == []


def test_order_by_financial_total_rejected(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(order_by="total_paid_supports")
    assert fake_bms.xmlrpc_calls == []


# --- Transport behavior (spec 31-34) ---------------------------------------------


def test_xmlrpc_uses_exact_model_and_search_read(fake_bms):
    _read(transport="xmlrpc")
    calls = [c for c in fake_bms.xmlrpc_calls if c[0] == "execute_kw"]
    assert calls, "expected an execute_kw call"
    params = calls[0][1]
    assert params[3] == "modeem.bms.beneficiary"
    assert params[4] == "search_read"


def test_xmlrpc_requests_only_approved_fields(fake_bms):
    _read(transport="xmlrpc")
    params = next(c for c in fake_bms.xmlrpc_calls if c[0] == "execute_kw")[1]
    kwargs = params[6]
    assert set(kwargs["fields"]) <= {
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    }


def test_json2_path_is_exact(fake_bms):
    _read(transport="json2", secret="valid-api-key")
    assert fake_bms.json2_calls, "expected a JSON-2 call"
    url = fake_bms.json2_calls[0][0]
    assert url.endswith("/json/2/modeem.bms.beneficiary/search_read")


def test_json2_payload_contains_only_validated_args(fake_bms):
    _read(
        transport="json2",
        secret="valid-api-key",
        filters=[{"field": "is_family", "operator": "=", "value": True}],
    )
    body = fake_bms.json2_calls[0][1]
    assert set(body["fields"]) <= {
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    }
    assert body["domain"] == [["is_family", "=", True]]


# --- Output sanitation (spec 35-41) ----------------------------------------------


def _with_upstream(fake_bms, rows):
    fake_bms.raw_search_read_result = rows


def test_extra_sensitive_upstream_fields_dropped(fake_bms):
    _with_upstream(
        fake_bms,
        [
            {
                "id": 10,
                "name": "Beneficiary",
                "is_family": False,
                "total_draft_supports": 500,
                "total_paid_supports": 1000,
                "id_number": "1234567890",
                "phone_number": "0501234567",
            }
        ],
    )
    page = _read()
    record = page["records"][0]
    assert set(record) == {
        "id",
        "name",
        "is_family",
        "total_draft_supports",
        "total_paid_supports",
    }


def test_id_number_never_in_output(fake_bms):
    _with_upstream(
        fake_bms,
        [dict(BENEFICIARIES[0], id_number="1234567890")],
    )
    page = _read()
    assert "1234567890" not in json.dumps(page)


def test_phone_number_never_in_output(fake_bms):
    _with_upstream(
        fake_bms,
        [dict(BENEFICIARIES[0], phone_number="0501234567")],
    )
    page = _read()
    assert "0501234567" not in json.dumps(page)


def test_malformed_boolean_fails_unsupported_response(fake_bms):
    _with_upstream(fake_bms, [dict(BENEFICIARIES[0], is_family=1)])
    with pytest.raises(ConnectorError) as e:
        _read()
    assert e.value.code == "unsupported_response"


def test_malformed_numeric_string_fails_unsupported_response(fake_bms):
    _with_upstream(fake_bms, [dict(BENEFICIARIES[0], total_paid_supports="100.0")])
    with pytest.raises(ConnectorError) as e:
        _read()
    assert e.value.code == "unsupported_response"


def test_bool_rejected_for_financial_number(fake_bms):
    _with_upstream(fake_bms, [dict(BENEFICIARIES[0], total_draft_supports=True)])
    with pytest.raises(ConnectorError) as e:
        _read()
    assert e.value.code == "unsupported_response"


def test_overlength_name_fails_safely(fake_bms):
    _with_upstream(fake_bms, [dict(BENEFICIARIES[0], name="x" * 256)])
    with pytest.raises(ConnectorError) as e:
        _read()
    assert e.value.code == "unsupported_response"
    assert "x" * 256 not in str(e.value)


def test_int_and_float_both_accepted_for_totals(fake_bms):
    _with_upstream(
        fake_bms,
        [dict(BENEFICIARIES[0], total_draft_supports=500, total_paid_supports=1000.5)],
    )
    page = _read()
    assert page["records"][0]["total_paid_supports"] == 1000.5


# --- Pagination (spec 42-43) ------------------------------------------------------


def test_returned_page_is_bounded(fake_bms):
    fake_bms.records = [
        {
            "id": i,
            "name": f"B{i}",
            "is_family": False,
            "total_draft_supports": 0,
            "total_paid_supports": 0,
        }
        for i in range(1, 60)
    ]
    page = _read(limit=25)
    assert page["returned_count"] == 25
    assert page["has_more"] is True
    assert page["next_offset"] == 25


def test_pagination_limits_unchanged(fake_bms):
    with pytest.raises(ReadPolicyError):
        _read(limit=51)
    with pytest.raises(ReadPolicyError):
        _read(limit=25, offset=1001)
    assert fake_bms.xmlrpc_calls == []


# --- API authorization & audit (spec 44-51) ---------------------------------------


def _bms_fake(monkeypatch):
    monkeypatch.setattr(
        security, "enforce_outbound_policy", lambda url, environment: None
    )
    server = FakeOdoo(records=BENEFICIARIES)
    monkeypatch.setattr(
        safe_http, "build_client", lambda *a, **k: _mock_client(server.handler)
    )
    return server


def _preview(client, cid, **overrides):
    body = {"resource": "beneficiaries_summary", "limit": 25, "offset": 0}
    body.update(overrides)
    return client.post(
        f"/api/v1/connections/{cid}/read-preview", json=body, headers=_csrf(client)
    )


def test_member_role_cannot_preview_bms(roles_seed, monkeypatch):
    _bms_fake(monkeypatch)
    owner = _client()
    _login(owner, "owner@example.com")
    cid = _tested_connection(owner, name="BMS Owner Conn")
    member = _client()
    _login(member, "member@example.com")
    res = _preview(member, cid)
    assert res.status_code in (403, 404)


def test_cross_tenant_preview_is_404(roles_seed, monkeypatch):
    _bms_fake(monkeypatch)
    owner = _client()
    _login(owner, "owner@example.com")
    cid = _tested_connection(owner, name="BMS Tenant Conn")
    other = _client()
    _login(other, "owner-b@example.com")
    res = _preview(other, cid)
    assert res.status_code == 404


def test_csrf_required_for_bms_preview(roles_seed, monkeypatch):
    _bms_fake(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="BMS CSRF Conn")
    res = client.post(
        f"/api/v1/connections/{cid}/read-preview",
        json={"resource": "beneficiaries_summary", "limit": 25, "offset": 0},
    )
    assert res.status_code in (403, 419)


def test_untested_connection_cannot_preview_bms(roles_seed, monkeypatch):
    from tests.test_connections import _create

    _bms_fake(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _create(client, name="BMS Untested Conn").json()["id"]
    res = _preview(client, cid)
    assert res.status_code == 409


def test_successful_bms_preview_and_audit_metadata_safe(roles_seed, monkeypatch):
    server = _bms_fake(monkeypatch)
    client = _client()
    _login(client, "owner@example.com")
    cid = _tested_connection(client, name="BMS Audit Conn")
    res = _preview(
        client,
        cid,
        filters=[{"field": "name", "operator": "ilike", "value": "Beneficiary One"}],
    )
    assert res.status_code == 200
    page = res.json()
    assert page["resource"] == "beneficiaries_summary"
    assert all(
        set(r)
        <= {"id", "name", "is_family", "total_draft_supports", "total_paid_supports"}
        for r in page["records"]
    )
    assert server.xmlrpc_calls or server.json2_calls

    # Audit rows must never contain record contents, names, or filter values.
    db = TestingSession()
    try:
        logs = db.query(AuditLog).filter(AuditLog.resource_id == cid).all()
        assert logs
        for log in logs:
            blob = json.dumps(log.metadata_json or {})
            assert "Beneficiary One" not in blob
            assert "Beneficiary Two" not in blob
            assert "filters" not in (log.metadata_json or {})
        preview_logs = [
            log
            for log in logs
            if (log.metadata_json or {}).get("resource") == "beneficiaries_summary"
        ]
        assert preview_logs, "read-preview audit row expected"
        meta = preview_logs[-1].metadata_json
        assert set(meta) <= {
            "resource",
            "transport",
            "requested_limit",
            "returned_count",
            "error_code",
            "success",
        }
    finally:
        db.close()


# --- Resource-unavailable behavior (spec: missing modeem_bms) ----------------------


def test_missing_bms_model_fails_safely(fake_bms, monkeypatch):
    import xmlrpc.client as xc

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/xmlrpc/2/common"):
            return httpx.Response(
                200, content=xc.dumps((7,), methodresponse=True).encode()
            )
        # Odoo raises a fault when the model does not exist.
        fault = xc.dumps(
            xc.Fault(2, "Object modeem.bms.beneficiary doesn't exist"),
            methodresponse=True,
        )
        return httpx.Response(200, content=fault.encode())

    monkeypatch.setattr(
        safe_http, "build_client", lambda *a, **k: _mock_client(handler)
    )
    with pytest.raises(ConnectorError) as e:
        _read()
    # Safe classification, never a raw traceback; static message only.
    assert e.value.code in ("unsupported_response", "upstream_error", "auth_failed")
    assert "Traceback" not in str(e.value)


# --- Scope guards (spec 52-60) ------------------------------------------------------


def test_countries_policy_unchanged():
    policy = get_policy("countries")
    assert policy.odoo_model == "res.country"
    assert policy.allowed_fields == {"id", "name", "code"}
    assert policy.default_fields == ("id", "name", "code")


def test_no_write_methods_in_odoo_integration():
    pkg = pathlib.Path(reader.__file__).parent
    for py in pkg.glob("*.py"):
        if py.name == "activity_writer.py":
            continue
        source = py.read_text()
        for forbidden in ('"create"', "'create'", '"write"', "'write'", '"unlink"', "'unlink'"):
            assert forbidden not in source, f"{py.name} references {forbidden}"
    writer_source = (pkg / "activity_writer.py").read_text()
    assert '"create"' in writer_source
    for forbidden in ('"write"', "'write'", '"unlink"', "'unlink'"):
        assert forbidden not in writer_source


def test_no_local_bms_persistence_model():
    from app import models

    names = {n.lower() for n in dir(models)}
    assert not any("beneficiar" in n or "support" in n or "bms" in n for n in names)


def test_no_bms_migration_exists():
    versions = (
        pathlib.Path(reader.__file__).resolve().parents[3] / "alembic" / "versions"
    )
    assert versions.is_dir()
    for p in versions.iterdir():
        lower = p.name.lower()
        assert "bms" not in lower and "beneficiar" not in lower and "support" not in lower


def test_no_support_resource_exists():
    for key in ("supports", "support_types", "beneficiary_groups", "family_members"):
        assert key not in READ_POLICIES


def test_no_family_expansion_fields():
    policy = get_policy("beneficiaries_summary")
    for fld in ("family_id", "family_member_ids", "support_ids"):
        assert fld not in policy.allowed_fields
