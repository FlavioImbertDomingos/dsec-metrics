"""Sign-in throttling by username and by source address, stored in Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from dsec_metrics.config import Settings
from dsec_metrics.db.models import AuthFailure


def is_throttled(
    db: Session, username: str, source_address: str, settings: Settings, now: datetime
) -> bool:
    """True when either the username or the source has too many recent failures."""
    since = now - timedelta(minutes=settings.login_window_minutes)
    recent = AuthFailure.occurred_at > since
    by_user = db.scalar(select(func.count()).where(recent, AuthFailure.username == username))
    if (by_user or 0) >= settings.login_max_failures_per_user:
        return True
    by_source = db.scalar(
        select(func.count()).where(recent, AuthFailure.source_address == source_address)
    )
    return (by_source or 0) >= settings.login_max_failures_per_source


def record_failure(db: Session, username: str, source_address: str, now: datetime) -> None:
    """Remember one failed attempt."""
    db.add(AuthFailure(username=username, source_address=source_address, occurred_at=now))


def clear_failures(db: Session, username: str) -> None:
    """Forget failures for a user after a successful sign-in."""
    db.execute(delete(AuthFailure).where(AuthFailure.username == username))


def purge_old_failures(db: Session, settings: Settings, now: datetime) -> None:
    """Drop failures older than the window."""
    since = now - timedelta(minutes=settings.login_window_minutes)
    db.execute(delete(AuthFailure).where(AuthFailure.occurred_at <= since))
