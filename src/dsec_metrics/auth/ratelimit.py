"""Fixed-window request counters in Postgres (ADR-0001 rules out Redis).

Each request increments one row per key for the current minute with a single upsert.
Session keys use a hash of the cookie, never the cookie itself.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dsec_metrics.db.models import RateLimitWindow

WINDOW = timedelta(minutes=1)
KEEP = timedelta(minutes=10)


def window_start(now: datetime) -> datetime:
    """Start of the one-minute window that contains ``now``."""
    return now.replace(second=0, microsecond=0)


def address_key(address: str) -> str:
    """Counter key for a client address."""
    return f"a:{address[:64]}"


def session_key(cookie: str) -> str:
    """Counter key for a session cookie. The cookie value is hashed, not stored."""
    return "s:" + hashlib.sha256(cookie.encode("utf-8")).hexdigest()[:40]


def count_request(db: Session, keys: list[str], now: datetime) -> dict[str, int]:
    """Add one to each key's counter for the current window and return the new counts."""
    start = window_start(now)
    values = [{"key": key, "window_start": start, "count": 1} for key in keys]
    stmt = (
        insert(RateLimitWindow)
        .values(values)
        .on_conflict_do_update(
            index_elements=["key", "window_start"],
            set_={"count": RateLimitWindow.count + 1},
        )
        .returning(RateLimitWindow.key, RateLimitWindow.count)
    )
    return dict(db.execute(stmt).tuples().all())


def purge_old_windows(db: Session, now: datetime) -> None:
    """Drop counters for windows that ended a while ago."""
    db.execute(delete(RateLimitWindow).where(RateLimitWindow.window_start < now - KEEP))
