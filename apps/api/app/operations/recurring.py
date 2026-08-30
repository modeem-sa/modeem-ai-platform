"""Bounded timezone-aware recurring task occurrence generator."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models import OperationTask, RecurringTaskOccurrence, RecurringTaskTemplate


def generate_occurrences(
    db: Session, *, now: datetime | None = None, max_catchup: int = 31
) -> int:
    now = now or datetime.now(UTC)
    made = 0
    for template in db.query(RecurringTaskTemplate).filter_by(enabled=True).all():
        try:
            local_day = now.astimezone(ZoneInfo(template.timezone)).date()
        except ZoneInfoNotFoundError:
            continue
        span = {"daily": 1, "weekly": 7, "monthly": 30}.get(template.frequency)
        if span is None:
            continue
        for offset in range(max_catchup):
            day = local_day - timedelta(days=offset)
            if offset and offset % span:
                continue
            key = day.isoformat()
            exists = (
                db.query(RecurringTaskOccurrence)
                .filter_by(template_id=template.id, occurrence_date=key)
                .first()
            )
            if exists:
                continue
            task = OperationTask(
                tenant_id=template.tenant_id,
                title=template.title,
                description=template.description,
                category=template.category,
                priority=template.priority,
                created_by_user_id=template.created_by_user_id,
                due_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                source_type="recurring",
                source_signal="recurring",
                source_reference=str(template.id),
                source_sync_state="generated",
                source_synced_at=now,
            )
            db.add(task)
            db.flush()
            db.add(
                RecurringTaskOccurrence(
                    template_id=template.id,
                    task_id=task.id,
                    occurrence_date=key,
                )
            )
            made += 1
    return made