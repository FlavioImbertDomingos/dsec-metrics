from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.auth.sessions import create_session
from dsec_metrics.auth.users import find_user
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import UserSession
from dsec_metrics.worker.main import heartbeat_age, run

pytestmark = pytest.mark.integration


def test_worker_heartbeat_and_purge(
    db_settings: Settings, session_factory: sessionmaker[Session], user: str
) -> None:
    now = datetime.now(UTC)
    with transaction(session_factory) as db:
        found = find_user(db, user)
        assert found is not None
        create_session(db, found, db_settings, now, "192.0.2.1")
        create_session(db, found, db_settings, now, "192.0.2.2")
    with transaction(session_factory) as db:
        first = db.scalars(select(UserSession.id)).first()
        db.execute(
            update(UserSession)
            .where(UserSession.id == first)
            .values(expires_at=now - timedelta(minutes=1))
        )

    db_settings.worker_heartbeat_file.unlink(missing_ok=True)
    assert heartbeat_age(db_settings.worker_heartbeat_file) is None
    ticks = run(db_settings, threading.Event(), max_ticks=1)
    assert ticks == 1
    age = heartbeat_age(db_settings.worker_heartbeat_file)
    assert age is not None
    assert age < 5
    with session_factory() as db:
        assert len(db.scalars(select(UserSession)).all()) == 1


def test_worker_stops_on_event(db_settings: Settings) -> None:
    stop = threading.Event()
    thread = threading.Thread(target=run, args=(db_settings, stop))
    thread.start()
    time.sleep(0.3)
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_worker_survives_database_outage(db_settings: Settings) -> None:
    broken = db_settings.model_copy(update={"db_port": 1})
    assert run(broken, threading.Event(), max_ticks=2) == 2
