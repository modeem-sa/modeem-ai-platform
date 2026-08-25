"""Audit logging helper for authentication and tenancy events.

Never store passwords, session tokens, or authorization headers here.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    actor_type: str,
    actor_id: str | None = None,
    tenant_id: uuid.UUID | None = None,
    resource_type: str = "auth",
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata,
    )
    db.add(entry)
    return entry
