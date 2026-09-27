"""Server-side sessions stored in Postgres."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dsec_metrics.auth.tokens import new_token, token_hash
from dsec_metrics.config import Settings
from dsec_metrics.db.models import User, UserSession

COOKIE_NAME = "__Host-dsec_session"
TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """What the caller needs to set the cookie. The token exists only here."""

    token: str
    csrf_token: str
    expires_at: datetime


def create_session(
    db: Session, user: User, settings: Settings, now: datetime, source_address: str | None
) -> IssuedSession:
    """Create a session row and return the one-time token for the cookie."""
    token = new_token()
    csrf = new_token()
    expires_at = now + timedelta(hours=settings.session_absolute_hours)
    db.add(
        UserSession(
            token_hash=token_hash(token),
            csrf_token=csrf,
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            source_address=source_address,
        )
    )
    return IssuedSession(token=token, csrf_token=csrf, expires_at=expires_at)


def load_session(db: Session, token: str, settings: Settings, now: datetime) -> UserSession | None:
    """Return the live session for a cookie token, or ``None``.

    A session ends at its absolute expiry or after the idle timeout, whichever comes
    first. Expired rows are deleted when found. ``last_seen_at`` is updated at most once
    a minute to keep writes down.
    """
    try:
        digest = token_hash(token)
    except UnicodeEncodeError:
        return None
    row = db.scalars(select(UserSession).where(UserSession.token_hash == digest)).first()
    if row is None:
        return None
    idle_limit = row.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if now >= row.expires_at or now >= idle_limit or not row.user.is_active:
        db.delete(row)
        return None
    if now - row.last_seen_at >= TOUCH_INTERVAL:
        row.last_seen_at = now
    return row


def end_session(db: Session, session_id: object) -> None:
    """Delete one session."""
    db.execute(delete(UserSession).where(UserSession.id == session_id))


def purge_expired(db: Session, now: datetime) -> int:
    """Delete sessions past their absolute expiry. Returns the number removed."""
    result = db.execute(delete(UserSession).where(UserSession.expires_at <= now))
    return int(getattr(result, "rowcount", 0) or 0)
