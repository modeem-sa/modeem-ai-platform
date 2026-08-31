"""Tenant-scoped, admin-editable automation workflow policy tests."""

import json

from app.models import AutomationWorkflowOverride, OperationTask
from app.operations.automation_catalog import CATALOG, default_modes, get_workflow
from app.workers import operations as operations_worker
from tests.test_auth_security import TestingSession, _client, _csrf, _login

WORKFLOW_KEY = "finance.overdue_invoice_followup"


def _catalog(client, tenant_id):
    return client.get(
        "/api/v1/operations/automation/catalog",
        params={"tenant_id": str(tenant_id)},
    )


def _update(client, tenant_id, *, enabled, modes, expected_version):
    return client.put(
        f"/api/v1/operations/automation/workflows/{WORKFLOW_KEY}",
        json={
            "tenant_id": str(tenant_id),
            "enabled": enabled,
            "step_modes": modes,
            "expected_version": expected_version,
        },
        headers=_csrf(client),
    )


def test_catalog_exposes_safe_defaults_and_proposed_paths_start_disabled(roles_seed):
    client = _client()
    _login(client, "admin@example.com")

    response = _catalog(client, roles_seed["tenant_a"])

    assert response.status_code == 200
    body = response.json()
    assert body["can_manage"] is True
    by_key = {item["key"]: item for item in body["workflows"]}
    finance = by_key[WORKFLOW_KEY]
    assert finance["enabled"] is True
    assert finance["step_modes"]["submit_for_approval"] == "automatic"
    assert "automatic" not in next(
        step["allowed_modes"] for step in finance["steps"] if step["key"] == "execute"
    )
    assert by_key["hr.attendance_review"]["enabled"] is False
    assert by_key["purchasing.purchase_request_review"]["enabled"] is False
    assert by_key["administrative.official_letter"]["enabled"] is False
    assert all("model" not in json.dumps(item).lower() for item in body["workflows"])


def test_admin_can_update_persist_reset_and_stale_version_is_rejected(roles_seed):
    client = _client()
    _login(client, "admin@example.com")
    workflow = get_workflow(WORKFLOW_KEY)
    assert workflow is not None
    modes = default_modes(workflow)
    modes["analyze"] = "manual"

    updated = _update(
        client,
        roles_seed["tenant_a"],
        enabled=False,
        modes=modes,
        expected_version=workflow.version,
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["customized"] is True
    persisted = _catalog(client, roles_seed["tenant_a"]).json()["workflows"][0]
    assert persisted["enabled"] is False
    assert persisted["step_modes"]["analyze"] == "manual"

    stale = _update(
        client,
        roles_seed["tenant_a"],
        enabled=True,
        modes=default_modes(workflow),
        expected_version=workflow.version,
    )
    assert stale.status_code == 409

    reset = client.post(
        f"/api/v1/operations/automation/workflows/{WORKFLOW_KEY}/reset",
        json={"tenant_id": str(roles_seed["tenant_a"]), "expected_version": 2},
        headers=_csrf(client),
    )
    assert reset.status_code == 200
    assert reset.json()["enabled"] is True
    assert reset.json()["customized"] is False
    assert reset.json()["version"] == 3


def test_role_scope_unknown_steps_and_csrf_are_enforced(roles_seed):
    manager = _client()
    _login(manager, "manager@example.com")
    workflow = get_workflow(WORKFLOW_KEY)
    assert workflow is not None

    assert _catalog(manager, roles_seed["tenant_a"]).status_code == 200
    denied = _update(
        manager,
        roles_seed["tenant_a"],
        enabled=True,
        modes=default_modes(workflow),
        expected_version=workflow.version,
    )
    assert denied.status_code == 403
    assert _catalog(manager, roles_seed["tenant_b"]).status_code == 404

    admin = _client()
    _login(admin, "admin@example.com")
    invalid_modes = default_modes(workflow)
    invalid_modes["arbitrary_odoo_method"] = "automatic"
    invalid = _update(
        admin,
        roles_seed["tenant_a"],
        enabled=True,
        modes=invalid_modes,
        expected_version=workflow.version,
    )
    assert invalid.status_code == 422
    no_csrf = admin.put(
        f"/api/v1/operations/automation/workflows/{WORKFLOW_KEY}",
        json={
            "tenant_id": str(roles_seed["tenant_a"]),
            "enabled": True,
            "step_modes": default_modes(workflow),
            "expected_version": workflow.version,
        },
    )
    assert no_csrf.status_code == 403


def test_disabled_workflow_blocks_generation_before_ai_provider(seed, monkeypatch):
    workflow = get_workflow(WORKFLOW_KEY)
    assert workflow is not None
    db = TestingSession()
    db.add(
        AutomationWorkflowOverride(
            tenant_id=seed["tenant_a"],
            workflow_key=WORKFLOW_KEY,
            enabled=False,
            step_modes_json=json.dumps(default_modes(workflow)),
            version=2,
            updated_by_user_id=seed["user_a"],
        )
    )
    db.add(
        OperationTask(
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
    )
    db.commit()
    db.close()

    monkeypatch.setattr(operations_worker, "get_session_factory", lambda: TestingSession)
    monkeypatch.setattr(
        operations_worker.OpenAICompatibleProvider,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("AI must not be called"))),
    )
    operations_worker._AI_AUTOMATION_RETRY_AFTER = 0.0

    assert operations_worker.generate_missing_ai_proposals_once() == 0


def test_catalog_keys_are_unique():
    assert len({workflow.key for workflow in CATALOG}) == len(CATALOG)