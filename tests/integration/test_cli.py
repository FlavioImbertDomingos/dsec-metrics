from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dsec_metrics import __version__
from dsec_metrics.auth.passwords import verify_password
from dsec_metrics.auth.users import find_user
from dsec_metrics.cli.main import app
from dsec_metrics.config import Settings, get_settings

pytestmark = pytest.mark.integration
runner = CliRunner()


@pytest.fixture
def env(db_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    values = {
        "DSEC_MODE": "development",
        "DSEC_LOCAL_ACCOUNTS": "true",
        "DSEC_PUBLIC_ORIGIN": db_settings.public_origin,
        "DSEC_DB_HOST": db_settings.db_host,
        "DSEC_DB_PORT": str(db_settings.db_port),
        "DSEC_DB_PASSWORD": "dsec",
        "DSEC_DB_SSLMODE": "disable",
        "DSEC_WORKER_HEARTBEAT_FILE": str(db_settings.worker_heartbeat_file),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_bootstrap_creates_dev_admin(
    env: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("a dev admin password\n", encoding="utf-8")
    monkeypatch.setenv("DSEC_DEV_ADMIN_PASSWORD_FILE", str(secret))
    get_settings.cache_clear()

    first = runner.invoke(app, ["bootstrap"])
    assert first.exit_code == 0, first.output
    assert "dev user dev-admin created" in first.stdout
    second = runner.invoke(app, ["bootstrap"])
    assert "up to date" in second.stdout

    with session_factory() as db:
        user = find_user(db, "dev-admin")
        assert user is not None
        assert verify_password(user.password_hash, "a dev admin password")


def test_bootstrap_rejects_weak_dev_password(
    env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory: object
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("short", encoding="utf-8")
    monkeypatch.setenv("DSEC_DEV_ADMIN_PASSWORD_FILE", str(secret))
    get_settings.cache_clear()
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code == 1
    assert "at least 12" in result.output


def test_db_upgrade(env: None, session_factory: object) -> None:
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output


def test_dev_create_user_with_file(
    env: None, tmp_path: Path, session_factory: sessionmaker[Session]
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("another long password", encoding="utf-8")
    args = ["dev", "create-user", "alice", "--display-name", "Alice"]
    result = runner.invoke(app, [*args, "--password-file", str(secret)])
    assert result.exit_code == 0, result.output
    assert "user alice created" in result.stdout
    again = runner.invoke(app, ["dev", "create-user", "alice", "--password-file", str(secret)])
    assert "user alice updated" in again.stdout


def test_dev_create_user_needs_password_source(env: None) -> None:
    result = runner.invoke(app, ["dev", "create-user", "bob"])
    assert result.exit_code == 1
    assert "use --password-file" in result.output


def test_dev_commands_refused_in_production(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSEC_MODE", "production")
    get_settings.cache_clear()
    result = runner.invoke(app, ["dev", "create-user", "mallory"])
    assert result.exit_code == 2
    assert "not allowed in production" in result.output


def test_dev_commands_refused_without_local_accounts(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DSEC_LOCAL_ACCOUNTS", "false")
    get_settings.cache_clear()
    result = runner.invoke(app, ["dev", "create-user", "mallory"])
    assert result.exit_code == 2
    assert "only in development mode" in result.output


def test_health_worker(env: None, db_settings: Settings) -> None:
    path = db_settings.worker_heartbeat_file
    path.unlink(missing_ok=True)
    assert runner.invoke(app, ["health", "worker"]).exit_code == 1
    path.touch()
    assert runner.invoke(app, ["health", "worker"]).exit_code == 0
    old = path.stat().st_mtime - 600
    os.utime(path, (old, old))
    assert runner.invoke(app, ["health", "worker"]).exit_code == 1


def test_health_api_unreachable() -> None:
    result = runner.invoke(app, ["health", "api", "--port", "1"])
    assert result.exit_code == 1
    assert "unreachable" in result.output
