"""Canonical Odoo auth-material resolution (Phase 2E).

Single trusted backend helper used by BOTH Test Connection and Read
Preview (and any future endpoint) so username/secret extraction logic is
never duplicated.

Rules:
- Connection.username is the ONLY canonical Odoo login identity.
- The secret comes ONLY from the decrypted `password_or_api_key`.
- A legacy encrypted `login` key (pre-Phase-2E payloads) is IGNORED
  completely — never used, never logged, never exposed.
- Missing/blank username or missing secret fails safely BEFORE any
  network activity, with a static message that leaks nothing.

Never log, audit, or serialize OdooAuthMaterial.
"""

from dataclasses import dataclass


class AuthMaterialError(Exception):
    """Safe configuration failure. `message` is static text only."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class OdooAuthMaterial:
    login: str
    secret: str


def resolve_auth_material(
    username: str | None, decrypted_credentials: dict
) -> OdooAuthMaterial:
    """Build canonical auth material from Connection.username plus the
    decrypted credential payload. Raises AuthMaterialError before any
    network call when the configuration is unusable."""
    login = (username or "").strip()
    if not login:
        raise AuthMaterialError(
            "Connection has no username; set the username and re-test"
        )
    secret = decrypted_credentials.get("password_or_api_key")
    if not isinstance(secret, str) or not secret:
        raise AuthMaterialError(
            "Stored credentials are missing the secret; replace credentials"
        )
    # Any legacy "login" key in the decrypted payload is deliberately
    # ignored: Connection.username always wins.
    return OdooAuthMaterial(login=login, secret=secret)
