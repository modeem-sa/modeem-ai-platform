"""Seed realistic demo work for one employee assigned to 15 associations.

Usage: python seed_operations_demo.py USER_EMAIL
"""

import sys
import uuid
from datetime import UTC, datetime, timedelta

from app.db.base import get_session_factory
from app.models import OperationsTask, Tenant, TenantMembership, User

ASSOCIATIONS = [
    "جمعية البر بالرياض",
    "جمعية رعاية الأيتام",
    "جمعية التنمية الأسرية",
    "جمعية حفظ النعمة",
    "جمعية ذوي الإعاقة",
    "جمعية تمكين الشباب",
    "جمعية العناية بالمساجد",
    "جمعية الإسكان التنموي",
    "جمعية سقيا الماء",
    "جمعية مكافحة السرطان",
    "جمعية كفالة الأيتام",
    "جمعية الدعوة والإرشاد",
    "جمعية رعاية كبار السن",
    "جمعية المسؤولية المجتمعية",
    "جمعية التطوع الصحي",
]

TASK_TEMPLATES = [
    ("اعتماد مسير الرواتب الشهري", "financial", "awaiting_approval", "urgent", 0),
    ("مراجعة فواتير الموردين", "financial", "overdue", "high", -2),
    ("تجديد عقود الموظفين", "administrative", "upcoming", "normal", 5),
    ("معالجة فرق التسوية البنكية", "financial", "needs_intervention", "urgent", 1),
    ("رفع تقرير الأداء إلى مجلس الإدارة", "administrative", "upcoming", "high", 3),
]


def seed(email: str) -> None:
    db = get_session_factory()()
    try:
        user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
        if user is None:
            raise SystemExit(f"No user found for {email}")
        now = datetime.now(UTC)
        for index, name in enumerate(ASSOCIATIONS):
            code = f"demo-association-{index + 1:02d}"
            tenant = db.query(Tenant).filter(Tenant.code == code).one_or_none()
            if tenant is None:
                tenant = Tenant(name=name, code=code, is_active=True)
                db.add(tenant)
                db.flush()
            membership = (
                db.query(TenantMembership)
                .filter(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.user_id == user.id,
                )
                .one_or_none()
            )
            if membership is None:
                db.add(
                    TenantMembership(
                        tenant_id=tenant.id, user_id=user.id, role="manager", is_active=True
                    )
                )
            if db.query(OperationsTask).filter(OperationsTask.tenant_id == tenant.id).count():
                continue
            for task_index, template in enumerate(TASK_TEMPLATES[: 2 + (index % 4)]):
                title, work_type, status, priority, due_days = template
                db.add(
                    OperationsTask(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, f"{code}:{task_index}"),
                        tenant_id=tenant.id,
                        title=title,
                        description=f"متابعة {title} ضمن دورة العمل المشتركة للجمعية.",
                        work_type=work_type,
                        status=status,
                        priority=priority,
                        due_at=now + timedelta(days=due_days, hours=index % 8),
                        assignee_name=user.full_name,
                        source="demo",
                    )
                )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python seed_operations_demo.py USER_EMAIL")
    seed(sys.argv[1])