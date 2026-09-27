"""Worker process.

Two things run here. The scheduler (in a background thread) runs each collector instance on
its cron schedule and re-evaluates the metrics that read from it. The main loop checks
the database every ``worker_heartbeat_seconds``, purges expired sessions, old sign-in
failures and old rate-limit counters, and touches the heartbeat file that the container
health check reads.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from sqlalchemy.exc import SQLAlchemyError

from dsec_metrics.auth.ratelimit import purge_old_windows
from dsec_metrics.auth.sessions import purge_expired
from dsec_metrics.auth.throttle import purge_old_failures
from dsec_metrics.config import Settings, get_settings, validate_startup
from dsec_metrics.content import cross_check, load_content
from dsec_metrics.db.engine import make_engine, make_session_factory, ping, transaction
from dsec_metrics.logs import configure_logging
from dsec_metrics.pipeline import instance_queries, sync_definitions
from dsec_metrics.worker.jobs import JOBS
from dsec_metrics.worker.scheduler import run_scheduler, sync_schedules

log = logging.getLogger(__name__)


def touch(path: Path) -> None:
    """Create the heartbeat file or update its modification time."""
    path.touch(exist_ok=True)


def heartbeat_age(path: Path, now: float | None = None) -> float | None:
    """Seconds since the last heartbeat, or ``None`` if there has been none."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    return (now if now is not None else time.time()) - mtime


def run(settings: Settings, stop: threading.Event, max_ticks: int | None = None) -> int:
    """Run the heartbeat loop until ``stop`` is set. Returns the number of ticks."""
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    ticks = 0
    try:
        while not stop.is_set():
            try:
                ping(engine)
                with transaction(factory) as db:
                    now = datetime.now(UTC)
                    removed = purge_expired(db, now)
                    purge_old_failures(db, settings, now)
                    purge_old_windows(db, now)
                touch(settings.worker_heartbeat_file)
                log.info("worker heartbeat", extra={"event": "worker_heartbeat", "purged": removed})
            except SQLAlchemyError as exc:
                log.warning(
                    "database unavailable",
                    extra={"event": "worker_db_unavailable", "error": type(exc).__name__},
                )
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            stop.wait(settings.worker_heartbeat_seconds)
    finally:
        engine.dispose()
    return ticks


def main() -> None:
    """Entry point: configure logging, install signal handlers, run."""
    settings = get_settings()
    configure_logging(settings.log_level)
    validate_startup(settings)
    stop = threading.Event()

    def _handle(signum: int, _frame: FrameType | None) -> None:
        log.info("worker stopping", extra={"event": "worker_stop", "signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    log.info("worker starting", extra={"event": "worker_start", "mode": settings.mode.value})
    content = load_content(settings.content_dir)
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    try:
        problems = [*content.problems, *cross_check(content, instance_queries)]
        if not problems:
            with transaction(factory) as db:
                sync_definitions(db, content)
                ids = sync_schedules(db, content, datetime.now(UTC))
            log.info("schedules registered", extra={"event": "schedules", "schedules": ids})
        else:
            log.error(
                "content is invalid; definitions and schedules left as they were",
                extra={"event": "content_invalid", "problems": len(problems)},
            )
        scheduler = threading.Thread(
            target=run_scheduler,
            args=(factory, JOBS, stop, settings.scheduler_poll_seconds),
            name="scheduler",
            daemon=True,
        )
        scheduler.start()
        run(settings, stop)
        scheduler.join(timeout=settings.scheduler_poll_seconds)
    finally:
        engine.dispose()
