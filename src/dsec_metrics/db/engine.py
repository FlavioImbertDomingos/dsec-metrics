"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.config import Settings


def make_engine(settings: Settings) -> Engine:
    """Create the process-wide engine. ``pool_pre_ping`` survives database restarts."""
    return create_engine(
        settings.database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 5, "application_name": "dsec-metrics"},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions do not expire objects on commit, so returned models stay readable."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Open a session, commit on success, roll back on error."""
    with factory() as session, session.begin():
        yield session


def ping(engine: Engine) -> None:
    """Raise if the database is unreachable."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
