from __future__ import annotations

import pytest

from dsec_metrics.auth.passwords import hash_password, needs_rehash, verify_password
from dsec_metrics.auth.users import PasswordPolicyError, check_password_policy


def test_hash_is_argon2id_and_verifies() -> None:
    encoded = hash_password("a long enough password")
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "a long enough password")
    assert not verify_password(encoded, "wrong password")
    assert not needs_rehash(encoded)


def test_same_password_hashes_differently() -> None:
    assert hash_password("same password here") != hash_password("same password here")


def test_missing_user_never_verifies() -> None:
    assert not verify_password(None, "dsec-metrics timing equaliser")
    assert not verify_password(None, "anything")


def test_garbage_hash_does_not_raise() -> None:
    assert not verify_password("not-a-hash", "anything")


def test_password_policy() -> None:
    check_password_policy("x" * 12)
    with pytest.raises(PasswordPolicyError):
        check_password_policy("x" * 11)
