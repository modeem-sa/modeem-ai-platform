"""Server-owned, capability-free automation workflow catalogue.

This module intentionally contains only product workflow metadata.  It never
contains an Odoo model, method, domain, or executable user supplied value.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.automation_workflow_override import AutomationWorkflowOverride

AUTOMATION_MODES = ("automatic", "approval_required", "manual")


@dataclass(frozen=True)
class CatalogStep:
    key: str
    type: str
    default_mode: str
    allowed_modes: tuple[str, ...]
    executor_available: bool


@dataclass(frozen=True)
class CatalogWorkflow:
    key: str
    module: str
    service: str
    label_ar: str
    label_en: str
    description_ar: str
    description_en: str
    version: int
    enabled_default: bool
    steps: tuple[CatalogStep, ...]


_STANDARD_STEPS = (
    CatalogStep("read_source", "read", "automatic", ("automatic", "manual"), True),
    CatalogStep("analyze", "analysis", "automatic", ("automatic", "manual"), True),
    CatalogStep("prepare_draft", "draft", "automatic", AUTOMATION_MODES, True),
    CatalogStep("submit_for_approval", "approval_submission", "automatic", ("automatic", "manual"), True),
    CatalogStep(
        "manager_approval",
        "approval",
        "approval_required",
        ("approval_required", "manual"),
        True,
    ),
    CatalogStep(
        "execute",
        "external_write",
        "approval_required",
        ("approval_required", "manual"),
        True,
    ),
    CatalogStep("verify", "verification", "automatic", ("automatic", "manual"), True),
)
_PROPOSED_STEPS = tuple(
    CatalogStep(step.key, step.type, step.default_mode, step.allowed_modes, False)
    for step in _STANDARD_STEPS
)

CATALOG: tuple[CatalogWorkflow, ...] = (
    CatalogWorkflow("finance.overdue_invoice_followup", "finance", "overdue_invoice_followup",
        "متابعة الفواتير المتأخرة", "Overdue invoice follow-up",
        "قراءة الفواتير المتأخرة وتجهيز نشاط متابعة آمن للاعتماد.",
        "Read overdue invoices and prepare a safe follow-up activity for approval.",
        1, True, _STANDARD_STEPS),
    CatalogWorkflow("hr.attendance_review", "human_resources", "attendance_review",
        "مراجعة الحضور", "Attendance review", "اقتراح مراجعة حالات الحضور.",
        "Proposed attendance exception review.", 1, False, _PROPOSED_STEPS),
    CatalogWorkflow("purchasing.purchase_request_review", "purchasing", "purchase_request_review",
        "مراجعة طلبات الشراء", "Purchase request review", "اقتراح مراجعة طلبات الشراء.",
        "Proposed purchase request review.", 1, False, _PROPOSED_STEPS),
    CatalogWorkflow("administrative.official_letter", "administrative", "official_letter",
        "إعداد خطاب رسمي", "Official letter preparation", "اقتراح إعداد خطاب رسمي.",
        "Proposed official letter preparation.", 1, False, _PROPOSED_STEPS),
)
_BY_KEY = {workflow.key: workflow for workflow in CATALOG}


def get_workflow(workflow_key: str) -> CatalogWorkflow | None:
    return _BY_KEY.get(workflow_key)


def default_modes(workflow: CatalogWorkflow) -> dict[str, str]:
    return {step.key: step.default_mode for step in workflow.steps}


def validate_step_modes(workflow: CatalogWorkflow, modes: object) -> dict[str, str]:
    if not isinstance(modes, dict) or set(modes) != {step.key for step in workflow.steps}:
        raise ValueError("Step modes must contain exactly the workflow step keys")
    allowed = {step.key: step.allowed_modes for step in workflow.steps}
    if any(not isinstance(mode, str) or mode not in allowed[key] for key, mode in modes.items()):
        raise ValueError("A step mode is not allowed for this workflow")
    return dict(modes)


def effective_config(
    db: Session, tenant_id: uuid.UUID, workflow_key: str
) -> dict[str, object]:
    """Return the fully resolved configuration used by API and workers."""
    workflow = get_workflow(workflow_key)
    if workflow is None:
        raise ValueError("Unknown automation workflow")
    override = db.query(AutomationWorkflowOverride).filter_by(
        tenant_id=tenant_id, workflow_key=workflow_key
    ).one_or_none()
    modes = default_modes(workflow)
    if override is not None:
        try:
            modes = validate_step_modes(workflow, json.loads(override.step_modes_json))
        except (json.JSONDecodeError, ValueError):
            # This should be unreachable due to API validation.  Fail closed if
            # a database was manually corrupted.
            modes = {step.key: "manual" for step in workflow.steps}
        return {"workflow": workflow, "enabled": override.enabled, "step_modes": modes,
                "version": override.version,
                "customized": override.enabled != workflow.enabled_default or modes != default_modes(workflow),
                "updated_by_user_id": override.updated_by_user_id,
                "updated_at": override.updated_at}
    return {"workflow": workflow, "enabled": workflow.enabled_default, "step_modes": modes,
            "version": workflow.version, "customized": False, "updated_by_user_id": None,
            "updated_at": None}


def serialize_effective(config: dict[str, object]) -> dict[str, object]:
    workflow = config["workflow"]
    assert isinstance(workflow, CatalogWorkflow)
    modes = config["step_modes"]
    assert isinstance(modes, dict)
    return {
        "key": workflow.key, "module": workflow.module, "service": workflow.service,
        "label_ar": workflow.label_ar, "label_en": workflow.label_en,
        "description_ar": workflow.description_ar, "description_en": workflow.description_en,
        "definition_version": workflow.version, "enabled_default": workflow.enabled_default,
        "enabled": config["enabled"], "step_modes": modes, "version": config["version"],
        "customized": config["customized"], "updated_by_user_id": config["updated_by_user_id"],
        "updated_at": config["updated_at"],
        "steps": [{"key": step.key, "type": step.type, "default_mode": step.default_mode,
                   "allowed_modes": list(step.allowed_modes),
                   "executor_available": step.executor_available} for step in workflow.steps],
    }