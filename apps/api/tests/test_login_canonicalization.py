"""Task: canonicalize Odoo login/username before expanding data access.

Phase 2E: Connection.username is the ONLY login identity; OdooCredentials
holds just the secret. Canonicalization rules are applied on create and
update: trim, NFKC, email lowercasing, and rejection of dangerous chars.
"""

import pytest
from pydantic import ValidationError

from app.schemas.connections import (
    ConnectionCreate,
    ConnectionUpdate,
    canonicalize_odoo_login,
    normalize_username,
)

# ---------- unit rules ----------


def test_trims_whitespace():
    assert canonicalize_odoo_login("  api-user  ") == "api-user"


def test_email_is_lowercased():
    assert canonicalize_odoo_login("  Admin@Example.COM ") == "admin@example.com"


def test_non_email_keeps_case():
    # Odoo compares non-email logins case-sensitively; do not lowercase.
    assert canonicalize_odoo_login("ApiUser") == "ApiUser"


def test_multiple_at_signs_not_lowercased():
    assert canonicalize_odoo_login("A@b@C") == "A@b@C"


def test_nfkc_normalization():
    # Full-width letters normalize to ASCII, then email rule lowercases.
    assert canonicalize_odoo_login("Ａｄｍｉｎ@ｅｘ.ｃｏｍ") == "admin@ex.com"


def test_normalize_username_delegates():
    assert normalize_username("  Admin@Example.com ") == "admin@example.com"


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_blank_rejected(bad):
    with pytest.raises(ValueError):
        canonicalize_odoo_login(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "a b",  # internal whitespace
        "a\tb",
        "a<b",
        'a"b',
        "a'b",
        "a`b",
        "a\\b",
        "a;b",
        "a\x00b",  # NUL
        "a\x07b",  # control char
        "a\u200eb",  # format char (LRM)
    ],
)
def test_dangerous_characters_rejected(bad):
    with pytest.raises(ValueError):
        canonicalize_odoo_login(bad)


# ---------- applied at schema boundaries ----------


def _create_body(**overrides):
    body = {
        "name": "c",
        "provider": "odoo",
        "base_url": "https://odoo.example.com",
        "username": "User@X.Com",
        "credentials": {"password_or_api_key": "s"},
    }
    body.update(overrides)
    return body


def test_create_username_canonicalized():
    body = ConnectionCreate(**_create_body(username="  User@X.Com "))
    assert body.username == "user@x.com"


def test_create_username_required():
    with pytest.raises(ValidationError):
        ConnectionCreate(**{k: v for k, v in _create_body().items() if k != "username"})


def test_create_username_rejects_forbidden():
    with pytest.raises(ValidationError):
        ConnectionCreate(**_create_body(username="ad'min"))


def test_create_credentials_reject_login_key():
    # Phase 2E: login lives only in username; extra keys are forbidden.
    with pytest.raises(ValidationError):
        ConnectionCreate(
            **_create_body(
                credentials={"login": "x", "password_or_api_key": "s"}
            )
        )


def test_update_username_canonicalized():
    assert ConnectionUpdate(username="  ApiUser ").username == "ApiUser"
    assert ConnectionUpdate(username=" Admin@Ex.Com ").username == "admin@ex.com"


def test_update_username_null_passes_schema():
    # Explicit null is rejected later in the API layer (cannot clear the
    # canonical login); the schema itself passes it through.
    assert ConnectionUpdate(username=None).username is None


def test_update_username_rejects_forbidden():
    with pytest.raises(ValidationError):
        ConnectionUpdate(username="a;b")
