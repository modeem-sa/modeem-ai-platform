"""Request-bound AI Workbench authorization and persistence tests."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import workbench as workbench_api
from app.content_manager.provider import ProviderUnavailableError
from app.core.security import hash_password
from app.main import app
from app.models import (
    AgentMessage,
    AgentSession,
    AgentToolCall,
    AuditLog,
    Connection,
    OperationAction,
    OperationActionHistory,
    OperationTask,
    ServiceRequest,
    TenantMembership,
    User,
)
from app.operations.workbench_actions import _action_out
from app.operations.workbench_tools import (
    CUSTOMER_INVOICES_TOOL_KEY,
    FINANCE_TOOLS,
    RECEIVABLES_TOOL_KEY,
    RECENT_PAYMENTS_TOOL_KEY,
    VENDOR_BILLS_TOOL_KEY,
    InvoiceLookupInput,
    OverdueInvoicesInput,
    ReceivablesInput,
    RecentPaymentsInput,
    VendorBillsInput,
    execute_finance_tool,
    execute_overdue_customer_invoices,
    finance_tool_input_from_instruction,
    select_finance_tool,
)
from tests.test_auth_security import PASSWORD, TestingSession


def _client(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["modeem_csrf"]}


def _fixture(seed):
    db = TestingSession()
    customer = User(
        email="workbench-customer@example.com",
        full_name="Workbench Customer",
        password_hash=hash_password(PASSWORD),
    )
    employee = User(
        email="workbench-employee@example.com",
        full_name="Workbench Employee",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([customer, employee])
    db.flush()
    db.add_all(
        [
            TenantMembership(tenant_id=seed["tenant_a"], user_id=customer.id, role="customer"),
            TenantMembership(tenant_id=seed["tenant_a"], user_id=employee.id, role="member"),
            Connection(
                tenant_id=seed["tenant_a"],
                name="Test Odoo",
                provider="odoo",
                base_url="https://odoo.example.invalid",
                selected_transport="json2",
                status="configured",
                is_active=True,
                last_test_status="success",
                odoo_company_id=1,
                encrypted_credentials=b"encrypted-test-value",
                encryption_version=1,
            ),
        ]
    )
    request = ServiceRequest(
        tenant_id=seed["tenant_a"],
        requester_id=customer.id,
        assigned_employee_id=employee.id,
        subject="تقرير فواتير متأخرة",
        description="أحتاج تقريراً بالفواتير المتأخرة أكثر من 30 يوماً.",
        priority="medium",
        source="portal",
        status="open",
        automation_status="none",
        public_reference="SR-WORKBENCH",
        version=1,
    )
    db.add(request)
    db.commit()
    result = {"request": request.id, "employee": employee.id, "customer": customer.id}
    db.close()
    return result


class FakeProvider:
    model = "workbench-test-model"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _analysis():
    return {
        "request_summary": "استخراج الفواتير المتأخرة.",
        "customer_goal": "إعداد تقرير للمراجعة.",
        "service_category": "financial",
        "required_information": ["رقم الفاتورة", "تاريخ الاستحقاق"],
        "missing_information": [],
        "suggested_steps": ["قراءة البيانات", "تجهيز التقرير"],
        "potential_risks": ["تحتاج النتائج إلى مراجعة الموظف."],
        "data_sources_needed": ["نظام المحاسبة"],
        "approval_likely_required": False,
    }


def _enable_finance_connection(seed):
    db = TestingSession()
    connection = (
        db.query(Connection)
        .filter(Connection.tenant_id == seed["tenant_a"], Connection.provider == "odoo")
        .order_by(Connection.created_at.desc())
        .first()
    )
    connection.odoo_company_id = 1
    db.commit()
    db.close()


def _invoice(
    invoice_id: int,
    *,
    due_date: date,
    residual: float,
    currency_id: int = 1,
    currency: str = "SAR",
    customer_id: int = 10,
):
    return {
        "id": invoice_id,
        "name": f"INV/{invoice_id:04d}",
        "move_type": "out_invoice",
        "state": "posted",
        "invoice_date": (due_date - timedelta(days=10)).isoformat(),
        "invoice_date_due": due_date.isoformat(),
        "partner_id": [customer_id, f"Customer {customer_id}"],
        "currency_id": [currency_id, currency],
        "company_id": [1, "Main Company"],
        "amount_total": residual + 100,
        "amount_residual": residual,
        "payment_state": "partial",
    }


def _single_page(records):
    def read_page(_connection, *, limit, offset, filters, **_kwargs):
        page_records = records[offset : offset + limit]
        next_offset = offset + len(page_records)
        return {
            "records": page_records,
            "offset": offset,
            "returned_count": len(page_records),
            "has_more": next_offset < len(records),
            "next_offset": next_offset if next_offset < len(records) else None,
        }

    return read_page


def test_customer_cannot_create_or_read_workbench_session(seed):
    data = _fixture(seed)
    client = _client("workbench-customer@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/session"
    response = client.post(path, json={}, headers=_csrf(client))
    assert response.status_code == 404
    assert client.get(path).status_code == 404

    detail = client.get(f"/api/v1/service-requests/{data['request']}")
    assert detail.status_code == 200
    assert detail.json()["can_use_workbench"] is False


def test_employee_can_resume_analyze_and_keep_internal_messages_separate(seed, monkeypatch):
    data = _fixture(seed)
    provider = FakeProvider(_analysis())
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/session"
    started = client.post(path, json={"locale": "ar"}, headers=_csrf(client))
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]

    analyzed = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/analyze",
        json={"locale": "ar"},
        headers=_csrf(client),
    )
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["session"]["analysis"]["request_summary"]
    assert analyzed.json()["session"]["id"] == session_id
    assert analyzed.json()["messages"][0]["role"] == "assistant"
    assert "credentials" not in str(provider.calls[0]["user_payload"]).lower()
    resumed = client.post(path, json={}, headers=_csrf(client))
    assert resumed.status_code == 200
    assert resumed.json()["session"]["id"] == session_id

    db = TestingSession()
    assert db.query(AgentSession).count() == 1
    assert db.query(AgentMessage).count() == 1
    assert {row.action for row in db.query(AuditLog).all()} >= {
        "agent_session_created",
        "agent_analysis_started",
        "agent_analysis_completed",
    }
    db.close()


def test_conversation_context_is_bounded_ordered_and_session_scoped(seed, monkeypatch):
    data = _fixture(seed)
    db = TestingSession()
    other_request = ServiceRequest(
        tenant_id=seed["tenant_a"],
        requester_id=data["customer"],
        assigned_employee_id=data["employee"],
        subject="طلب سياق آخر",
        description="طلب منفصل.",
        priority="medium",
        source="portal",
        status="open",
        automation_status="none",
        public_reference="SR-WORKBENCH-CONTEXT-OTHER",
        version=1,
    )
    db.add(other_request)
    db.flush()
    other_session = AgentSession(
        tenant_id=seed["tenant_a"],
        service_request_id=other_request.id,
        employee_user_id=data["employee"],
        status="active",
    )
    db.add(other_session)
    db.flush()
    db.add(
        AgentMessage(
            session_id=other_session.id,
            tenant_id=seed["tenant_a"],
            role="user",
            content="محتوى من جلسة أخرى يجب ألا يظهر",
        )
    )
    db.commit()
    db.close()
    provider = FakeProvider(_analysis())
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/messages"
    assert client.post(
        path,
        json={"content": "السؤال الأول"},
        headers=_csrf(client),
    ).status_code == 200
    assert client.post(
        path,
        json={"content": "السؤال الثاني"},
        headers=_csrf(client),
    ).status_code == 200
    context = provider.calls[1]["user_payload"]["conversation"]
    assert [item["role"] for item in context] == ["user", "assistant"]
    assert context[0]["content"] == "السؤال الأول"
    assert context[1]["content"] == _analysis()["request_summary"]
    assert all("جلسة أخرى" not in item["content"] for item in context)
    assert all(set(item) == {"role", "content"} for item in context)
    assert len(context) <= workbench_api.MAX_CONTEXT_TURNS
    assert sum(len(item["content"]) for item in context) <= workbench_api.MAX_CONTEXT_CHARS


def test_request_and_connection_context_are_server_owned_and_body_is_strict(seed):
    data = _fixture(seed)
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/session"
    response = client.post(
        path,
        json={"locale": "ar", "tenant_id": str(seed["tenant_b"]), "connection_id": "attacker"},
        headers=_csrf(client),
    )
    assert response.status_code == 422

    message_response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/messages",
        json={
            "content": "حلل الطلب",
            "locale": "ar",
            "tenant_id": str(seed["tenant_b"]),
            "connection_id": "attacker",
        },
        headers=_csrf(client),
    )
    assert message_response.status_code == 422

    db = TestingSession()
    session = (
        db.query(AgentSession)
        .filter_by(service_request_id=data["request"], employee_user_id=data["employee"])
        .one_or_none()
    )
    assert session is None
    db.close()


def test_cross_tenant_employee_cannot_access_request_workbench(seed):
    data = _fixture(seed)
    client = _client("b@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/session"
    assert client.get(path).status_code == 404
    assert client.post(path, json={}, headers=_csrf(client)).status_code == 404


def test_workbench_session_is_bound_to_exact_request(seed, monkeypatch):
    data = _fixture(seed)
    provider = FakeProvider(_analysis())
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client("workbench-employee@example.com")
    first_path = f"/api/v1/service-requests/{data['request']}/agent/session"
    assert client.post(first_path, json={}, headers=_csrf(client)).status_code == 200

    db = TestingSession()
    second = ServiceRequest(
        tenant_id=seed["tenant_a"],
        requester_id=data["customer"],
        assigned_employee_id=data["employee"],
        subject="طلب ثان",
        description="طلب مستقل.",
        priority="medium",
        source="portal",
        status="open",
        automation_status="none",
        public_reference="SR-WORKBENCH-SECOND",
        version=1,
    )
    db.add(second)
    db.commit()
    second_id = second.id
    db.close()

    second_path = f"/api/v1/service-requests/{second_id}/agent/session"
    response = client.get(second_path)
    assert response.status_code == 200
    assert response.json()["session"] is None
    assert response.json().get("can_use_workbench") is None

    detail = client.get(f"/api/v1/service-requests/{data['request']}")
    assert detail.status_code == 200
    assert detail.json()["can_use_workbench"] is True


def test_malformed_provider_output_is_rejected_and_session_failed(seed, monkeypatch):
    data = _fixture(seed)
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: FakeProvider({"unexpected": "value"})),
    )
    client = _client("workbench-employee@example.com")
    response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/analyze",
        json={"locale": "en"},
        headers=_csrf(client),
    )
    assert response.status_code == 502
    db = TestingSession()
    session = db.query(AgentSession).one()
    assert session.status == "failed"
    assert any(row.action == "agent_provider_failed" for row in db.query(AuditLog).all())
    db.close()


def test_missing_provider_fails_safely_and_records_audit(seed, monkeypatch):
    data = _fixture(seed)
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(ProviderUnavailableError())),
    )
    client = _client("workbench-employee@example.com")
    response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/analyze",
        json={},
        headers=_csrf(client),
    )
    assert response.status_code == 503
    db = TestingSession()
    assert any(row.action == "agent_provider_failed" for row in db.query(AuditLog).all())
    db.close()


def test_message_provider_failure_commits_user_message_and_audits_it(seed, monkeypatch):
    data = _fixture(seed)
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(ProviderUnavailableError())),
    )
    client = _client("workbench-employee@example.com")
    response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/messages",
        json={"content": "تعليمات محفوظة عند الفشل"},
        headers=_csrf(client),
    )
    assert response.status_code == 503
    db = TestingSession()
    message = db.query(AgentMessage).one()
    assert message.role == "user"
    audits = db.query(AuditLog).all()
    assert any(row.action == "agent_provider_failed" for row in audits)
    assert any(
        row.action == "agent_message_created"
        and row.metadata_json["message_id"] == str(message.id)
        and row.metadata_json["message_role"] == "user"
        for row in audits
    )
    db.close()


def test_internal_agent_messages_never_appear_in_customer_request_messages(seed, monkeypatch):
    data = _fixture(seed)
    provider = FakeProvider(_analysis())
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    employee = _client("workbench-employee@example.com")
    assert employee.post(
        f"/api/v1/service-requests/{data['request']}/agent/analyze",
        json={},
        headers=_csrf(employee),
    ).status_code == 200
    detail = employee.get(f"/api/v1/service-requests/{data['request']}")
    assert detail.status_code == 200
    assert all(message["body"] != _analysis()["request_summary"] for message in detail.json()["messages"])

    db = TestingSession()
    assert db.query(AgentMessage).count() == 1
    db.close()


def test_successful_employee_message_audits_without_raw_content(seed, monkeypatch):
    data = _fixture(seed)
    provider = FakeProvider(_analysis())
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    client = _client("workbench-employee@example.com")
    response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/messages",
        json={"content": "هذه تعليمات داخلية سرية"},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    db = TestingSession()
    audit = [row for row in db.query(AuditLog).all() if row.action == "agent_message_created"]
    assert {row.metadata_json["message_role"] for row in audit} == {"user", "assistant"}
    assert all("هذه تعليمات داخلية سرية" not in str(row.metadata_json) for row in audit)
    assert all("message_id" in row.metadata_json for row in audit)
    db.close()


def test_overdue_tool_calculates_threshold_aging_and_currency_totals(seed):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = date(2026, 9, 21)
    records = [
        _invoice(6, due_date=as_of, residual=999),
        _invoice(1, due_date=as_of - timedelta(days=30), residual=100),
        _invoice(2, due_date=as_of - timedelta(days=31), residual=200),
        _invoice(3, due_date=as_of - timedelta(days=61), residual=300),
        _invoice(4, due_date=as_of - timedelta(days=91), residual=400),
        _invoice(
            5,
            due_date=as_of - timedelta(days=45),
            residual=50,
            currency_id=2,
            currency="USD",
        ),
    ]
    db = TestingSession()
    actor = db.get(User, data["employee"])
    request = db.get(ServiceRequest, data["request"])
    connection = (
        db.query(Connection)
        .filter(Connection.tenant_id == seed["tenant_a"], Connection.provider == "odoo")
        .first()
    )
    result = execute_overdue_customer_invoices(
        db=db,
        actor=actor,
        request=request,
        connection=connection,
        tool_input=OverdueInvoicesInput(minimum_days_overdue=30, max_records=100),
        read_page=_single_page(records),
        today=as_of,
    )
    db.close()

    assert [item.days_overdue for item in result.invoices] == [30, 31, 61, 91, 45]
    assert result.returned_count == 5
    assert result.complete is True
    totals = {item.currency: item for item in result.totals_by_currency}
    assert totals["SAR"].outstanding_amount == "1000.00"
    assert totals["SAR"].aging.model_dump() == {
        "days_0_30": "100.00",
        "days_31_60": "200.00",
        "days_61_90": "300.00",
        "over_90_days": "400.00",
    }
    assert totals["USD"].outstanding_amount == "50.00"
    assert len(result.totals_by_currency) == 2


def test_finance_tool_threshold_extraction_is_bounded_and_deterministic():
    assert (
        finance_tool_input_from_instruction("اعرض الفواتير المتأخرة أكثر من 60 يومًا")
        .minimum_days_overdue
        == 60
    )
    assert (
        finance_tool_input_from_instruction("Show invoices overdue 45 days")
        .minimum_days_overdue
        == 45
    )
    assert finance_tool_input_from_instruction("فواتير متأخرة").minimum_days_overdue == 30
    with pytest.raises(HTTPException) as exc:
        finance_tool_input_from_instruction("فواتير متأخرة 0 يوم")
    assert exc.value.status_code == 422


def test_overdue_tool_paginates_and_marks_incomplete_totals(seed):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = date(2026, 9, 21)
    records = [
        _invoice(index, due_date=as_of - timedelta(days=40), residual=10)
        for index in range(1, 122)
    ]
    offsets = []

    def read_page(_connection, *, limit, offset, **_kwargs):
        offsets.append(offset)
        page_records = records[offset : offset + limit]
        next_offset = offset + len(page_records)
        return {
            "records": page_records,
            "offset": offset,
            "returned_count": len(page_records),
            "has_more": next_offset < len(records),
            "next_offset": next_offset if next_offset < len(records) else None,
        }

    db = TestingSession()
    result = execute_overdue_customer_invoices(
        db=db,
        actor=db.get(User, data["employee"]),
        request=db.get(ServiceRequest, data["request"]),
        connection=db.query(Connection).filter_by(tenant_id=seed["tenant_a"]).first(),
        tool_input=OverdueInvoicesInput(minimum_days_overdue=30, max_records=100),
        read_page=read_page,
        today=as_of,
    )
    db.close()

    assert offsets == [0, 50]
    assert result.returned_count == 100
    assert result.result_truncated is True
    assert result.needs_narrower_filter is True
    assert result.complete is False
    assert result.totals_by_currency == []


def test_employee_message_selects_read_only_finance_tool_and_audits(seed, monkeypatch):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = datetime.now(UTC).date()
    seen = {}

    def read_page(connection, **kwargs):
        seen["connection_id"] = connection.id
        seen["kwargs"] = kwargs
        return _single_page(
            [_invoice(1, due_date=as_of - timedelta(days=40), residual=245000)]
        )(connection, **kwargs)

    monkeypatch.setattr(workbench_api, "_operations_read_page", read_page)
    monkeypatch.setattr(
        workbench_api.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("provider must not select tools"))),
    )
    client = _client("workbench-employee@example.com")
    response = client.post(
        f"/api/v1/service-requests/{data['request']}/agent/messages",
        json={"content": "نفذ تحليل الفواتير المتأخرة.", "locale": "ar"},
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool_calls"][0]["tool_key"] == "finance.get_overdue_customer_invoices"
    assert body["tool_calls"][0]["mode"] == "read"
    assert body["tool_calls"][0]["result"]["returned_count"] == 1
    assert body["tool_calls"][0]["result"]["connection_name"] == "Test Odoo"
    assert seen["kwargs"]["resource"] == "invoices"
    assert seen["kwargs"]["company_scoped"] is True
    assert seen["kwargs"]["order_by"] == "id"
    assert seen["kwargs"]["order_direction"] == "asc"
    assert {item["field"] for item in seen["kwargs"]["filters"]} == {
        "move_type",
        "state",
        "payment_state",
        "invoice_date_due",
        "amount_residual",
    }

    db = TestingSession()
    call = db.query(AgentToolCall).one()
    assert call.status == "completed"
    assert call.mode == "read"
    assert "Customer 10" not in call.safe_result_summary_json
    assert "INV/0001" not in call.safe_result_summary_json
    assert '"invoices"' not in call.safe_result_summary_json
    audits = db.query(AuditLog).filter(AuditLog.resource_id == str(call.id)).all()
    assert {row.action for row in audits} == {
        "agent_tool_started",
        "agent_tool_completed",
    }
    assert all("245000" not in str(row.metadata_json) for row in audits)
    db.close()


def test_finance_tool_body_cannot_inject_tenant_connection_or_unknown_tool(seed):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/tools/execute"
    injected = client.post(
        path,
        json={
            "tool_key": "finance.get_overdue_customer_invoices",
            "input": {"minimum_days_overdue": 30, "max_records": 50},
            "tenant_id": str(seed["tenant_b"]),
            "connection_id": "attacker",
        },
        headers=_csrf(client),
    )
    assert injected.status_code == 422
    invented = client.post(
        path,
        json={"tool_key": "finance.raw_odoo_query", "input": {}},
        headers=_csrf(client),
    )
    assert invented.status_code == 422


def test_customer_and_cross_tenant_employee_cannot_execute_finance_tool(seed):
    data = _fixture(seed)
    path = f"/api/v1/service-requests/{data['request']}/agent/tools/execute"
    customer = _client("workbench-customer@example.com")
    assert customer.post(path, json={}, headers=_csrf(customer)).status_code == 404
    other_employee = _client("b@example.com")
    assert (
        other_employee.post(path, json={}, headers=_csrf(other_employee)).status_code
        == 404
    )


def test_collection_followup_action_is_server_bound_reviewable_and_approval_only(
    seed, monkeypatch
):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = date(2026, 9, 21)
    monkeypatch.setattr(
        workbench_api,
        "_operations_read_page",
        _single_page([_invoice(1, due_date=as_of - timedelta(days=40), residual=245)]),
    )
    employee = _client("workbench-employee@example.com")
    request_path = f"/api/v1/service-requests/{data['request']}"
    assert employee.post(
        f"{request_path}/agent/session", json={}, headers=_csrf(employee)
    ).status_code == 200
    read = employee.post(
        f"{request_path}/agent/tools/execute",
        json={
            "tool_key": "finance.get_overdue_customer_invoices",
            "input": {"minimum_days_overdue": 30, "max_records": 100},
        },
        headers=_csrf(employee),
    )
    assert read.status_code == 200, read.text
    source_call_id = read.json()["tool_calls"][0]["id"]

    prepare = employee.post(
        f"{request_path}/agent/actions/prepare",
        json={"source_tool_call_id": source_call_id, "locale": "en"},
        headers=_csrf(employee),
    )
    assert prepare.status_code == 200, prepare.text
    action = prepare.json()["action"]
    assert action["status"] == "proposed"
    assert action["proposal"]["target_records"][0]["invoice_id"] == 1
    assert action["proposal"]["source_tool_call_id"] != action["proposal"]["requested_source_tool_call_id"]
    db = TestingSession()
    original = db.get(AgentToolCall, uuid.UUID(source_call_id))
    refreshed = db.get(
        AgentToolCall, uuid.UUID(action["proposal"]["source_tool_call_id"])
    )
    assert original is not None and refreshed is not None
    assert refreshed.status == "completed"
    assert str(original.id) == action["proposal"]["requested_source_tool_call_id"]
    assert str(refreshed.id) == action["proposal"]["source_tool_call_id"]
    snapshot = {
        "as_of": action["proposal"]["source_as_of"],
        "target_records": [
            {
                "invoice_id": row["invoice_id"],
                "customer_id": row["customer_id"],
                "currency_id": row["currency_id"],
                "remaining_amount": row["remaining_amount"],
            }
            for row in action["proposal"]["target_records"]
        ],
        "totals_by_currency": action["proposal"]["totals_by_currency"],
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert snapshot_hash == action["proposal"]["source_snapshot_hash"]
    assert json.loads(refreshed.safe_result_summary_json)["source_snapshot_hash"] == snapshot_hash
    db.close()
    assert "tenant_id" not in prepare.request.content.decode()
    invalid = employee.post(
        f"{request_path}/agent/actions/prepare",
        json={
            "source_tool_call_id": source_call_id,
            "tenant_id": str(seed["tenant_b"]),
            "invoice_ids": [999],
        },
        headers=_csrf(employee),
    )
    assert invalid.status_code == 422

    updated = employee.patch(
        f"{request_path}/agent/actions/{action['id']}",
        json={
            "expected_action_version": action["version"],
            "expected_proposal_hash": action["proposal_hash"],
            "draft_message": "Edited safe draft",
            "internal_note": "Review before sending",
            "followup_type": "phone",
        },
        headers=_csrf(employee),
    )
    assert updated.status_code == 200, updated.text
    updated_action = updated.json()["action"]
    assert updated_action["proposal"]["draft_message"] == "Edited safe draft"
    assert updated_action["proposal_hash"] != action["proposal_hash"]
    submitted = employee.post(
        f"{request_path}/agent/actions/{action['id']}/submit",
        json={
            "expected_action_version": updated_action["version"],
            "expected_proposal_hash": updated_action["proposal_hash"],
        },
        headers=_csrf(employee),
    )
    assert submitted.status_code == 200, submitted.text
    awaiting = submitted.json()["action"]
    db = TestingSession()
    other = User(
        email="workbench-other@example.com",
        full_name="Other Employee",
        password_hash=hash_password(PASSWORD),
    )
    db.add(other)
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_a"], user_id=other.id, role="member"))
    db.commit()
    db.close()
    other_caps = _action_out(
        db.query(OperationTask).one(),
        db.query(OperationAction).one(),
        other,
        "member",
    )
    assert not any(
        other_caps[key] for key in ("can_edit", "can_submit", "can_approve", "can_reject")
    )
    db.close()

    db = TestingSession()
    manager = User(
        email="workbench-manager@example.com",
        full_name="Workbench Manager",
        password_hash=hash_password(PASSWORD),
    )
    db.add(manager)
    db.flush()
    db.add(TenantMembership(tenant_id=seed["tenant_a"], user_id=manager.id, role="manager"))
    db.commit()
    db.close()
    manager_client = _client("workbench-manager@example.com")
    own_rejection = employee.post(
        f"{request_path}/agent/actions/{action['id']}/reject",
        json={
            "expected_action_version": awaiting["version"],
            "expected_proposal_hash": awaiting["proposal_hash"],
            "rejection_reason": "self rejection must be blocked",
        },
        headers=_csrf(employee),
    )
    assert own_rejection.status_code == 403
    own_approval = employee.post(
        f"{request_path}/agent/actions/{action['id']}/approve",
        json={
            "expected_action_version": awaiting["version"],
            "expected_proposal_hash": awaiting["proposal_hash"],
        },
        headers=_csrf(employee),
    )
    assert own_approval.status_code == 403
    approved = manager_client.post(
        f"{request_path}/agent/actions/{action['id']}/approve",
        json={
            "expected_action_version": awaiting["version"],
            "expected_proposal_hash": awaiting["proposal_hash"],
        },
        headers=_csrf(manager_client),
    )
    assert approved.status_code == 200, approved.text
    approved_action = approved.json()["action"]
    assert approved_action["status"] == "approved"
    assert approved_action["approved_hash"] == approved_action["proposal_hash"]
    assert approved_action["not_executed"] is True
    assert approved_action["can_edit"] is False
    assert approved_action["can_submit"] is False
    assert approved_action["can_approve"] is False
    assert approved_action["can_reject"] is False
    blocked_edit = employee.patch(
        f"{request_path}/agent/actions/{action['id']}",
        json={
            "expected_action_version": approved_action["version"],
            "expected_proposal_hash": approved_action["proposal_hash"],
            "draft_message": "Must not change",
        },
        headers=_csrf(employee),
    )
    assert blocked_edit.status_code == 409

    generic_body = {
        "expected_version": 1,
        "expected_action_version": approved_action["version"],
        "expected_proposal_hash": approved_action["proposal_hash"],
    }
    for endpoint in ("submit", "approve", "retry"):
        response = manager_client.post(
            f"/api/v1/operations/tasks/{approved_action['task_id']}/action/{endpoint}",
            json=generic_body,
            headers=_csrf(manager_client),
        )
        assert response.status_code == 409
    db = TestingSession()
    stored = db.query(OperationAction).one()
    stored.status = "queued"
    db.commit()
    db.close()
    with patch("app.workers.operations.create_invoice_activity") as writer:
        from app.workers.operations import run_queued_actions_once
        with patch("app.workers.operations.get_session_factory", lambda: TestingSession):
            assert run_queued_actions_once() == 0
        writer.assert_not_called()
    db = TestingSession()
    stored = db.query(OperationAction).one()
    assert stored.status == "queued"
    stored.workflow_key = None
    task = db.query(OperationTask).one()
    task.source_type = "agent_workbench"
    db.commit()
    db.close()
    with patch("app.workers.operations.create_invoice_activity") as writer:
        with patch("app.workers.operations.get_session_factory", lambda: TestingSession):
            assert run_queued_actions_once() == 0
        writer.assert_not_called()
    db = TestingSession()
    assert db.query(OperationAction).one().status == "queued"
    db.close()
    db = TestingSession()
    stored = db.query(OperationAction).one()
    stored.workflow_key = "finance.prepare_collection_followup"
    stored.status = "approved"
    db.commit()
    db.close()

    customer = _client("workbench-customer@example.com")
    assert customer.get(f"{request_path}/agent/actions").status_code == 404
    db = TestingSession()
    stored = db.query(OperationAction).one()
    assert stored.status == "approved"
    assert stored.approved_hash == stored.proposal_hash
    original_json, original_hash = stored.proposal_json, stored.proposal_hash
    stored.proposal_json = "{}"
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()
    stored = db.query(OperationAction).one()
    stored.proposal_hash = "0" * 64
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()
    stored = db.query(OperationAction).one()
    assert (stored.proposal_json, stored.proposal_hash) == (original_json, original_hash)
    assert {row.event for row in db.query(OperationActionHistory).all()} >= {
        "generated",
        "regenerated",
        "submitted",
        "approved",
    }
    assert {
        row.action
        for row in db.query(AuditLog).all()
    } >= {
        "agent_action_prepared",
        "agent_action_updated",
        "agent_action_submitted_for_approval",
        "agent_action_approved",
    }
    db.close()


def test_finance_tool_enforces_module_and_service_scopes(seed, monkeypatch):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    monkeypatch.setattr(
        workbench_api,
        "_operations_read_page",
        _single_page([]),
    )
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/tools/execute"
    db = TestingSession()
    membership = (
        db.query(TenantMembership)
        .filter_by(tenant_id=seed["tenant_a"], user_id=data["employee"])
        .one()
    )
    membership.odoo_module_scope_json = '["hr"]'
    db.commit()
    db.close()
    assert client.post(path, json={}, headers=_csrf(client)).status_code == 403

    db = TestingSession()
    membership = (
        db.query(TenantMembership)
        .filter_by(tenant_id=seed["tenant_a"], user_id=data["employee"])
        .one()
    )
    membership.odoo_module_scope_json = '["account"]'
    membership.service_scope_json = '["administrative"]'
    db.commit()
    db.close()
    assert client.post(path, json={}, headers=_csrf(client)).status_code == 403


def test_finance_tool_permission_rejects_non_worker_role(seed):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    db = TestingSession()
    membership = (
        db.query(TenantMembership)
        .filter_by(tenant_id=seed["tenant_a"], user_id=data["employee"])
        .one()
    )
    membership.role = "viewer"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        execute_overdue_customer_invoices(
            db=db,
            actor=db.get(User, data["employee"]),
            request=db.get(ServiceRequest, data["request"]),
            connection=db.query(Connection).filter_by(tenant_id=seed["tenant_a"]).first(),
            tool_input=OverdueInvoicesInput(),
            read_page=_single_page([]),
        )
    db.close()
    assert exc.value.status_code == 403
    assert exc.value.detail == "Finance tool permission denied"


def test_finance_tool_failure_is_safe_and_internal(seed, monkeypatch):
    data = _fixture(seed)
    _enable_finance_connection(seed)

    def fail(*_args, **_kwargs):
        raise RuntimeError("credential-secret-must-not-leak")

    monkeypatch.setattr(workbench_api, "_operations_read_page", fail)
    employee = _client("workbench-employee@example.com")
    response = employee.post(
        f"/api/v1/service-requests/{data['request']}/agent/tools/execute",
        json={},
        headers=_csrf(employee),
    )
    assert response.status_code == 502
    assert "credential-secret" not in response.text

    db = TestingSession()
    call = db.query(AgentToolCall).one()
    assert call.status == "failed"
    assert call.error_code == "tool_execution_failed"
    assert call.safe_result_summary_json is None
    assert any(
        row.action == "agent_tool_failed"
        and "credential-secret" not in str(row.metadata_json)
        for row in db.query(AuditLog).all()
    )
    db.close()

    customer = _client("workbench-customer@example.com")
    detail = customer.get(f"/api/v1/service-requests/{data['request']}")
    assert detail.status_code == 200
    assert "tool_calls" not in detail.json()
    assert all("finance.get_" not in message["body"] for message in detail.json()["messages"])


def test_phase3b_registry_routing_and_approved_date_phrases_are_deterministic():
    assert set(FINANCE_TOOLS) == {
        "finance.get_overdue_customer_invoices",
        CUSTOMER_INVOICES_TOOL_KEY,
        RECEIVABLES_TOOL_KEY,
        VENDOR_BILLS_TOOL_KEY,
        RECENT_PAYMENTS_TOOL_KEY,
    }
    assert all(tool.mode == "read" for tool in FINANCE_TOOLS.values())
    assert select_finance_tool("اعرض فواتير العميل شركة النور") == CUSTOMER_INVOICES_TOOL_KEY
    assert select_finance_tool("ملخص الذمم المستحقة على العملاء") == RECEIVABLES_TOOL_KEY
    assert select_finance_tool("unpaid vendor bills") == VENDOR_BILLS_TOOL_KEY
    assert select_finance_tool("incoming payments last 30 days") == RECENT_PAYMENTS_TOOL_KEY
    current = date(2026, 9, 21)
    parsed = finance_tool_input_from_instruction(
        "فواتير العميل شركة النور غير المسدد هذا الشهر",
        CUSTOMER_INVOICES_TOOL_KEY,
        today=current,
    )
    assert parsed.customer == "شركة النور"
    assert parsed.payment_status == "not_paid"
    assert parsed.date_from == date(2026, 9, 1)
    assert parsed.date_to == current
    assert InvoiceLookupInput.model_validate(
        {"date_from": "2026-09-01", "date_to": "2026-09-21"}
    ).date_from == date(2026, 9, 1)
    with pytest.raises(HTTPException) as exc:
        finance_tool_input_from_instruction(
            "show payments yesterday",
            RECENT_PAYMENTS_TOOL_KEY,
            today=current,
        )
    assert exc.value.status_code == 422


def test_customer_invoice_tool_resolves_server_side_partner_and_rejects_ambiguity(seed):
    data = _fixture(seed)
    db = TestingSession()
    actor = db.get(User, data["employee"])
    request = db.get(ServiceRequest, data["request"])
    connection = db.query(Connection).filter_by(tenant_id=seed["tenant_a"]).first()
    as_of = date(2026, 9, 21)
    calls = []

    def read_page(_connection, *, resource, filters, limit, offset, **_kwargs):
        calls.append((resource, filters))
        records = (
            [{"id": 81, "name": "شركة النور"}]
            if resource == "finance_customers"
            else [_invoice(7, due_date=as_of, residual=250, customer_id=81)]
        )
        return {
            "records": records[offset : offset + limit],
            "offset": offset,
            "returned_count": len(records[offset : offset + limit]),
            "has_more": False,
            "next_offset": None,
        }

    result = execute_finance_tool(
        db=db,
        actor=actor,
        request=request,
        connection=connection,
        tool_key=CUSTOMER_INVOICES_TOOL_KEY,
        tool_input=InvoiceLookupInput(customer="النور", payment_status="not_paid"),
        read_page=read_page,
        today=as_of,
    )
    assert result.returned_count == 1
    assert result.invoices[0]["party_id"] == 81
    invoice_filters = calls[-1][1]
    assert {"field": "partner_id", "operator": "=", "value": 81} in invoice_filters
    assert result.totals_by_currency[0]["outstanding_amount"] == "250.00"
    assert calls[0][0] == "finance_customers"

    def ambiguous(_connection, *, resource, **_kwargs):
        assert resource == "finance_customers"
        return {
            "records": [{"id": 1, "name": "Al Noor"}, {"id": 2, "name": "Al Noor Trading"}],
            "offset": 0,
            "returned_count": 2,
            "has_more": False,
            "next_offset": None,
        }

    with pytest.raises(HTTPException) as exc:
        execute_finance_tool(
            db=db,
            actor=actor,
            request=request,
            connection=connection,
            tool_key=CUSTOMER_INVOICES_TOOL_KEY,
            tool_input=InvoiceLookupInput(customer="Al Noor"),
            read_page=ambiguous,
            today=as_of,
        )
    db.close()
    assert exc.value.status_code == 409


def test_receivables_summary_uses_decimal_currency_aging_and_omits_truncated_totals(seed):
    data = _fixture(seed)
    db = TestingSession()
    as_of = date(2026, 9, 21)
    records = [
        _invoice(1, due_date=as_of - timedelta(days=5), residual=100.10),
        _invoice(2, due_date=as_of - timedelta(days=45), residual=200.20),
        _invoice(3, due_date=as_of + timedelta(days=5), residual=50.30),
        _invoice(4, due_date=as_of - timedelta(days=95), residual=9.40, currency_id=2, currency="USD"),
    ]
    common = {
        "db": db,
        "actor": db.get(User, data["employee"]),
        "request": db.get(ServiceRequest, data["request"]),
        "connection": db.query(Connection).filter_by(tenant_id=seed["tenant_a"]).first(),
        "tool_key": RECEIVABLES_TOOL_KEY,
        "today": as_of,
    }
    result = execute_finance_tool(
        **common,
        tool_input=ReceivablesInput(max_records=200),
        read_page=_single_page(records),
    )
    totals = {item["currency"]: item for item in result.totals_by_currency}
    assert totals["SAR"]["open_receivables_total"] == "350.60"
    assert totals["SAR"]["overdue_receivables_total"] == "300.30"
    assert totals["SAR"]["aging"]["days_0_30"] == "100.10"
    assert totals["SAR"]["aging"]["days_31_60"] == "200.20"
    assert totals["USD"]["aging"]["over_90_days"] == "9.40"

    many = [_invoice(index, due_date=as_of - timedelta(days=40), residual=1) for index in range(1, 102)]
    truncated = execute_finance_tool(
        **common,
        tool_input=ReceivablesInput(max_records=100),
        read_page=_single_page(many),
    )
    db.close()
    assert truncated.result_truncated is True
    assert truncated.totals_by_currency == []


def test_vendor_bill_and_payment_tools_use_only_bounded_approved_filters(seed):
    data = _fixture(seed)
    db = TestingSession()
    as_of = date(2026, 9, 21)
    common = {
        "db": db,
        "actor": db.get(User, data["employee"]),
        "request": db.get(ServiceRequest, data["request"]),
        "connection": db.query(Connection).filter_by(tenant_id=seed["tenant_a"]).first(),
        "read_page": None,
        "today": as_of,
    }
    bill = _invoice(1, due_date=as_of - timedelta(days=10), residual=75)
    bill["move_type"] = "in_invoice"
    bill["partner_id"] = [90, "Vendor 90"]
    observed = {}

    def bill_page(connection, **kwargs):
        observed["bill"] = kwargs
        return _single_page([bill])(connection, **kwargs)

    common["read_page"] = bill_page
    bills = execute_finance_tool(
        **common,
        tool_key=VENDOR_BILLS_TOOL_KEY,
        tool_input=VendorBillsInput(
            state="posted",
            payment_status="not_paid",
            due_status="overdue",
        ),
    )
    assert bills.bills[0]["party"] == "Vendor 90"
    assert {item["field"] for item in observed["bill"]["filters"]} == {
        "state",
        "payment_state",
        "invoice_date_due",
    }
    payment = {
        "id": 10,
        "name": "PAY/0010",
        "date": as_of.isoformat(),
        "amount": 88.25,
        "payment_type": "inbound",
        "partner_type": "customer",
        "partner_id": [10, "Customer 10"],
        "currency_id": [1, "SAR"],
        "company_id": [1, "Main Company"],
        "state": "posted",
    }

    def payment_page(connection, **kwargs):
        observed["payment"] = kwargs
        return _single_page([payment])(connection, **kwargs)

    common["read_page"] = payment_page
    payments = execute_finance_tool(
        **common,
        tool_key=RECENT_PAYMENTS_TOOL_KEY,
        tool_input=RecentPaymentsInput(
            date_from=as_of - timedelta(days=29),
            date_to=as_of,
            direction="incoming",
        ),
    )
    db.close()
    assert payments.payments[0]["amount"] == "88.25"
    assert {"field": "payment_type", "operator": "=", "value": "inbound"} in observed["payment"]["filters"]
    assert payments.totals_by_currency[0]["total_amount"] == "88.25"


def test_new_tool_rows_are_transient_and_unknown_input_is_rejected(seed, monkeypatch):
    data = _fixture(seed)
    _enable_finance_connection(seed)
    as_of = datetime.now(UTC).date()
    bill = _invoice(1, due_date=as_of - timedelta(days=10), residual=75)
    bill["move_type"] = "in_invoice"
    bill["partner_id"] = [90, "Sensitive Vendor Name"]
    monkeypatch.setattr(workbench_api, "_operations_read_page", _single_page([bill]))
    client = _client("workbench-employee@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/tools/execute"
    response = client.post(
        path,
        json={
            "tool_key": VENDOR_BILLS_TOOL_KEY,
            "input": {"state": "posted", "max_records": 100},
            "locale": "en",
        },
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["tool_calls"][0]["result"]["bills"][0]["party"] == "Sensitive Vendor Name"
    persisted = client.get(
        f"/api/v1/service-requests/{data['request']}/agent/session"
    ).json()["tool_calls"][0]["result"]
    assert "bills" not in persisted
    assert "Sensitive Vendor Name" not in str(persisted)
    injected = client.post(
        path,
        json={
            "tool_key": VENDOR_BILLS_TOOL_KEY,
            "input": {"domain": [["id", ">", 0]], "max_records": 100},
        },
        headers=_csrf(client),
    )
    assert injected.status_code == 422