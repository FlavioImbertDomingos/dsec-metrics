from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.config import Settings, get_settings
from dsec_metrics.content import load_content
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import ScheduleRow
from dsec_metrics.worker.jobs import JOBS
from dsec_metrics.worker.scheduler import claim_due, run_due, run_scheduler, sync_schedules
from tests.conftest import CONTENT_DIR

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(db_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for k, v in {
        "DSEC_MODE": "development",
        "DSEC_PUBLIC_ORIGIN": db_settings.public_origin,
        "DSEC_DB_HOST": db_settings.db_host,
        "DSEC_DB_PORT": str(db_settings.db_port),
        "DSEC_DB_PASSWORD": "dsec",
        "DSEC_DB_SSLMODE": "disable",
        "DSEC_CONTENT_DIR": str(CONTENT_DIR),
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def synced(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as db:
        assert sync_schedules(db, load_content(CONTENT_DIR), NOW) == ["collect:sample"]


def make_due(factory: sessionmaker[Session], **values: Any) -> None:
    with transaction(factory) as db:
        db.execute(update(ScheduleRow).values(next_run_at=NOW - timedelta(days=3), **values))


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, str]] = []
        self.fail = fail

    def __call__(self, **kwargs: str) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("boom")
        return {"runs": 1}


def test_sync_creates_keeps_updates_and_removes(session_factory: sessionmaker[Session]) -> None:
    synced(session_factory)
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.job == "collect"
        assert row.args == {"instance_id": "sample"}
        assert row.next_run_at == datetime(2026, 9, 27, 2, 5, tzinfo=UTC)

    content = load_content(CONTENT_DIR)
    with transaction(session_factory) as db:
        sync_schedules(db, content, NOW + timedelta(hours=1))
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.next_run_at == datetime(2026, 9, 27, 2, 5, tzinfo=UTC)  # unchanged

    inst = content.collectors["sample"]
    content.collectors["sample"] = inst.model_copy(update={"schedule": "0 * * * *"})
    with transaction(session_factory) as db:
        sync_schedules(db, content, NOW)
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.next_run_at == datetime(2026, 9, 26, 11, 0, tzinfo=UTC)

    content.collectors["sample"] = inst.model_copy(update={"schedule": None})
    with transaction(session_factory) as db:
        assert sync_schedules(db, content, NOW) == []
    with session_factory() as db:
        assert db.get(ScheduleRow, "collect:sample") is None


def test_due_schedule_runs_once_and_advances(session_factory: sessionmaker[Session]) -> None:
    synced(session_factory)
    make_due(session_factory)
    job = Recorder()
    assert run_due(session_factory, {"collect": job}, clock=lambda: NOW) == [
        ("collect:sample", "succeeded")
    ]
    # Three missed days run once, not three times.
    assert job.calls == [{"instance_id": "sample"}]
    assert run_due(session_factory, {"collect": job}, clock=lambda: NOW) == []
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.last_status == "succeeded"
        assert row.last_error is None
        assert row.next_run_at == datetime(2026, 9, 27, 2, 5, tzinfo=UTC)


def test_failures_are_recorded(session_factory: sessionmaker[Session]) -> None:
    synced(session_factory)
    make_due(session_factory)
    assert run_due(session_factory, {"collect": Recorder(fail=True)}, clock=lambda: NOW) == [
        ("collect:sample", "failed")
    ]
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.last_status == "failed"
        assert row.last_error == "RuntimeError"

    make_due(session_factory)
    assert run_due(session_factory, {}, clock=lambda: NOW) == [("collect:sample", "failed")]
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.last_error == "unknown job 'collect'"


@pytest.mark.parametrize(
    ("values", "error", "next_run"),
    [
        # A broken expression can never be scheduled again, so it is parked a century out.
        (
            {"cron": "not a cron"},
            "invalid cron expression",
            datetime(2126, 9, 26, 10, 0, tzinfo=UTC),
        ),
        # Bad arguments fail at each fire time until someone fixes the row.
        (
            {"args": {"instance_id": ["x"]}},
            "arguments must be strings",
            datetime(2026, 9, 27, 2, 5, tzinfo=UTC),
        ),
    ],
)
def test_hand_edited_rows_do_not_run(
    session_factory: sessionmaker[Session],
    values: dict[str, Any],
    error: str,
    next_run: datetime,
) -> None:
    synced(session_factory)
    make_due(session_factory, **values)
    job = Recorder()
    assert run_due(session_factory, {"collect": job}, clock=lambda: NOW) == []
    assert job.calls == []
    with session_factory() as db:
        row = db.get(ScheduleRow, "collect:sample")
        assert row is not None
        assert row.last_status == "failed"
        assert row.last_error == error
        assert row.next_run_at == next_run


def test_a_claimed_schedule_is_skipped_by_other_workers(
    session_factory: sessionmaker[Session],
) -> None:
    synced(session_factory)
    make_due(session_factory)
    with session_factory() as first, first.begin():
        assert claim_due(first, NOW) is not None
        with session_factory() as second, second.begin():
            assert claim_due(second, NOW) is None


def test_run_scheduler_stops_and_survives_errors(session_factory: sessionmaker[Session]) -> None:
    stop = threading.Event()

    class Broken(dict[str, Any]):
        def get(self, *_: object, **__: object) -> Any:
            stop.set()
            raise RuntimeError("registry broken")

    synced(session_factory)
    make_due(session_factory)
    run_scheduler(session_factory, Broken(), stop, poll_seconds=0.01)
    assert stop.is_set()


def test_collect_job_runs_the_sample_instance(
    session_factory: sessionmaker[Session], env: None
) -> None:
    result = JOBS["collect"](instance_id="sample")
    assert result == {"runs": 14, "failed_runs": 0, "measurements": result["measurements"]}
    assert result["measurements"] > 16
