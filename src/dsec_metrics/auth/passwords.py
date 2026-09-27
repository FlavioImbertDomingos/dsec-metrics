"""Argon2id password hashing for development-mode local accounts."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults follow RFC 9106's second recommended option:
# Argon2id, t=3, m=64 MiB, p=4.
_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an encoded Argon2id hash."""
    return _HASHER.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    """Check a password in roughly constant time, even when the user does not exist.

    Pass ``None`` for ``encoded`` when there is no such user; a dummy hash is checked so
    the response time does not reveal which usernames exist.
    """
    target = encoded if encoded is not None else _dummy_hash()
    try:
        ok = _HASHER.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and encoded is not None


def needs_rehash(encoded: str) -> bool:
    """True when the stored hash uses weaker parameters than the current ones."""
    return _HASHER.check_needs_rehash(encoded)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash("dsec-metrics timing equaliser")
