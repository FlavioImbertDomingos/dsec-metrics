"""M1 acceptance: ``dsec-metrics demo`` then ``dsec-metrics status``."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from dsec_metrics.cli.main import app
from dsec_metrics.config import Settings, get_settings
from tests.conftest import CONTENT_DIR

pytestmark = pytest.mark.integration
runner = CliRunner()


@pytest.fixture
def env(
    db_settings: Settings, monkeypatch: pytest.MonkeyPatch, session_factory: object
) -> Iterator[None]:
    values = {
        "DSEC_MODE": "development",
        "DSEC_PUBLIC_ORIGIN": db_settings.public_origin,
        "DSEC_DB_HOST": db_settings.db_host,
        "DSEC_DB_PORT": str(db_settings.db_port),
        "DSEC_DB_PASSWORD": "dsec",
        "DSEC_DB_SSLMODE": "disable",
        "DSEC_CONTENT_DIR": str(CONTENT_DIR),
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_validate_needs_no_database() -> None:
    result = runner.invoke(app, ["validate", "--content", str(CONTENT_DIR)])
    assert result.exit_code == 0, result.output
    assert "16 metrics, 40 controls, 3 dashboards" in result.stdout


def test_demo_then_status(env: None) -> None:
    demo = runner.invoke(app, ["demo", "--months", "3"])
    assert demo.exit_code == 0, demo.output
    assert "2026-07-31: 14 collections (0 failed)" in demo.stdout
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0, status.output
    rows = [line for line in status.stdout.splitlines()[1:] if line.strip()]
    assert len(rows) == 16
    for row in rows:
        assert re.search(r"\b(green|amber|red)\b", row), row
        assert "2026-09-30" in row
    assert re.search(r"KRI-06\s+XX red\s+7\s", status.stdout)
    earlier = runner.invoke(app, ["status", "--as-of", "2026-08-31"])
    assert "2026-08-31" in earlier.stdout


def test_collect_and_evaluate_commands(env: None) -> None:
    collected = runner.invoke(
        app, ["collect", "sample", "card_data_scans", "--as-of", "2026-09-30"]
    )
    assert collected.exit_code == 0, collected.output
    assert "card numbers masked" in collected.stdout
    evaluated = runner.invoke(app, ["evaluate", "--metric", "KRI-07", "--as-of", "2026-09-30"])
    assert evaluated.exit_code == 0, evaluated.output
    assert "new measurement" in evaluated.stdout
    bad = runner.invoke(app, ["evaluate", "--metric", "NOPE-01"])
    assert bad.exit_code == 1
    assert runner.invoke(app, ["collect", "nope", "x"]).exit_code == 1
    assert runner.invoke(app, ["collect", "sample", "x", "--as-of", "yesterday"]).exit_code == 1
