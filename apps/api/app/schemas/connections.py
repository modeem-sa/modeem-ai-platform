"""Pydantic schemas for Connections (Phase 2B).

Responses expose only safe metadata — never credentials, ciphertext,
nonces, or encryption details beyond a `has_credentials` boolean.
"""

import unicodedata
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

# Characters never allowed in an Odoo login/username. Blocking these keeps
# audit logs, HTML views, and any downstream query building safe regardless
# of how the value is later interpolated.
_FORBIDDEN_LOGIN_CHARS = set('<>"\'`\\;\x00')


def validate_base_url(value: str, *, require_https: bool) -> str:
    """Validate and normalize a stored base URL.

    Rejects credentials-in-URL, query strings, and fragments; strips any
    trailing slash from the path. Never fetches or resolves the host —
    SSRF/IP/DNS protections are a Phase 2C prerequisite before any
    network call is allowed.
    """
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ValueError("base_url must start with http:// or https://")
    if require_https and parts.scheme != "https":
        raise ValueError("base_url must use https:// in production")
    if not parts.hostname:
        raise ValueError("base_url must include a valid host")
    if parts.username is not None or parts.password is not None:
        raise ValueError(
            "base_url must not contain credentials; store them separately"
        )
    if parts.query:
        raise ValueError("base_url must not contain a query string")
    if parts.fragment:
        raise ValueError("base_url must not contain a fragment")
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def canonicalize_odoo_login(value: str) -> str:
    """Canonicalize an Odoo login/username to ONE stable form.

    Rules (applied on create AND update, before storage):
    - Unicode NFKC normalization (full-width chars, compatibility forms).
    - Strip leading/trailing whitespace; must be non-empty afterwards.
    - Reject control characters and internal whitespace (a login is a
      single token — spaces inside indicate a paste/typing error).
    - Reject dangerous characters: < > " ' ` \\ ; and NUL.
    - Email-shaped logins (exactly one '@', non-empty local and domain
      parts) are lowercased — Odoo logins are conventionally emails and
      case differences would create duplicate identities. Non-email
      logins keep their case, since Odoo compares them case-sensitively.
    """
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        raise ValueError("login must not be blank")
    for ch in value:
        if ch in _FORBIDDEN_LOGIN_CHARS:
            raise ValueError(f"login contains a forbidden character: {ch!r}")
        if unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError("login must not contain control characters")
        if ch.isspace():
            raise ValueError("login must not contain whitespace")
    if value.count("@") == 1:
        local, domain = value.split("@")
        if local and domain:
            value = value.lower()
    return value


def normalize_username(value: str) -> str:
    """Canonical Odoo login normalization (Phase 2E). Delegates to
    canonicalize_odoo_login: Connection.username is the ONLY login identity."""
    return canonicalize_odoo_login(value)


class OdooCredentials(BaseModel):
    """Secret payload for provider 'odoo'. Stored only encrypted.

    Phase 2E: contains ONLY the secret. The Odoo login identity lives
    exclusively in Connection.username — a `login` key here is rejected.
    """

    model_config = {"extra": "forbid"}

    password_or_api_key: str = Field(min_length=1, max_length=1024)


class ConnectionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    provider: Literal["odoo"]
    base_url: str = Field(max_length=500)
    database_name: str | None = Field(default=None, max_length=200)
    # Canonical Odoo login identity — required and non-blank for new
    # connections (needed by XML-RPC auth and JSON-2 legacy fallback).
    username: str = Field(min_length=1, max_length=200)
    auth_mode: Literal["auto", "password", "api_key"] = "auto"
    credentials: OdooCredentials

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("username")
    @classmethod
    def _canonicalize_username(cls, v: str) -> str:
        return canonicalize_odoo_login(v)


class ConnectionUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    base_url: str | None = Field(default=None, max_length=500)
    database_name: str | None = Field(default=None, max_length=200)
    # Omitted -> preserve existing username. Explicit null or blank is
    # rejected: the canonical login cannot be cleared.
    username: str | None = Field(default=None, max_length=200)

    @field_validator("username")
    @classmethod
    def _canonicalize_username(cls, v: str | None) -> str | None:
        if v is None:
            # Explicit null vs omitted is enforced in the API layer via
            # model_fields_set (clearing username is rejected there).
            return None
        return canonicalize_odoo_login(v)

    status: Literal["configured", "disabled"] | None = None
    auth_mode: Literal["auto", "password", "api_key"] | None = None
    # If supplied: encrypt and replace. If omitted: keep existing secret.
    credentials: OdooCredentials | None = None


class ConnectionOut(BaseModel):
    """Safe metadata only. No secret or ciphertext fields exist here."""

    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    database_name: str | None
    username: str | None
    status: str
    is_active: bool
    has_credentials: bool
    auth_mode: str
    detected_odoo_version: str | None
    detected_odoo_major: int | None
    detected_edition: str | None
    selected_transport: str | None
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_error_code: str | None
    created_at: datetime
    updated_at: datetime


class ConnectionTestResult(BaseModel):
    """Safe connectivity test result. Never contains secrets, raw upstream
    errors, or remote tracebacks."""

    success: bool
    error_code: str | None = None
    odoo_version: str | None = None
    odoo_major: int | None = None
    edition: str | None = None
    transport: str | None = None
    capabilities: dict | None = None
    tested_at: datetime
