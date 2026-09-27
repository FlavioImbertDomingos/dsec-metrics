from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import Engine, inspect

from dsec_metrics.db.migrate import alembic_config, upgrade

pytestmark = pytest.mark.integration


def test_upgrade_is_idempotent_and_reversible(engine: Engine) -> None:
    upgrade(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"users", "sessions", "auth_failures", "alembic_version"} <= tables

    config = alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

    upgrade(engine)
    assert {"users", "sessions", "auth_failures"} <= set(inspect(engine).get_table_names())
