"""A small Postgres-backed scheduler for the worker.

Each row in ``schedules`` names a job from the fixed ``JOBS`` registry, its JSON string
arguments and a cron expression. Workers claim due rows with ``SELECT ... FOR UPDATE SKIP
LOCKED``, move ``next_run_at`` forward in the same transaction, then run the job. So two
worker replicas never run the same fire time twice, and a missed fire time (the worker was
down) runs once when the worker comes back rather than once per missed slot.

Nothing read from the table is imported, unpickled or turned into objects: the job name is
looked up in a dict and the arguments must be a flat mapping of strings. ADR-0007 explains
why this replaced APScheduler.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.content import Content
from dsec_metrics.core.cron import CronError, parse_cron
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import ScheduleRow

log = logging.getLogger(__name__)

Job = Callable[..., Mapping[str, Any]]
Clock = Callable[[], datetime]
COLLECT = "collect"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Claimed:
    """A due schedule that this worker now owns for one run."""

    id: str
    job: str
    args: dict[str, str]


def desired_schedules(content: Content) -> dict[str, tuple[str, dict[str, str], str]]:
    """Schedule id -> (job, args, cron) for every collector instance with a schedule."""
    wanted: dict[str, tuple[str, dict[str, str], str]] = {}
    for instance in content.collectors.values():
        if instance.schedule:
            wanted[f"{COLLECT}:{instance.id}"] = (
                COLLECT,
                {"instance_id": instance.id},
                instance.schedule,
            )
    return wanted


def sync_schedules(db: Session, content: Content, now: datetime) -> list[str]:
    """Make the table match the content. New or changed schedules get a fresh
    ``next_run_at``; unchanged ones keep theirs. Returns the schedule ids."""
    wanted = desired_schedules(content)
    db.execute(delete(ScheduleRow).where(ScheduleRow.id.not_in(list(wanted))))
    for sid, (job, args, cron) in sorted(wanted.items()):
        row = db.get(ScheduleRow, sid)
        if row is None:
            row = ScheduleRow(id=sid)
            db.add(row)
        if row.cron != cron or row.job != job or row.args != args:
            row.job, row.args, row.cron = job, args, cron
            row.next_run_at = parse_cron(cron).next_after(now)
            row.updated_at = now
    db.flush()
    return sorted(wanted)


def claim_due(db: Session, now: datetime) -> Claimed | None:
    """Lock the most overdue schedule, advance it past ``now`` and return it. Rows that
    cannot run (only possible after a hand edit of the table) are marked failed; one
    with a broken cron expression is parked a century ahead."""
    while True:
        row = db.scalars(
            select(ScheduleRow)
            .where(ScheduleRow.next_run_at <= now)
            .order_by(ScheduleRow.next_run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if row is None:
            return None
        row.last_started_at = now
        args = row.args if isinstance(row.args, dict) else None
        try:
            row.next_run_at = parse_cron(row.cron).next_after(now)
        except CronError:
            row.next_run_at = now.replace(year=now.year + 100)
            row.last_status, row.last_error = "failed", "invalid cron expression"
            continue
        if args is None or not all(isinstance(v, str) for v in args.values()):
            row.last_status, row.last_error = "failed", "arguments must be strings"
            continue
        row.last_status = "running"
        return Claimed(row.id, row.job, {str(k): str(v) for k, v in args.items()})


def finish(db: Session, schedule_id: str, now: datetime, error: str | None) -> None:
    """Record the outcome of a run."""
    row = db.get(ScheduleRow, schedule_id)
    if row is not None:
        row.last_finished_at = now
        row.last_status = "failed" if error else "succeeded"
        row.last_error = error[:2000] if error else None


def run_due(
    factory: sessionmaker[Session], jobs: Mapping[str, Job], clock: Clock = _now
) -> list[tuple[str, str]]:
    """Run every schedule that is due now. Returns (schedule id, status) pairs."""
    done: list[tuple[str, str]] = []
    while True:
        with transaction(factory) as db:
            claimed = claim_due(db, clock())
        if claimed is None:
            return done
        error: str | None = None
        job = jobs.get(claimed.job)
        if job is None:
            error = f"unknown job {claimed.job!r}"
        else:
            try:
                result = job(**claimed.args)
                log.info(
                    "scheduled job finished",
                    extra={"event": "job_finished", "schedule": claimed.id, **dict(result)},
                )
            except Exception as exc:  # a job failure must not stop the scheduler
                error = type(exc).__name__
                log.exception(
                    "scheduled job failed",
                    extra={"event": "job_failed", "schedule": claimed.id},
                )
        with transaction(factory) as db:
            finish(db, claimed.id, clock(), error)
        done.append((claimed.id, "failed" if error else "succeeded"))


def run_scheduler(
    factory: sessionmaker[Session],
    jobs: Mapping[str, Job],
    stop: threading.Event,
    poll_seconds: float,
) -> None:
    """Poll for due schedules until ``stop`` is set."""
    while not stop.is_set():
        try:
            run_due(factory, jobs)
        except Exception:  # database outage and similar: log, wait, retry
            log.exception("scheduler poll failed", extra={"event": "scheduler_error"})
        stop.wait(poll_seconds)
