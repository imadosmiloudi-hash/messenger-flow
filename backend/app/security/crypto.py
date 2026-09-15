"""Fernet encrypt/decrypt for OAuth tokens at rest. Key derived from SECRET_KEY."""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)

# Fernet tokens are urlsafe-base64 and typically start with gAAAAA (version 0x80)
_FERNET_PREFIX = "gAAAAA"


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _require_secret() -> str:
    settings = get_settings()
    secret = (settings.secret_key or "").strip()
    weak = {"", "change-me-to-a-long-random-string", "changeme", "secret"}
    if not secret or secret.lower() in weak:
        if settings.app_env not in ("development", "test"):
            raise RuntimeError(
                "SECRET_KEY must be set to a strong value for token encryption in production"
            )
        # Dev/test: still derive so roundtrips work, but log once
        if not secret:
            secret = "dev-only-insecure-secret-key-do-not-use-in-prod"
    return secret


def get_fernet() -> Fernet:
    return Fernet(_derive_fernet_key(_require_secret()))


def encrypt_str(plaintext: str) -> str:
    """Encrypt a string; empty input returns empty string."""
    if plaintext is None or plaintext == "":
        return ""
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_str(ciphertext: str) -> str:
    """Decrypt a Fernet token string. Raises ValueError on failure."""
    if ciphertext is None or ciphertext == "":
        return ""
    try:
        return get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid encrypted token") from exc


def looks_encrypted(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith(_FERNET_PREFIX)


def decrypt_maybe(value: str | None) -> str:
    """Decrypt if Fernet-looking; otherwise return plaintext (legacy tokens)."""
    if not value:
        return ""
    if looks_encrypted(value):
        try:
            return decrypt_str(value)
        except ValueError:
            logger.warning("decrypt_maybe: Fernet-looking value failed to decrypt; treating as opaque")
            return value
    return value
