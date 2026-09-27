from __future__ import annotations

import threading
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics import audit
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import AuditEvent

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def fill(factory: sessionmaker[Session], n: int = 5) -> None:
    with transaction(factory) as db:
        for i in range(n):
            audit.record(db, "tester", "test.event", f"thing:{i}", {"i": i}, now=T0)


def tamper(engine: Engine, sql: str) -> None:
    """Change the table behind the trigger's back, as someone with database access could."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        conn.execute(text(sql))
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))


def check(factory: sessionmaker[Session]) -> audit.ChainResult:
    with factory() as db:
        return audit.verify_chain(db, batch=2)


def test_chain_links_every_entry(session_factory: sessionmaker[Session]) -> None:
    assert check(session_factory) == audit.ChainResult(ok=True, checked=0)
    fill(session_factory)
    result = check(session_factory)
    assert result.ok
    assert result.checked == 5
    with session_factory() as db:
        rows = db.query(AuditEvent).order_by(AuditEvent.seq).all()
        assert rows[0].prev_hash == audit.GENESIS
        assert all(b.prev_hash == a.hash for a, b in pairwise(rows))
        assert result.head == rows[-1].hash
        assert audit.count(db) == 5


@pytest.mark.parametrize(
    ("sql", "broken_at", "reason"),
    [
        ("UPDATE audit_events SET details = '{\"i\": 99}' WHERE seq = 3", 3, "contents"),
        ("UPDATE audit_events SET actor = 'someone-else' WHERE seq = 1", 1, "contents"),
        ("DELETE FROM audit_events WHERE seq = 2", 2, "missing"),
        (
            "UPDATE audit_events SET seq = -2 WHERE seq = 2;"
            " UPDATE audit_events SET seq = 2 WHERE seq = 4;"
            " UPDATE audit_events SET seq = 4 WHERE seq = -2",
            2,
            "previous-hash",
        ),
        ("UPDATE audit_events SET hash = repeat('a', 64) WHERE seq = 5", 5, "contents"),
    ],
    ids=["edit", "actor", "delete", "reorder", "rehash"],
)
def test_tampering_is_detected_and_located(
    session_factory: sessionmaker[Session], engine: Engine, sql: str, broken_at: int, reason: str
) -> None:
    fill(session_factory)
    tamper(engine, sql)
    result = check(session_factory)
    assert not result.ok
    assert result.broken_at == broken_at
    assert reason in (result.reason or "")
    assert result.checked == broken_at - 1


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_events SET actor = 'x'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_the_table_is_append_only(
    session_factory: sessionmaker[Session], engine: Engine, sql: str
) -> None:
    fill(session_factory, 1)
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
        conn.execute(text(sql))


def test_concurrent_writers_keep_one_chain(session_factory: sessionmaker[Session]) -> None:
    def write(worker: int) -> None:
        for i in range(10):
            with transaction(session_factory) as db:
                audit.record(db, f"worker-{worker}", "test.event", f"thing:{i}")

    threads = [threading.Thread(target=write, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = check(session_factory)
    assert result.ok
    assert result.checked == 40
