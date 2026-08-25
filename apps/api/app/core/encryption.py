"""Credential encryption/decryption using Fernet (AES-128-CBC + HMAC-SHA256).

The Fernet key is derived from SESSION_SECRET via HKDF — see security.py for
the derivation rationale.  To split keys later, replace get_fernet_key() with
a direct read of an ENCRYPTION_KEY_SECRET env var.
"""

import json

from cryptography.fernet import Fernet

from app.core.security import get_fernet_key


def _fernet() -> Fernet:
    return Fernet(get_fernet_key())


def encrypt_creds(creds: dict) -> str:
    """Encrypt a credentials dict and return a URL-safe Fernet token string."""
    plaintext = json.dumps(creds, ensure_ascii=False).encode()
    return _fernet().encrypt(plaintext).decode()


def decrypt_creds(token: str) -> dict:
    """Decrypt a Fernet token string and return the original credentials dict."""
    plaintext = _fernet().decrypt(token.encode())
    return json.loads(plaintext)
