"""The hash-chained audit log.

Each entry stores the hash of the entry before it. The hash covers the sequence number,
time, actor, action, target, details and previous hash, as canonical JSON. Changing,
deleting, inserting or reordering any entry breaks the chain at that point, and
:func:`verify_chain` reports where.

Appends take a transaction-level advisory lock, so API and worker processes writing at
the same time still produce one linear chain. A database trigger rejects UPDATE,
DELETE and TRUNCATE (migration 0004). Every entry is also logged as a JSON line for the
SIEM.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from dsec_metrics.core.canonical import canonical_json, sha256_hex
from dsec_metrics.db.models import AuditEvent

log = logging.getLogger("dsec_metrics.audit")

GENESIS = "0" * 64
# Arbitrary constant key for pg_advisory_xact_lock: "dsec" in ASCII.
LOCK_KEY = 0x64736563


def entry_hash(
    seq: int,
    occurred_at: datetime,
    actor: str,
    action: str,
    target: str,
    details: Mapping[str, Any],
    prev_hash: str,
) -> str:
    """SHA-256 of the canonical JSON of an entry's fields."""
    return sha256_hex(
        canonical_json(
            {
                "seq": seq,
                "occurred_at": occurred_at.astimezone(UTC).isoformat(),
                "actor": actor,
                "action": action,
                "target": target,
                "details": dict(details),
                "prev_hash": prev_hash,
            }
        )
    )


def record(
    db: Session,
    actor: str,
    action: str,
    target: str = "",
    details: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> AuditEvent:
    """Append an entry in the caller's transaction. It is durable when that commits."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
    last = db.execute(
        select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
    ).first()
    seq = (last.seq if last else 0) + 1
    prev = last.hash if last else GENESIS
    # Microseconds are dropped so the time round-trips exactly through Postgres and JSON.
    when = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    body = dict(details or {})
    event = AuditEvent(
        seq=seq,
        occurred_at=when,
        actor=actor[:128],
        action=action[:64],
        target=target[:256],
        details=body,
        prev_hash=prev,
        hash=entry_hash(seq, when, actor[:128], action[:64], target[:256], body, prev),
    )
    db.add(event)
    db.flush()
    log.info(
        action,
        extra={
            "event": "audit",
            "audit_seq": seq,
            "actor": event.actor,
            "action": event.action,
            "target": event.target,
            "audit_hash": event.hash,
        },
    )
    return event


@dataclass(frozen=True)
class ChainResult:
    """Outcome of a chain check. ``broken_at`` is the first sequence number that fails."""

    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None
    head: str = GENESIS


def verify_chain(db: Session, batch: int = 5000) -> ChainResult:
    """Recompute every hash in order and stop at the first broken link."""
    expected_seq = 1
    prev = GENESIS
    checked = 0
    last_seq = 0
    while True:
        rows = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.seq > last_seq)
            .order_by(AuditEvent.seq)
            .limit(batch)
        ).all()
        if not rows:
            return ChainResult(ok=True, checked=checked, head=prev)
        for row in rows:
            if row.seq != expected_seq:
                return ChainResult(
                    False, checked, expected_seq, f"entry {expected_seq} is missing", prev
                )
            if row.prev_hash != prev:
                return ChainResult(
                    False, checked, row.seq, "previous-hash link does not match", prev
                )
            recomputed = entry_hash(
                row.seq,
                row.occurred_at,
                row.actor,
                row.action,
                row.target,
                row.details,
                row.prev_hash,
            )
            if recomputed != row.hash:
                return ChainResult(
                    False, checked, row.seq, "contents do not match the stored hash", prev
                )
            prev = row.hash
            expected_seq += 1
            checked += 1
            last_seq = row.seq
        db.expunge_all()


def count(db: Session) -> int:
    """Number of entries."""
    return int(db.scalar(select(func.count()).select_from(AuditEvent)) or 0)
