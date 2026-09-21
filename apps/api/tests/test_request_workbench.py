"""Request-bound AI Workbench authorization and persistence tests."""

from fastapi.testclient import TestClient

from app.api import workbench as workbench_api
from app.content_manager.provider import ProviderUnavailableError
from app.core.security import hash_password
from app.main import app
from app.models import (
    AgentMessage,
    AgentSession,
    AuditLog,
    Connection,
    ServiceRequest,
    TenantMembership,
    User,
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