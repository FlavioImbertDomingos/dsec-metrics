"""Run Alembic migrations from application code, without an ``alembic.ini``."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

SCRIPT_LOCATION = "dsec_metrics.db:migrations"


def alembic_config() -> Config:
    """Alembic configuration pointing at the migrations shipped in the package."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Upgrade the database to ``revision`` inside one transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
