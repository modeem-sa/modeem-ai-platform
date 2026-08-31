"""Focused contract tests for the internal Content Manager endpoint."""

import os
from collections.abc import Mapping
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.content_manager import ContentManagerResponse, get_content_manager_provider
from app.content_manager.export import prepare_pdf_line, safe_export_filename
from app.content_manager.provider import (
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.content_manager.repository import PromptRepository
from app.content_manager.workflow import ContentManagerWorkflow, ModelResult
from app.main import app
from app.models import AuditLog, ContentDocument, ContentDocumentRevision
from tests.fixtures.content_manager_provider_contracts import (
    OUT_OF_SCOPE,
    PROVIDER_CONTRACT_SAMPLES,
    RESPONSE_CONTRACT_SAMPLES,
)
from tests.test_auth_security import PASSWORD, TestingSession


class FakeProvider:
    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.last_user_payload: Mapping[str, object] | None = None

    def generate(self, **kwargs: object) -> Mapping[str, object]:
        payload = kwargs.get("user_payload")
        if isinstance(payload, Mapping):
            self.last_user_payload = payload
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


@pytest.mark.parametrize(
    ("expected_status", "sample"),
    RESPONSE_CONTRACT_SAMPLES.items(),
    ids=RESPONSE_CONTRACT_SAMPLES,
)
def test_response_contract_samples_cover_every_public_state(expected_status, sample):
    response = ContentManagerResponse.model_validate(sample)
    assert response.status == expected_status


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
        {
            "status": "complete",
            "document": secret_text,
            "document_type": secret_text,
            "ui": None,
        }
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

def test_export_requires_authenticated_tenant_and_csrf(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    body = {"document": "Reviewed document", "document_type": "official-letter"}
    client = _client()

    anonymous = client.post(
        "/api/v1/agents/content-manager/documents/export/pdf",
        json=body,
    )
    assert anonymous.status_code == 401

    _login(client)
    no_csrf = client.post(
        "/api/v1/agents/content-manager/documents/export/pdf",
        json=body,
        headers={
            "X-Tenant-ID": str(seed["tenant_a"]),
            "X-Internal-Token": "internal-test-secret",
        },
    )
    assert no_csrf.status_code == 403

    mismatched_tenant = client.post(
        "/api/v1/agents/content-manager/documents/export/pdf",
        json=body,
        headers=_headers(client, seed["tenant_b"]),
    )
    assert mismatched_tenant.status_code == 403
def test_documents_persist_revisions_and_remain_tenant_isolated(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    provider = FakeProvider(
        {
            "status": "complete",
            "document": "المسودة الأولى",
            "document_type": "memo",
            "document_action": "create_new_document",
            "ui": None,
        }
    )
    app.dependency_overrides[get_content_manager_provider] = lambda: provider
    client_a = _client()
    _login(client_a)

    created = client_a.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(
            original_request="اكتب تعميماً داخلياً",
            conversation_messages=[
                {"role": "user", "content": "اكتب تعميماً داخلياً"}
            ],
        ),
        headers=_headers(client_a, seed["tenant_a"]),
    )
    assert created.status_code == 200
    document_id = created.json()["document_id"]

    db = TestingSession()
    document = db.query(ContentDocument).one()
    revision = db.query(ContentDocumentRevision).one()
    assert str(document.id) == document_id
    assert document.tenant_id == seed["tenant_a"]
    assert document.created_by_user_id == seed["user_a"]
    assert document.current_document == "المسودة الأولى"
    assert revision.tenant_id == seed["tenant_a"]
    assert revision.created_by_user_id == seed["user_a"]
    assert revision.revision_number == 1
    db.close()

    listed = client_a.get(
        "/api/v1/agents/content-manager/documents",
        headers=_headers(client_a, seed["tenant_a"]),
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["revision_count"] == 1

    detail = client_a.get(
        f"/api/v1/agents/content-manager/documents/{document_id}",
        headers=_headers(client_a, seed["tenant_a"]),
    )
    assert detail.status_code == 200
    assert detail.json()["current_document"] == "المسودة الأولى"
    assert detail.json()["conversation_messages"][0]["content"] == "اكتب تعميماً داخلياً"

    provider.result = {
        "status": "complete",
        "document": "المسودة المنقحة",
        "document_type": "memo",
        "document_action": "revise_active_document",
        "ui": None,
    }
    revised = client_a.post(
        "/api/v1/agents/content-manager/documents",
        json=_body(
            document_id=document_id,
            original_request="اكتب تعميماً داخلياً",
            current_document="المسودة الأولى",
            active_document_type="memo",
            latest_correction="اجعلها أكثر اختصاراً",
            conversation_messages=[
                {"role": "user", "content": "اجعلها أكثر اختصاراً"}
            ],
        ),
        headers=_headers(client_a, seed["tenant_a"]),
    )
    assert revised.status_code == 200, revised.json()
    assert revised.json()["document_id"] == document_id
    assert provider.last_user_payload is not None
    assert "document_id" not in provider.last_user_payload

    revised_detail = client_a.get(
        f"/api/v1/agents/content-manager/documents/{document_id}",
        headers=_headers(client_a, seed["tenant_a"]),
    ).json()
    assert revised_detail["current_document"] == "المسودة المنقحة"
    assert [item["revision_number"] for item in revised_detail["revisions"]] == [1, 2]
    assert revised_detail["revisions"][0]["document"] == "المسودة الأولى"

    db = TestingSession()
    audits = (
        db.query(AuditLog)
        .filter(AuditLog.resource_id == document_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    assert [entry.action for entry in audits] == [
        "content_manager.document_created",
        "content_manager.document_updated",
    ]
    audit_dump = str([entry.metadata_json for entry in audits])
    assert "المسودة الأولى" not in audit_dump
    assert "المسودة المنقحة" not in audit_dump
    assert "اجعلها أكثر اختصاراً" not in audit_dump
    db.close()

    client_b = _client()
    client_b.post(
        "/api/v1/auth/login",
        json={"email": "b@example.com", "password": PASSWORD},
    )
    tenant_b_headers = _headers(client_b, seed["tenant_b"])
    other_list = client_b.get(
        "/api/v1/agents/content-manager/documents",
        headers=tenant_b_headers,
    )
    assert other_list.status_code == 200
    assert other_list.json() == {"items": [], "total": 0}
    assert (
        client_b.get(
            f"/api/v1/agents/content-manager/documents/{document_id}",
            headers=tenant_b_headers,
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            "/api/v1/agents/content-manager/documents",
            json=_body(document_id=document_id),
            headers=tenant_b_headers,
        ).status_code
        == 404
    )
    app.dependency_overrides.pop(get_content_manager_provider, None)

def test_arabic_docx_export_has_rtl_and_no_identity_metadata(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)
    tenant_marker = str(seed["tenant_a"])
    response = client.post(
        "/api/v1/agents/content-manager/documents/export/docx",
        json={
            "document": "خطاب رسمي\nمرحبًا بكم في منصة موديم.",
            "document_type": "official-letter",
        },
        headers=_headers(client, seed["tenant_a"]),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.docx"')
    with ZipFile(BytesIO(response.content)) as archive:
        document_xml = archive.read("word/document.xml").decode()
        core_xml = archive.read("docProps/core.xml").decode()
    assert "خطاب رسمي" in document_xml
    assert "<w:bidi" in document_xml
    assert '<w:rtl w:val="1"' in document_xml
    assert tenant_marker not in core_xml
    assert "a@example.com" not in core_xml


@pytest.mark.parametrize(
    "broken_response",
    [
        {"status": "out_of_scope", "redirect_message": "not a provider result"},
        {"status": "complete"},
        {"status": "needs_information", "ui": {"fields": []}},
        {"status": "complete", "document": "ok", "unexpected": True},
        {
            "status": "needs_information",
            "ui": {
                "fields": [
                    {
                        "id": "details",
                        "label": "تفاصيل",
                        "type": "textarea",
                        "options": ["x" * 201],
                    }
                ]
            },
        },
    ],
    ids=["provider-status", "missing-document", "missing-fields", "extra-key", "oversized-option"],
)
def test_provider_contract_breaks_fail_as_a_safe_provider_error(broken_response):
    class BrokenProvider:
        def generate(self, **_kwargs: object) -> Mapping[str, object]:
            return broken_response

    with pytest.raises(ProviderFailureError):
        ContentManagerWorkflow(BrokenProvider()).execute(_body())


def test_live_provider_contract_is_opt_in_and_redacted():
    """Exercise the configured provider only when explicitly requested.

    The assertion inspects only the status and never logs the response,
    document text, API key, or response headers.
    """
    if os.getenv("MODEEM_RUN_LIVE_PROVIDER_CONTRACT") != "1":
        pytest.skip("set MODEEM_RUN_LIVE_PROVIDER_CONTRACT=1 to run the live check")

    try:
        provider = OpenAICompatibleProvider.from_environment()
        result = provider.generate(
            system_prompt=PromptRepository().system_prompt(),
            user_payload={
                "original_request": "اكتب رسالة داخلية قصيرة عن اجتماع الأسبوع القادم",
                "provided_fields": {},
                "conversation_messages": [],
            },
        )
        validated = ModelResult.model_validate(result)
    except (ProviderFailureError, ProviderUnavailableError, ValidationError):
        pytest.fail("live provider response violated the Content Manager contract", pytrace=False)
    assert validated.status in {"complete", "needs_information"}

def test_live_provider_contract_is_scheduled_with_repository_secrets():
    workflow_path = (
        Path(__file__).resolve().parents[4]
        / ".github"
        / "workflows"
        / "content-manager-provider-contract.yml"
    )
    automation = workflow_path.read_text(encoding="utf-8")

    assert "schedule:" in automation
    assert "workflow_dispatch:" in automation
    assert 'MODEEM_RUN_LIVE_PROVIDER_CONTRACT: "1"' in automation
    assert "secrets.AI_INTEGRATIONS_OPENAI_API_KEY" in automation
    assert "secrets.OPENAI_API_KEY" in automation
    assert "-k live_provider_contract" in automation
    assert "continue-on-error: true" not in automation


def test_out_of_scope_contract_is_produced_without_calling_provider():
    class UnexpectedProvider:
        def generate(self, **_kwargs: object) -> Mapping[str, object]:
            raise AssertionError("out-of-scope requests must not call the provider")

    result = ContentManagerWorkflow(UnexpectedProvider()).execute(
        _body(original_request="ارسم صورة لشعار")
    )
    assert result["status"] == OUT_OF_SCOPE["status"]
    assert "redirect_message" in result


@pytest.mark.parametrize("sample", PROVIDER_CONTRACT_SAMPLES.values(), ids=PROVIDER_CONTRACT_SAMPLES)
def test_provider_contract_samples_accept_optional_fields_omitted(sample):
    """The managed provider may omit display-only fields without breaking users."""
    result = ModelResult.model_validate(sample)
    assert result.status in {"complete", "needs_information"}

def test_english_docx_and_arabic_pdf_formatting(seed, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "internal-test-secret")
    client = _client()
    _login(client)

    english = client.post(
        "/api/v1/agents/content-manager/documents/export/docx",
        json={"document": "Quarterly report\nRevenue increased.", "document_type": "report"},
        headers=_headers(client, seed["tenant_a"]),
    )
    assert english.status_code == 200
    with ZipFile(BytesIO(english.content)) as archive:
        document_xml = archive.read("word/document.xml").decode()
    assert "Quarterly report" in document_xml
    assert '<w:jc w:val="left"' in document_xml
    assert "<w:bidi" not in document_xml

    arabic_pdf = client.post(
        "/api/v1/agents/content-manager/documents/export/pdf",
        json={"document": "تقرير عربي\nنتائج الربع الأول", "document_type": "report"},
        headers=_headers(client, seed["tenant_a"]),
    )
    assert arabic_pdf.status_code == 200
    assert arabic_pdf.content.startswith(b"%PDF-")
    assert arabic_pdf.headers["content-type"].startswith("application/pdf")
    assert arabic_pdf.headers["cache-control"] == "no-store"

    visual_arabic, is_rtl = prepare_pdf_line("مرحبًا بكم")
    assert is_rtl is True
    assert visual_arabic != "مرحبًا بكم"
    visual_english, is_rtl = prepare_pdf_line("Quarterly report")
    assert is_rtl is False
    assert visual_english == "Quarterly report"

def test_export_filename_is_safe_and_document_type_appropriate():
    filename = safe_export_filename(
        "../../Official Letter / Q1",
        "pdf",
        export_date=date(2026, 8, 25),
    )
    assert filename == "modeem-official-letter-q1-2026-08-25.pdf"
    assert "/" not in filename
    assert "\\" not in filename

    fallback = safe_export_filename("خطاب رسمي", "docx", export_date=date(2026, 8, 25))
    assert fallback == "modeem-document-2026-08-25.docx"
