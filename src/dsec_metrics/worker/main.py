"""Worker process.

In M0 the worker proves the plumbing: it waits for the database, then every
``worker_heartbeat_seconds`` it checks the database, purges expired sessions and old
sign-in failures, and touches a heartbeat file that the container health check reads.
Scheduling and collector runs arrive in M1.
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

from dsec_metrics.auth.sessions import purge_expired
from dsec_metrics.auth.throttle import purge_old_failures
from dsec_metrics.config import Settings, get_settings, validate_startup
from dsec_metrics.db.engine import make_engine, make_session_factory, ping, transaction
from dsec_metrics.logs import configure_logging

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
    run(settings, stop)
