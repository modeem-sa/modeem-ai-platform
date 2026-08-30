"""Focused unit tests for the narrow invoice-activity write adapter."""

from contextlib import nullcontext

import pytest

from app.integrations.odoo import activity_writer
from app.integrations.odoo.activity_writer import ActivityWritePolicyError
from app.integrations.odoo.errors import ConnectorError


def _params(**overrides):
    params = {
        "base_url": "https://odoo.example.com",
        "database": "db",
        "transport": "xmlrpc",
        "login": "user",
        "secret": "never-log-this",
        "environment": "development",
        "company_id": 4,
        "invoice_id": 17,
        "activity_type_id": 3,
        "summary": "Review overdue invoice",
        "date_deadline": "2026-06-30",
        "idempotency_marker": "invoice-17-run-001",
    }
    params.update(overrides)
    return params


@pytest.fixture()
def fake_boundary(monkeypatch):
    monkeypatch.setattr(
        activity_writer.security, "enforce_outbound_policy", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        activity_writer.safe_http, "build_client", lambda environment: nullcontext(object())
    )
    calls = []
    activities = []

    def search(client, **kwargs):
        calls.append(("search", kwargs["model"], kwargs["domain"], kwargs["fields"]))
        if kwargs["model"] == "account.move":
            return [{"id": 17, "company_id": [4, "Company"], "move_type": "out_invoice"}]
        if kwargs["model"] == "ir.model":
            return [{"id": 91, "model": "account.move"}]
        if kwargs["model"] == "mail.activity.type":
            return [{"id": 3}]
        if kwargs["model"] == "mail.activity":
            return list(activities)
        raise AssertionError("unexpected model")

    def create(client, **kwargs):
        calls.append(("create", kwargs["transport"], dict(kwargs["values"])))
        activities.append(
            {
                "id": 501,
                "res_model_id": [91, "Invoice"],
                "res_id": 17,
                "summary": kwargs["values"]["summary"],
            }
        )
        return 501

    monkeypatch.setattr(activity_writer, "_search_read", search)
    monkeypatch.setattr(activity_writer, "_create_one_activity", create)
    return calls, activities


def test_create_is_fixed_bounded_and_verified(fake_boundary):
    calls, _activities = fake_boundary
    result = activity_writer.create_invoice_activity(**_params())
    assert result == {
        "operation": "invoice_activity",
        "activity_id": 501,
        "invoice_id": 17,
        "created": True,
        "idempotency_marker": "invoice-17-run-001",
        "transport": "xmlrpc",
    }
    creates = [call for call in calls if call[0] == "create"]
    assert len(creates) == 1
    assert creates[0][2] == {
        "activity_type_id": 3,
        "res_model_id": 91,
        "res_id": 17,
        "summary": "Review overdue invoice [Modeem:invoice-17-run-001]",
        "date_deadline": "2026-06-30",
    }
    assert [call[1] for call in calls if call[0] == "search"] == [
        "account.move",
        "ir.model",
        "mail.activity.type",
        "mail.activity",
        "mail.activity",
    ]


def test_retry_reconciles_same_marker_after_human_title_changes(fake_boundary):
    calls, activities = fake_boundary
    activities.append(
        {
            "id": 88,
            "res_model_id": [91, "Invoice"],
            "res_id": 17,
            "summary": "A changed human title [Modeem:invoice-17-run-001]",
        }
    )
    result = activity_writer.create_invoice_activity(**_params(transport="json2"))
    assert result["activity_id"] == 88
    assert result["created"] is False
    assert result["transport"] == "json2"
    assert not [call for call in calls if call[0] == "create"]
    activity_search = [
        call for call in calls if call[0] == "search" and call[1] == "mail.activity"
    ]
    assert activity_search[0][2] == [
        ["res_model_id", "=", 91],
        ["res_id", "=", 17],
        ["summary", "ilike", "[Modeem:invoice-17-run-001]"],
    ]


def test_public_reconcile_is_read_only(fake_boundary):
    calls, activities = fake_boundary
    activities.append(
        {
            "id": 88,
            "res_model_id": [91, "Invoice"],
            "res_id": 17,
            "summary": "Review overdue invoice [Modeem:invoice-17-run-001]",
        }
    )
    params = _params()
    params.pop("activity_type_id")
    params.pop("date_deadline")
    result = activity_writer.reconcile_invoice_activity(**params)
    assert result["found"] is True
    assert result["activity_id"] == 88
    assert not [call for call in calls if call[0] == "create"]


@pytest.mark.parametrize(
    "override",
    [
        {"invoice_id": True},
        {"company_id": 0},
        {"activity_type_id": "3"},
        {"summary": "bad\nsummary"},
        {"summary": "x" * 240},
        {"date_deadline": "30-06-2026"},
        {"idempotency_marker": "short"},
        {"idempotency_marker": "invoice marker with spaces"},
    ],
)
def test_invalid_inputs_fail_before_network(monkeypatch, override):
    touched = []
    monkeypatch.setattr(
        activity_writer.security,
        "enforce_outbound_policy",
        lambda *args, **kwargs: touched.append(True),
    )
    with pytest.raises(ActivityWritePolicyError):
        activity_writer.create_invoice_activity(**_params(**override))
    assert touched == []


def test_invoice_company_precondition_blocks_create(fake_boundary, monkeypatch):
    calls, _activities = fake_boundary

    def wrong_company(client, **kwargs):
        calls.append(("search", kwargs["model"], kwargs["domain"], kwargs["fields"]))
        if kwargs["model"] == "account.move":
            return []
        raise AssertionError("must stop after invoice lookup")

    monkeypatch.setattr(activity_writer, "_search_read", wrong_company)
    with pytest.raises(ActivityWritePolicyError, match="invoice is unavailable"):
        activity_writer.create_invoice_activity(**_params())
    assert not [call for call in calls if call[0] == "create"]


def test_stale_transport_rejected_before_network(monkeypatch):
    touched = []
    monkeypatch.setattr(
        activity_writer.security,
        "enforce_outbound_policy",
        lambda *args, **kwargs: touched.append(True),
    )
    with pytest.raises(ConnectorError) as exc:
        activity_writer.create_invoice_activity(**_params(transport="generic-rpc"))
    assert exc.value.code == "invalid_configuration"
    assert touched == []


def test_reconcile_requires_exact_typed_activity(fake_boundary):
    _calls, activities = fake_boundary
    activities.append(
        {
            "id": 88,
            "res_model_id": [91, "Invoice"],
            "res_id": 17,
            "summary": "different",
        }
    )
    with pytest.raises(ConnectorError) as exc:
        activity_writer.create_invoice_activity(**_params())
    assert exc.value.code == "unsupported_response"


@pytest.mark.parametrize(
    "activity",
    [
        {
            "id": 88,
            "res_model_id": [91, "Invoice"],
            "res_id": 17,
            "summary": "Review overdue invoice [Modeem:invoice-17-run-002]",
        },
        {
            "id": 88,
            "res_model_id": [91, "Invoice"],
            "res_id": 18,
            "summary": "Review overdue invoice [Modeem:invoice-17-run-001]",
        },
    ],
)
def test_reconcile_rejects_wrong_marker_or_invoice(fake_boundary, activity):
    _calls, activities = fake_boundary
    activities.append(activity)
    with pytest.raises(ConnectorError) as exc:
        activity_writer.create_invoice_activity(**_params())
    assert exc.value.code == "unsupported_response"