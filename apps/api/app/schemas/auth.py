"""Pydantic schemas for authentication endpoints.

Password hashes are never included in any response schema.
"""

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.core.security import MAX_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)


class TenantSelectRequest(BaseModel):
    tenant_id: uuid.UUID


class MembershipOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: str


class CurrentTenantOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_superuser: bool
    current_tenant: CurrentTenantOut | None
    memberships: list[MembershipOut]


class TenantContextOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: str
