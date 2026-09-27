"""Development-mode local accounts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dsec_metrics.auth.passwords import hash_password, verify_password
from dsec_metrics.db.models import User

MIN_PASSWORD_LENGTH = 12


class PasswordPolicyError(ValueError):
    """The password does not meet the minimum policy."""


def check_password_policy(password: str) -> None:
    """Minimum length only; development accounts never reach production."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")


def find_user(db: Session, username: str) -> User | None:
    """Look a user up by exact username."""
    return db.scalars(select(User).where(User.username == username)).first()


def ensure_local_user(
    db: Session,
    username: str,
    password: str,
    display_name: str,
    roles: tuple[str, ...] = ("viewer",),
) -> bool:
    """Create the user, or reset its password if it changed, and set its roles.
    Returns True if created."""
    check_password_policy(password)
    user = find_user(db, username)
    if user is None:
        db.add(
            User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                is_active=True,
                roles=sorted(set(roles)),
            )
        )
        db.flush()
        return True
    if not verify_password(user.password_hash, password):
        user.password_hash = hash_password(password)
    user.roles = sorted(set(roles))
    return False
