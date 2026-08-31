"""Task 46: bounded, tenant- and company-scoped Odoo financial reads."""

import uuid

import pytest

from app.integrations.odoo import reader
from app.integrations.odoo.reader import ReadPolicyError
from app.models import AuditLog, Connection
from tests.test_auth_security import _client, _csrf, _login
from tests.test_connections import TestingSession
from tests.test_odoo_read_preview import _tested_connection


def _ready_financial_connection(client, *, company_id=15) -> str:
    connection_id = _tested_connection(client, name=f"Finance {uuid.uuid4()}")
    db = TestingSession()
    connection = db.get(Connection, uuid.UUID(connection_id))
    connection.odoo_company_id = company_id
    db.commit()
    db.close()
    return connection_id


def _financial_read(client, connection_id, body):
    return client.post(
        f"/api/v1/connections/{connection_id}/financial-read",
        json=body,
        headers=_csrf(client),
    )


@pytest.fixture()
def stub_financial_page(monkeypatch):
    calls = []

    def fake_read_page(**kwargs):
        calls.append(kwargs)
        return {
            "resource": kwargs["resource"],
            "fields": ["id", "name", "date"],
            "records": [{"id": 91, "name": "MISC/2026/0091", "date": "2026-08-31"}],
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "returned_count": 1,
            "has_more": False,
            "next_offset": None,
            "transport": kwargs["transport"],
        }

    monkeypatch.setattr(reader, "read_page", fake_read_page)
    return calls


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "member", "viewer"])
def test_active_members_can_read_financial_data(roles_seed, stub_financial_page, role):
    owner = _client()
    _login(owner, "owner@example.com")
    connection_id = _ready_financial_connection(owner)

    client = _client()
    _login(client, f"{role}@example.com")
    response = _financial_read(
        client,
        connection_id,
        {"resource": "journal_entries", "order_by": "date"},
    )

    assert response.status_code == 200
    assert response.json()["source_company_id"] == 15
    assert response.json()["source_name"].startswith("Finance ")
    assert response.json()["read_at"]
    assert stub_financial_page[-1]["company_id"] == 15


def test_company_scope_is_derived_from_connection(roles_seed, stub_financial_page):
    client = _client()
    _login(client, "owner@example.com")
    connection_id = _ready_financial_connection(client, company_id=27)

    response = _financial_read(
        client,
        connection_id,
        {"resource": "journal_items", "filters": [{"field": "move_id", "operator": "=", "value": 91}]},
    )

    assert response.status_code == 200
    assert stub_financial_page[-1]["company_id"] == 27
    assert stub_financial_page[-1]["filters"] == [
        {"field": "move_id", "operator": "=", "value": 91}
    ]


def test_financial_endpoint_rejects_non_financial_resources(roles_seed, stub_financial_page):
    client = _client()
    _login(client, "owner@example.com")
    connection_id = _ready_financial_connection(client)

    response = _financial_read(client, connection_id, {"resource": "customers"})

    assert response.status_code == 422
    assert stub_financial_page == []


def test_financial_read_is_tenant_scoped(roles_seed, stub_financial_page):
    owner_a = _client()
    _login(owner_a, "owner@example.com")
    connection_id = _ready_financial_connection(owner_a)

    owner_b = _client()
    _login(owner_b, "owner-b@example.com")
    response = _financial_read(owner_b, connection_id, {"resource": "journal_entries"})

    assert response.status_code == 404
    assert stub_financial_page == []


def test_financial_read_requires_csrf(roles_seed, stub_financial_page):
    client = _client()
    _login(client, "owner@example.com")
    connection_id = _ready_financial_connection(client)

    response = client.post(
        f"/api/v1/connections/{connection_id}/financial-read",
        json={"resource": "journal_entries"},
    )

    assert response.status_code == 403
    assert stub_financial_page == []


def test_financial_read_audit_omits_filter_values_and_records(
    roles_seed, stub_financial_page
):
    client = _client()
    _login(client, "owner@example.com")
    connection_id = _ready_financial_connection(client)
    secret_filter = "MISC-PRIVATE-FILTER"

    response = _financial_read(
        client,
        connection_id,
        {
            "resource": "journal_entries",
            "filters": [{"field": "name", "operator": "ilike", "value": secret_filter}],
        },
    )

    assert response.status_code == 200
    db = TestingSession()
    entry = (
        db.query(AuditLog)
        .filter(AuditLog.action == "connection.financial_read_succeeded")
        .one()
    )
    dump = str(entry.metadata_json)
    db.close()
    assert secret_filter not in dump
    assert "MISC/2026/0091" not in dump
    assert entry.metadata_json["company_id"] == 15
    assert entry.metadata_json["filter_count"] == 1


def test_journal_policies_are_read_only_and_minimal():
    entries = reader.get_policy("journal_entries")
    items = reader.get_policy("journal_items")

    assert entries.odoo_model == "account.move"
    assert entries.base_domain == (("move_type", "=", "entry"),)
    assert "line_ids" not in entries.allowed_fields
    assert "narration" not in entries.allowed_fields
    assert items.odoo_model == "account.move.line"
    assert items.base_domain == (
        ("move_id.move_type", "=", "entry"),
        ("display_type", "=", False),
    )
    assert "analytic_distribution" not in items.allowed_fields
    assert "reconciled" not in items.allowed_fields


def test_journal_item_move_filter_accepts_only_positive_integer():
    policy = reader.get_policy("journal_items")
    assert reader._validate_filters(
        policy, [{"field": "move_id", "operator": "=", "value": 91}]
    ) == [["move_id", "=", 91]]
    for invalid in ("91", True, 0, -1):
        with pytest.raises(ReadPolicyError):
            reader._validate_filters(
                policy, [{"field": "move_id", "operator": "=", "value": invalid}]
            )


def test_range_operators_are_limited_to_dates_and_numbers():
    entries = reader.get_policy("journal_entries")
    assert reader._validate_filters(
        entries, [{"field": "date", "operator": ">=", "value": "2026-08-01"}]
    ) == [["date", ">=", "2026-08-01"]]
    with pytest.raises(ReadPolicyError, match="range operator"):
        reader._validate_filters(
            entries, [{"field": "name", "operator": ">=", "value": "MISC"}]
        )
    payments = reader.get_policy("payments_summary")
    assert reader._validate_filters(
        payments, [{"field": "date", "operator": "<=", "value": "2026-08-31"}]
    ) == [["date", "<=", "2026-08-31"]]