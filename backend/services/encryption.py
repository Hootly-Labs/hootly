"""Symmetric encryption for sensitive fields stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
The encryption key is derived from the ENCRYPTION_KEY env var.
If ENCRYPTION_KEY is not set, falls back to a deterministic key derived
from JWT_SECRET so existing deployments don't break — but a dedicated
ENCRYPTION_KEY should be set in production.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

_logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
_JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary string."""
    raw = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw)


if _ENCRYPTION_KEY:
    _fernet = Fernet(_derive_key(_ENCRYPTION_KEY))
else:
    _logger.warning(
        "ENCRYPTION_KEY not set — deriving from JWT_SECRET. "
        "Set a dedicated ENCRYPTION_KEY env var in production."
    )
    _fernet = Fernet(_derive_key(_JWT_SECRET))


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a URL-safe base64-encoded ciphertext."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """Decrypt a ciphertext string. Returns None if decryption fails
    (e.g. wrong key, corrupted data, or plaintext from before encryption was added)."""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
