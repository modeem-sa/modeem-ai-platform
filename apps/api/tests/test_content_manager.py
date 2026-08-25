"""Focused contract tests for the internal Content Manager endpoint."""

from collections.abc import Mapping

from fastapi.testclient import TestClient

from app.api.content_manager import get_content_manager_provider
from app.main import app
from app.models import AuditLog
from tests.test_auth_security import PASSWORD, TestingSession


class FakeProvider:
    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result

    def generate(self, **_kwargs: object) -> Mapping[str, object]:
        return self.result


def _client() -> TestClient:
    return TestClient(app)


def _headers(client: TestClient, tenant_id: object) -> dict[str, str]:
    return {
        "X-CSRF-Token": client.cookies.get("modeem_csrf", ""),
        "X-Internal-Token": "internal-test-secret",
        "X-Tenant-ID": str(tenant_id),
    }


def _login(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": PASSWORD},
    )


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "original_request": "اكتب إيميل شكر للموظفين",
        "provided_fields": {},
        "conversation_messages": [],
    }
    body.update(changes)
    return body


def test_requires_session_internal_auth_and_csrf(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    assert client.post("/api/v1/agents/content-manager/documents", json=_body()).status_code == 401

    _login(client)
    no_internal = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers={"X-Tenant-ID": str(seed["tenant_a"]), "X-CSRF-Token": client.cookies["modeem_csrf"]},
    )
    assert no_internal.status_code == 401

    no_csrf = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers={
            "X-Tenant-ID": str(seed["tenant_a"]),
            "X-Internal-Token": "internal-test-secret",
        },
    )
    assert no_csrf.status_code == 403


def test_tenant_isolation_and_client_tenant_rejection(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)
    mismatch = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_b"]),
    )
    assert mismatch.status_code == 403
    injected = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(tenant_id=str(seed["tenant_b"])),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert injected.status_code == 422


def test_complete_needs_information_and_out_of_scope(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)
    app.dependency_overrides[get_content_manager_provider] = lambda: FakeProvider(
        {
            "status": "complete",
            "document": "العنوان: شكر\nالنص: شكرًا لكم.",
            "document_type": "email",
            "document_action": "create_new_document",
            "ui": None,
        }
    )
    complete = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert complete.json()["status"] == "complete"

    app.dependency_overrides[get_content_manager_provider] = lambda: FakeProvider(
        {
            "status": "needs_information",
            "document": None,
            "document_type": "email",
            "document_action": "create_new_document",
            "ui": {
                "fields": [
                    {
                        "id": "email_purpose",
                        "label": "الغرض",
                        "type": "textarea",
                    }
                ]
            },
        }
    )
    missing = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert missing.json()["status"] == "needs_information"
    assert missing.json()["ui"]["fields"][0]["required"] is True
    outside = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(original_request="ارسم لي صورة"),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert outside.json()["status"] == "out_of_scope"
    app.dependency_overrides.pop(get_content_manager_provider, None)


def test_audit_redacts_content_and_provider_errors_are_safe(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)
    secret_text = "not-for-audit"
    app.dependency_overrides[get_content_manager_provider] = lambda: FakeProvider(
        {"status": "complete", "document": secret_text, "document_type": "email", "ui": None}
    )
    response = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(original_request=secret_text),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert response.status_code == 200
    db = TestingSession()
    audit = db.query(AuditLog).filter(AuditLog.action == "content_manager.document_created").one()
    assert secret_text not in str(audit.metadata_json)
    db.close()

    app.dependency_overrides[get_content_manager_provider] = lambda: FakeProvider({"bad": "output"})
    failed = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert failed.status_code == 502
    app.dependency_overrides.pop(get_content_manager_provider, None)


def test_missing_provider_returns_safe_503(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client()
    _login(client)
    response = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert response.status_code == 503


def test_oversized_provider_option_is_rejected_safely(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)
    app.dependency_overrides[get_content_manager_provider] = lambda: FakeProvider(
        {
            "status": "needs_information",
            "document": None,
            "document_type": "report",
            "document_action": "create_new_document",
            "ui": {
                "title": "بيانات التقرير",
                "description": "",
                "submit_label": "متابعة",
                "fields": [
                    {
                        "id": "report_type",
                        "label": "النوع",
                        "type": "select",
                        "required": True,
                        "options": ["x" * 201],
                    }
                ],
                "suggestions": [],
            },
        }
    )
    response = client.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(),
        headers=_headers(client, seed["tenant_a"]),
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "Content Manager provider failed"}
    app.dependency_overrides.pop(get_content_manager_provider, None)