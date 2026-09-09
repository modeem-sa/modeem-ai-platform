"""Tenant membership administration with server-owned Odoo access scopes."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db
from app.api.deps import RESOURCE_MODULES
from app.operations.automation_catalog import CATALOG
from app.core.security import MAX_PASSWORD_LENGTH, hash_password
from app.models import Tenant, TenantMembership, User
from app.models.tenant_membership import ALLOWED_ROLES
from app.models.user import normalize_email
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/permissions", tags=["permissions"])

# This is deliberately not a pass-through of Odoo's module registry.  It is
# the complete set of technical modules used by Modeem's fixed read policies.
SCOPE_MODULES = frozenset(
    set(RESOURCE_MODULES.values())
    | {workflow.required_odoo_module for workflow in CATALOG if workflow.required_odoo_module}
)
SCOPE_SERVICES = frozenset({
    "financial",
    "human_resources",
    "purchasing",
    "administrative",
    "tenant_memberships",
})


class MembershipInput(BaseModel):
    tenant_id: uuid.UUID
    role: str
    is_active: bool = True
    odoo_module_scope: list[str] | None = None
    service_scope: list[str] | None = None


class EmployeeCreate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=MAX_PASSWORD_LENGTH)
    user_id: uuid.UUID | None = None
    memberships: list[MembershipInput] = Field(min_length=1, max_length=100)


class MembershipUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    odoo_module_scope: list[str] | None = None
    service_scope: list[str] | None = None


def _scope(value: list[str] | None) -> str | None:
    if value is None:
        return None
    normalized = sorted(set(value))
    unknown = set(normalized) - SCOPE_MODULES
    if unknown:
        raise HTTPException(status_code=422, detail="Unsupported Odoo module scope")
    return json.dumps(normalized, separators=(",", ":"))


def _service_scope(value: list[str] | None) -> str | None:
    if value is None:
        return None
    normalized = sorted(set(value))
    if set(normalized) - SCOPE_SERVICES:
        raise HTTPException(status_code=422, detail="Unsupported service scope")
    return json.dumps(normalized, separators=(",", ":"))


def _can_manage_memberships(db: Session, actor: User, tenant_id: uuid.UUID) -> bool:
    if actor.is_superuser:
        return True
    member = db.query(TenantMembership).filter(
        TenantMembership.user_id == actor.id, TenantMembership.tenant_id == tenant_id,
        TenantMembership.is_active.is_(True),
    ).one_or_none()
    if member is None or member.role in ("owner", "admin"):
        return member is not None and member.role in ("owner", "admin")
    if member.role != "manager":
        return False
    if member.service_scope_json:
        try:
            if "tenant_memberships" in json.loads(member.service_scope_json):
                return True
        except (TypeError, json.JSONDecodeError):
            pass
    return False


def _manageable_ids(db: Session, actor: User) -> set[uuid.UUID]:
    if actor.is_superuser:
        return {item[0] for item in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()}
    return {
        item[0]
        for item in db.query(TenantMembership.tenant_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .filter(
            TenantMembership.user_id == actor.id,
            TenantMembership.is_active.is_(True),
            Tenant.is_active.is_(True),
        ).all()
        if _can_manage_memberships(db, actor, item[0])
    }


def _require_manageable(ids: set[uuid.UUID], tenant_id: uuid.UUID) -> None:
    if tenant_id not in ids:
        # A 404 avoids confirming memberships or tenant IDs outside the
        # administrator's authority.
        raise HTTPException(status_code=404, detail="Tenant not found")


def _validate_role(role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="Invalid membership role")


def _validate_granted_role(db: Session, actor: User, tenant_id: uuid.UUID, role: str) -> None:
    _validate_role(role)
    if actor.is_superuser:
        return
    current = db.query(TenantMembership.role).filter(
        TenantMembership.user_id == actor.id, TenantMembership.tenant_id == tenant_id,
        TenantMembership.is_active.is_(True),
    ).scalar()
    if current == "manager" and role in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Managers cannot grant elevated roles")


def _validate_delegated_scopes(
    db: Session, actor: User, tenant_id: uuid.UUID,
    module_scope: list[str] | None, service_scope: list[str] | None,
) -> None:
    if actor.is_superuser:
        return
    actor_member = db.query(TenantMembership).filter(
        TenantMembership.user_id == actor.id,
        TenantMembership.tenant_id == tenant_id,
        TenantMembership.is_active.is_(True),
    ).one()
    if actor_member.role != "manager":
        return
    for proposed, stored, label in (
        (module_scope, actor_member.odoo_module_scope_json, "Odoo module"),
        (service_scope, actor_member.service_scope_json, "service"),
    ):
        actor_scope = json.loads(stored) if stored else None
        if proposed is None and actor_scope is not None:
            raise HTTPException(status_code=403, detail=f"Managers cannot grant unrestricted {label} scope")
        if proposed is not None and actor_scope is not None and not set(proposed).issubset(set(actor_scope)):
            raise HTTPException(status_code=403, detail=f"Managers cannot grant broader {label} scope")


def _ensure_not_last_owner(db: Session, membership: TenantMembership, *, role: str, active: bool) -> None:
    if membership.role != "owner" or (role == "owner" and active):
        return
    # Lock the owner set, not just the edited row, so concurrent demotions
    # cannot both observe two owners and leave the tenant ownerless.
    owner_rows = db.query(TenantMembership.id).filter(
        TenantMembership.tenant_id == membership.tenant_id,
        TenantMembership.role == "owner",
        TenantMembership.is_active.is_(True),
    ).order_by(TenantMembership.id).with_for_update().all()
    if len(owner_rows) <= 1:
        raise HTTPException(status_code=409, detail="Cannot remove, deactivate, or demote the last active owner")


def _alternative_manager_exists(db: Session, member: TenantMembership) -> bool:
    rows = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == member.tenant_id,
        TenantMembership.user_id != member.user_id,
        TenantMembership.is_active.is_(True),
    ).all()
    for candidate in rows:
        if candidate.role in ("owner", "admin"):
            return True
        if candidate.role == "manager" and candidate.service_scope_json:
            try:
                if "tenant_memberships" in json.loads(candidate.service_scope_json):
                    return True
            except (TypeError, json.JSONDecodeError):
                continue
    return False


def _membership_out(member: TenantMembership, user: User, tenant: Tenant) -> dict:
    return {
        "id": str(member.id), "tenant_id": str(tenant.id), "tenant_name": tenant.name,
        "user_id": str(user.id), "email": user.email, "full_name": user.full_name,
        "user_is_active": user.is_active, "role": member.role, "is_active": member.is_active,
        "odoo_module_scope": json.loads(member.odoo_module_scope_json) if member.odoo_module_scope_json else None,
        "service_scope": json.loads(member.service_scope_json) if member.service_scope_json else None,
    }


@router.get("")
def permissions_bootstrap(actor: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    manageable = _manageable_ids(db, actor)
    if not manageable:
        raise HTTPException(status_code=403, detail="Insufficient role")
    rows = db.query(TenantMembership, User, Tenant).join(User, User.id == TenantMembership.user_id).join(
        Tenant, Tenant.id == TenantMembership.tenant_id
    ).filter(TenantMembership.tenant_id.in_(manageable)).order_by(
        Tenant.name, User.full_name, User.email
    ).all()
    return {
        "scope_modules": sorted(SCOPE_MODULES),
        "scope_services": sorted(SCOPE_SERVICES),
        "users": [
            {"id": str(u.id), "email": u.email, "full_name": u.full_name}
            for u in db.query(User).join(TenantMembership, TenantMembership.user_id == User.id)
            .filter(TenantMembership.tenant_id.in_(manageable)).distinct()
            .order_by(User.full_name, User.email).all()
        ],
        "tenants": [{"id": str(t.id), "name": t.name} for t in db.query(Tenant).filter(Tenant.id.in_(manageable)).order_by(Tenant.name).all()],
        "memberships": [_membership_out(m, u, t) for m, u, t in rows],
    }


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_employee(body: EmployeeCreate, actor: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tenant_ids = [item.tenant_id for item in body.memberships]
    if len(set(tenant_ids)) != len(tenant_ids):
        raise HTTPException(status_code=422, detail="Tenant may only be assigned once")
    # Serialize authorization and membership creation per tenant. Stable
    # ordering prevents multi-tenant requests from deadlocking each other.
    db.query(TenantMembership).filter(
        TenantMembership.tenant_id.in_(tenant_ids)
    ).order_by(TenantMembership.tenant_id, TenantMembership.id).with_for_update().populate_existing().all()
    manageable = _manageable_ids(db, actor)
    for tenant_id in tenant_ids:
        _require_manageable(manageable, tenant_id)
    if body.user_id is not None:
        user = db.get(User, body.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
    else:
        if body.email is None or body.full_name is None or body.password is None:
            raise HTTPException(status_code=422, detail="email, full_name, and password are required for a new user")
        email = normalize_email(str(body.email))
        if db.query(User.id).filter(User.email == email).first() is not None:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    existing_tenants = {
        row[0] for row in db.query(TenantMembership.tenant_id).filter(
            TenantMembership.user_id == user.id, TenantMembership.tenant_id.in_(tenant_ids)
        ).all()
    }
    if existing_tenants:
        raise HTTPException(status_code=409, detail="User already has a membership in one or more selected tenants")
    for item in body.memberships:
        _require_manageable(manageable, item.tenant_id)
        _validate_granted_role(db, actor, item.tenant_id, item.role)
        _validate_delegated_scopes(
            db, actor, item.tenant_id, item.odoo_module_scope, item.service_scope
        )
    if body.user_id is None:
        db.add(user)
        db.flush()
    elif not user.is_active:
        raise HTTPException(status_code=422, detail="Cannot assign an inactive user")
    members = []
    for item in body.memberships:
        member = TenantMembership(tenant_id=item.tenant_id, user_id=user.id, role=item.role,
                                  is_active=item.is_active, odoo_module_scope_json=_scope(item.odoo_module_scope),
                                  service_scope_json=_service_scope(item.service_scope))
        db.add(member)
        members.append(member)
        record_audit(db, action="membership.created", actor_type="user", actor_id=str(actor.id),
                     tenant_id=item.tenant_id, resource_type="tenant_membership", resource_id=str(member.id),
                     metadata={"user_id": str(user.id), "role": item.role, "active": item.is_active,
                               "module_scope": item.odoo_module_scope,
                               "service_scope": item.service_scope})
    if body.user_id is None:
        record_audit(db, action="user.created", actor_type="user", actor_id=str(actor.id),
                     resource_type="user", resource_id=str(user.id),
                     metadata={"membership_count": len(members)})
    db.flush()
    return {"user_id": str(user.id), "memberships": [{"id": str(m.id), "tenant_id": str(m.tenant_id)} for m in members]}


@router.patch("/memberships/{membership_id}", dependencies=[Depends(require_csrf)])
def update_membership(membership_id: uuid.UUID, body: MembershipUpdate, actor: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> dict:
    member = db.query(TenantMembership).filter(TenantMembership.id == membership_id).one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    locked_members = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == member.tenant_id
    ).order_by(TenantMembership.id).with_for_update().populate_existing().all()
    member = next(item for item in locked_members if item.id == membership_id)
    _require_manageable(_manageable_ids(db, actor), member.tenant_id)
    old_module_scope = json.loads(member.odoo_module_scope_json) if member.odoo_module_scope_json else None
    old_service_scope = json.loads(member.service_scope_json) if member.service_scope_json else None
    role = body.role if body.role is not None else member.role
    active = body.is_active if body.is_active is not None else member.is_active
    actor_role = db.query(TenantMembership.role).filter(
        TenantMembership.user_id == actor.id,
        TenantMembership.tenant_id == member.tenant_id,
        TenantMembership.is_active.is_(True),
    ).scalar()
    if actor_role == "manager" and member.role in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Managers cannot modify elevated memberships")
    _validate_granted_role(db, actor, member.tenant_id, role)
    _validate_delegated_scopes(
        db,
        actor,
        member.tenant_id,
        body.odoo_module_scope if "odoo_module_scope" in body.model_fields_set else (
            json.loads(member.odoo_module_scope_json) if member.odoo_module_scope_json else None
        ),
        body.service_scope if "service_scope" in body.model_fields_set else (
            json.loads(member.service_scope_json) if member.service_scope_json else None
        ),
    )
    effective_service_scope = (
        body.service_scope
        if "service_scope" in body.model_fields_set
        else (json.loads(member.service_scope_json) if member.service_scope_json else None)
    )
    remains_manager = active and (
        role in ("owner", "admin")
        or (
            role == "manager"
            and effective_service_scope is not None
            and "tenant_memberships" in effective_service_scope
        )
    )
    self_management_change = member.user_id == actor.id and not remains_manager
    if self_management_change and not _alternative_manager_exists(db, member):
        raise HTTPException(status_code=409, detail="Cannot remove the last tenant membership manager")
    _ensure_not_last_owner(db, member, role=role, active=active)
    if body.role is not None:
        member.role = role
    if body.is_active is not None:
        member.is_active = active
    # Explicit null resets to unrestricted.  Pydantic field-set distinguishes
    # it from an omitted scope update.
    if "odoo_module_scope" in body.model_fields_set:
        member.odoo_module_scope_json = _scope(body.odoo_module_scope)
    if "service_scope" in body.model_fields_set:
        member.service_scope_json = _service_scope(body.service_scope)
    record_audit(db, action="membership.updated", actor_type="user", actor_id=str(actor.id),
                 tenant_id=member.tenant_id, resource_type="tenant_membership", resource_id=str(member.id),
                 metadata={"user_id": str(member.user_id), "role": member.role, "active": member.is_active,
                            "scope_restricted": member.odoo_module_scope_json is not None,
                            "old_module_scope": old_module_scope,
                            "new_module_scope": json.loads(member.odoo_module_scope_json) if member.odoo_module_scope_json else None,
                            "old_service_scope": old_service_scope,
                            "new_service_scope": json.loads(member.service_scope_json) if member.service_scope_json else None})
    db.flush()
    user, tenant = db.get(User, member.user_id), db.get(Tenant, member.tenant_id)
    return _membership_out(member, user, tenant)