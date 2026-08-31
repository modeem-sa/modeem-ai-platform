"""AI assistant and automatic overdue-invoice workflow tests."""

import json
from collections.abc import Mapping

import pytest

from app.content_manager.provider import ProviderFailureError
from app.models import OperationAction, OperationActionHistory, OperationTask
from app.operations.assistant import FinanceAssistantService, sanitized_records
from app.workers import operations as operations_worker
from tests.test_auth_security import TestingSession


class FakeProvider:
    model = "test-model"

    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(kwargs)
        return self.result


def _assistant_result() -> dict[str, object]:
    return {
        "headline": "ملخص العمليات المالية",
        "summary": "توجد سجلات تحتاج متابعة، ولم يتم تنفيذ أي إجراء خارجي.",
        "findings": [
            {
                "title": "سجل يحتاج مراجعة",
                "evidence": "الحالة المعروضة غير مكتملة.",
                "severity": "attention",
            }
        ],
        "automation_opportunities": [
            {
                "workflow_key": "monitor_records",
                "title": "المراقبة التلقائية",
                "mode": "automatic",
                "reason": "يمكن متابعة تغير الحالة دون كتابة في Odoo.",
            },
            {
                "workflow_key": "prepare_invoice_activity",
                "title": "تجهيز نشاط متابعة",
                "mode": "approval_required",
                "reason": "تغيير Odoo يحتاج اعتماد المدير.",
            },
        ],
        "next_step": "راجع السجل ثم اعتمد الإجراء المناسب.",
        "confidence": 0.88,
    }


def _activity_result() -> dict[str, object]:
    return {
        "title": "متابعة الفاتورة المتأخرة",
        "summary": "تجهيز نشاط متابعة للفاتورة.",
        "note": "راجع حالة التحصيل وفق الإجراءات المعتمدة.",
        "deadline_offset_days": 3,
        "priority": "high",
        "priority_reason": "الفاتورة متأخرة وتحتاج متابعة.",
        "confidence": 0.91,
    }


def test_assistant_sanitizes_secret_like_fields_and_returns_structured_modes():
    provider = FakeProvider(_assistant_result())
    result = FinanceAssistantService(provider).analyze(
        service="invoices",
        locale="ar",
        records=[
            {
                "id": 4,
                "amount_residual": 1250,
                "password": "must-not-pass",
                "access_token": "must-not-pass",
            }
        ],
    )

    assert result.analyzed_count == 1
    assert result.automation_opportunities[0].mode == "automatic"
    payload = provider.calls[0]["user_payload"]
    assert isinstance(payload, dict)
    assert payload["records"] == [{"id": 4, "amount_residual": 1250}]
    assert "must-not-pass" not in json.dumps(payload)


def test_assistant_rejects_capability_bearing_or_unknown_workflow_output():
    raw = _assistant_result()
    raw["automation_opportunities"] = [
        {
            "workflow_key": "run_any_odoo_method",
            "title": "غير مسموح",
            "mode": "automatic",
            "reason": "غير مسموح",
        }
    ]
    with pytest.raises(ProviderFailureError):
        FinanceAssistantService(FakeProvider(raw)).analyze(
            service="invoices",
            locale="ar",
            records=[],
        )


def test_sanitized_records_rejects_non_object_rows():
    with pytest.raises(TypeError):
        sanitized_records(["invalid"])


def test_worker_automatically_prepares_one_exact_proposal_for_manager(seed, monkeypatch):
    db = TestingSession()
    task = OperationTask(
        tenant_id=seed["tenant_a"],
        title="Overdue invoice",
        category="financial",
        priority="high",
        created_by_user_id=seed["user_a"],
        source_type="odoo",
        source_record_id=42,
        source_signal="overdue_customer_invoice",
        source_snapshot_json=(
            '{"activity_type_id":3,"company_id":7,"currency":"SAR",'
            '"due_date":"2026-01-01","residual":"12500.50"}'
        ),
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    provider = FakeProvider(_activity_result())
    monkeypatch.setattr(
        operations_worker.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: provider),
    )
    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    operations_worker._AI_AUTOMATION_RETRY_AFTER = 0.0

    assert operations_worker.generate_missing_ai_proposals_once() == 1
    assert operations_worker.generate_missing_ai_proposals_once() == 0

    db = TestingSession()
    action = db.query(OperationAction).filter_by(task_id=task_id).one()
    assert action.status == "awaiting_approval"
    assert action.version == 2
    assert action.approved_hash is None
    proposal = json.loads(action.proposal_json)
    assert proposal["invoice_id"] == 42
    assert proposal["company_id"] == 7
    assert [row.event for row in (
        db.query(OperationActionHistory)
        .filter_by(action_id=action.id)
        .order_by(OperationActionHistory.version.asc())
        .all()
    )] == ["generated", "submitted"]
    db.close()