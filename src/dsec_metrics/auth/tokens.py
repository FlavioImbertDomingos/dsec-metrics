"""Random tokens and their hashes."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    """A URL-safe random token with 256 bits of entropy."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    """SHA-256 of a token. The database stores this, never the token itself."""
    return hashlib.sha256(token.encode("ascii", errors="strict")).digest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison."""
    return hmac.compare_digest(a.encode(), b.encode())
