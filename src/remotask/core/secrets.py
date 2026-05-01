"""Secret generation, masking, and key classification."""
from __future__ import annotations

import secrets as _stdlib_secrets

SECRET_KEYS: frozenset[str] = frozenset(
    {
        "daemon.auth_token",
        "telegram.bot_token",
    }
)

_TOKEN_BYTES = 32  # → ≥ 43 url-safe chars
_MASK_PREFIX = "****"


def generate_token() -> str:
    """Return a cryptographically strong url-safe token (≥ 32 chars)."""
    return _stdlib_secrets.token_urlsafe(_TOKEN_BYTES)


def mask(value: str | None) -> str:
    """Mask a secret to ``****<last4>`` form. Short/empty/None → ``****``."""
    if not value or len(value) < 4:
        return _MASK_PREFIX
    return f"{_MASK_PREFIX}{value[-4:]}"


def is_secret_key(dotted_key: str) -> bool:
    """Whether the dotted config key references a secret value."""
    return dotted_key in SECRET_KEYS
