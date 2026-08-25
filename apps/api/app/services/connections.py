"""Connections service — CRUD with transparent encryption/decryption."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.encryption import encrypt_creds
from app.models.connection import Connection


def list_connections(db: Session, tenant_id: uuid.UUID) -> list[Connection]:
    return (
        db.query(Connection)
        .filter(Connection.tenant_id == tenant_id, Connection.is_active.is_(True))
        .order_by(Connection.created_at.desc())
        .all()
    )


def create_connection(
    db: Session,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    connector_type: str,
    creds: dict,
) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        name=name,
        connector_type=connector_type,
        encrypted_creds=encrypt_creds(creds),
        created_by=created_by,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_connection(
    db: Session,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> bool:
    """Soft-delete a connection.  Returns False if not found or wrong tenant."""
    conn: Connection | None = (
        db.query(Connection)
        .filter(Connection.id == connection_id, Connection.tenant_id == tenant_id)
        .first()
    )
    if conn is None:
        return False
    conn.is_active = False
    conn.updated_at = datetime.now(UTC)
    db.commit()
    return True
