"""Password hashing and session-token utilities.

Password hashing uses Argon2id via argon2-cffi (the maintained Python
binding of the reference Argon2 implementation).

Session tokens are signed JWTs (HS256) carried in an HttpOnly cookie.
The signing secret comes from the AUTH_SECRET environment variable.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.core.config import get_settings

SESSION_COOKIE_NAME = "modeem_session"
CSRF_COOKIE_NAME = "modeem_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Reject pathological password sizes before hashing (Argon2 cost scales with input).
MAX_PASSWORD_LENGTH = 256

MIN_PRODUCTION_SECRET_LENGTH = 32

_hasher = PasswordHasher()  # Argon2id by default

# Pre-generated once at import so unknown-email logins still perform a full
# Argon2 verification (mitigates user-enumeration timing). Never per-request.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def verify_dummy_password(password: str) -> None:
    """Burn the same Argon2 work as a real verification; always 'fails'."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        pass


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_value: str, header_value: str) -> bool:
    return secrets.compare_digest(cookie_value, header_value)


def validate_auth_secret_for_production(environment: str, auth_secret: str) -> None:
    """Fail clearly in production when AUTH_SECRET is missing or weak.

    Never logs or includes the secret value itself.
    """
    if environment != "production":
        return
    if not auth_secret:
        raise RuntimeError(
            "AUTH_SECRET must be explicitly configured in production."
        )
    if len(auth_secret) < MIN_PRODUCTION_SECRET_LENGTH:
        raise RuntimeError(
            f"AUTH_SECRET must be at least {MIN_PRODUCTION_SECRET_LENGTH} "
            "characters in production."
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def create_session_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID | None, *, expires_in_seconds: int | None = None
) -> str:
    settings = get_settings()
    if not settings.auth_secret:
        raise RuntimeError("AUTH_SECRET is not configured")
    ttl = expires_in_seconds or settings.session_ttl_seconds
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    if tenant_id is not None:
        payload["tid"] = str(tenant_id)
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_session_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.auth_secret:
        return None
    try:
        return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
