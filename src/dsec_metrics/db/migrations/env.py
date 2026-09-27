"""Alembic environment.

The application runs migrations through :func:`dsec_metrics.db.migrate.upgrade`, which
passes an open connection in ``config.attributes``. Running ``alembic`` by hand in a
development checkout builds the connection from the ``DSEC_*`` settings instead.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from dsec_metrics.config import Settings
from dsec_metrics.db.engine import make_engine
from dsec_metrics.db.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live connection."""
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        _run(connection)
        return
    engine = make_engine(Settings())
    with engine.connect() as conn:
        _run(conn)
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported")
run_migrations_online()
