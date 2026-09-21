"""Request-bound AI Workbench authorization and persistence tests."""

from fastapi.testclient import TestClient

from app.api import workbench as workbench_api
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

    db = TestingSession()
    assert db.query(AgentSession).count() == 1
    assert db.query(AgentMessage).count() == 1
    assert {row.action for row in db.query(AuditLog).all()} >= {
        "agent_session_created",
        "agent_analysis_started",
        "agent_analysis_completed",
    }
    db.close()


def test_cross_tenant_employee_cannot_access_request_workbench(seed):
    data = _fixture(seed)
    client = _client("b@example.com")
    path = f"/api/v1/service-requests/{data['request']}/agent/session"
    assert client.get(path).status_code == 404
    assert client.post(path, json={}, headers=_csrf(client)).status_code == 404


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
    db.close()