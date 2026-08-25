"""Encrypted credential storage for Connections (Phase 2B).

AES-256-GCM via the maintained `cryptography` package — no custom crypto.

Design:
- CONNECTION_ENCRYPTION_KEY: URL-safe Base64 encoding of exactly 32 random
  bytes. Independent of AUTH_SECRET; never derived from it, never logged,
  never returned by any API.
- Every encryption uses a fresh random 96-bit nonce (stored alongside the
  ciphertext).
- Associated data (AAD) binds each ciphertext to its tenant_id and
  connection_id, so a ciphertext copied onto another record fails to
  decrypt.
- An encryption version is stored per record so key rotation can be added
  later without a schema change.

There is deliberately NO generic public decrypt API: decryption is only for
trusted backend services that actually need the credential. No Phase 2B
endpoint returns decrypted credentials.
"""

import base64
import binascii
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CURRENT_ENCRYPTION_VERSION = 1
# Kept for backward compatibility with existing imports.
ENCRYPTION_VERSION = CURRENT_ENCRYPTION_VERSION
_SUPPORTED_VERSIONS = frozenset({1})
_KEY_BYTES = 32
_NONCE_BYTES = 12


class EncryptionConfigError(RuntimeError):
    """Raised when CONNECTION_ENCRYPTION_KEY is missing or invalid."""


class CredentialDecryptionError(RuntimeError):
    """Raised when a ciphertext fails authentication or decoding."""


def validate_encryption_key(encoded_key: str) -> bytes:
    """Validate the configured key and return the raw 32 key bytes.

    Never include the key material in the raised error messages.
    """
    if not encoded_key:
        raise EncryptionConfigError(
            "CONNECTION_ENCRYPTION_KEY is not configured. Generate one with: "
            "python -c \"import base64, os; "
            "print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
        )
    try:
        # validate=True rejects any character outside the URL-safe Base64
        # alphabet instead of silently ignoring it.
        raw = base64.b64decode(
            encoded_key.encode("ascii"), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise EncryptionConfigError(
            "CONNECTION_ENCRYPTION_KEY is not valid URL-safe Base64."
        ) from exc
    if len(raw) != _KEY_BYTES:
        raise EncryptionConfigError(
            "CONNECTION_ENCRYPTION_KEY must decode to exactly 32 bytes (256 bits)."
        )
    return raw


def _load_key() -> bytes:
    from app.core.config import get_settings

    return validate_encryption_key(get_settings().connection_encryption_key)


def _aad(version: int, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> bytes:
    return f"modeem:connection:v{version}:{tenant_id}:{connection_id}".encode()


def encrypt_credentials(
    payload: dict[str, Any], *, tenant_id: uuid.UUID, connection_id: uuid.UUID
) -> tuple[bytes, int]:
    """Encrypt a credential payload; returns (nonce||ciphertext, version).

    Always encrypts with CURRENT_ENCRYPTION_VERSION; the returned version
    must be stored alongside the blob and supplied back at decryption time.
    """
    key = _load_key()
    nonce = os.urandom(_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(
        nonce, plaintext, _aad(CURRENT_ENCRYPTION_VERSION, tenant_id, connection_id)
    )
    return nonce + ciphertext, CURRENT_ENCRYPTION_VERSION


def decrypt_credentials(
    blob: bytes,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    encryption_version: int,
) -> dict[str, Any]:
    """Decrypt a credential payload. Trusted backend use only.

    The stored per-record ``encryption_version`` MUST be supplied explicitly;
    the AAD is built from it, never from the current global version, so
    bumping CURRENT_ENCRYPTION_VERSION later cannot break existing records.
    Must never be exposed through any API endpoint.
    """
    if encryption_version not in _SUPPORTED_VERSIONS:
        raise CredentialDecryptionError("Unsupported encryption version.")
    key = _load_key()
    if len(blob) <= _NONCE_BYTES:
        raise CredentialDecryptionError("Ciphertext too short.")
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(key).decrypt(
            nonce, ciphertext, _aad(encryption_version, tenant_id, connection_id)
        )
    except InvalidTag as exc:
        raise CredentialDecryptionError(
            "Credential ciphertext failed authentication."
        ) from exc
    return json.loads(plaintext.decode("utf-8"))
