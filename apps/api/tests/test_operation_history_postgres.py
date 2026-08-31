"""PostgreSQL integration coverage for database-level task-history immutability."""

import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command

API_DIR = Path(__file__).resolve().parents[1]


def _postgres_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url or make_url(url).get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL DATABASE_URL is required for this integration test")
    return url


def _schema_url(database_url: str, schema: str) -> str:
    url = make_url(database_url)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    return url.set(query=query).render_as_string(hide_password=False)


def test_history_is_append_only_but_insert_and_parent_cascade_work(monkeypatch):
    database_url = _postgres_url()
    schema = f"task_history_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url)
    schema_url = _schema_url(database_url, schema)
    engine = create_engine(schema_url)

    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        monkeypatch.setenv("DATABASE_URL", schema_url)
        config = Config(str(API_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(API_DIR / "alembic"))
        command.upgrade(config, "head")

        tenant_id, user_id, task_id, history_id = (uuid.uuid4() for _ in range(4))
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, code, created_at, updated_at)
                    VALUES (:id, 'History Test', :code, now(), now())
                    """
                ),
                {"id": tenant_id, "code": f"history-{uuid.uuid4().hex}"},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users
                        (id, email, full_name, password_hash, is_active,
                         is_superuser, created_at, updated_at)
                    VALUES
                        (:id, :email, 'History Tester', 'not-used', true,
                         false, now(), now())
                    """
                ),
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO operation_tasks
                        (id, tenant_id, title, category, priority, status,
                         created_by_user_id, version, created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, 'Protected task', 'administrative',
                         'high', 'pending', :user_id, 1, now(), now())
                    """
                ),
                {"id": task_id, "tenant_id": tenant_id, "user_id": user_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO operation_task_history
                        (id, task_id, tenant_id, actor_user_id, action,
                         from_status, to_status, version, created_at)
                    VALUES
                        (:id, :task_id, :tenant_id, :user_id, 'created',
                         NULL, 'pending', 1, now())
                    """
                ),
                {
                    "id": history_id,
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )

        for statement in (
            "UPDATE operation_task_history SET note = 'tampered' WHERE id = :id",
            "DELETE FROM operation_task_history WHERE id = :id",
        ):
            with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
                connection.execute(text(statement), {"id": history_id})

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM operation_tasks WHERE id = :id"),
                {"id": task_id},
            )
            remaining = connection.scalar(
                text("SELECT count(*) FROM operation_task_history WHERE id = :id"),
                {"id": history_id},
            )
        assert remaining == 0
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()