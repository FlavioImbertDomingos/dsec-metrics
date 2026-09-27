"""The M3 commands: keys, report build, verify, reproduce, audit verify, grant-auditor."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dsec_metrics.auth.users import find_user
from dsec_metrics.cli.main import app
from dsec_metrics.config import Settings, get_settings
from tests.conftest import load_demo

pytestmark = pytest.mark.integration
runner = CliRunner()


@pytest.fixture
def env(
    db_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> Iterator[Path]:
    load_demo(session_factory, months=3)
    key = tmp_path / "signing.pem"
    public = tmp_path / "signing.pub"
    values = {
        "DSEC_MODE": "development",
        "DSEC_LOCAL_ACCOUNTS": "true",
        "DSEC_PUBLIC_ORIGIN": db_settings.public_origin,
        "DSEC_DB_HOST": db_settings.db_host,
        "DSEC_DB_PORT": str(db_settings.db_port),
        "DSEC_DB_PASSWORD": "dsec",
        "DSEC_DB_SSLMODE": "disable",
        "DSEC_REPORT_SIGNING_KEY_FILE": str(key),
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    result = runner.invoke(
        app, ["keys", "generate", "--private-key", str(key), "--public-key", str(public)]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("fingerprint ")
    assert key.stat().st_mode & 0o777 == 0o600
    yield tmp_path
    get_settings.cache_clear()


def build(tmp: Path, name: str, *args: str) -> Path:
    out = tmp / f"{name}.zip"
    result = runner.invoke(
        app,
        [
            "report",
            "build",
            *args,
            "--output",
            str(out),
            "--period-start",
            "2026-07-01",
            "--period-end",
            "2026-09-30",
            "--prepared-for",
            "Example Audit LLP",
        ],
    )
    assert result.exit_code == 0, result.output
    return out


def test_keys_refuse_to_overwrite(env: Path) -> None:
    result = runner.invoke(
        app,
        [
            "keys",
            "generate",
            "--private-key",
            str(env / "signing.pem"),
            "--public-key",
            str(env / "x"),
        ],
    )
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_build_verify_and_detect_a_changed_byte(env: Path) -> None:
    package = build(env, "ctrl", "control", "--control", "DS-SM-02")
    ok = runner.invoke(app, ["verify", str(package), "--public-key", str(env / "signing.pub")])
    assert ok.exit_code == 0, ok.output
    assert "OK" in ok.stdout
    assert "(pinned)" in ok.stdout
    unpinned = runner.invoke(app, ["verify", str(package)])
    assert "compare it with the one you were given" in unpinned.stdout

    # Change one byte in one file, rebuilding the archive so it is still a valid ZIP.
    src = zipfile.ZipFile(package)
    tampered = env / "tampered.zip"
    with zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "report.xlsx":
                data = data[:100] + bytes([data[100] ^ 1]) + data[101:]
            dst.writestr(info, data)
    bad = runner.invoke(app, ["verify", str(tampered)])
    assert bad.exit_code == 1
    assert "FAIL report.xlsx: SHA-256 does not match the manifest" in bad.stdout

    wrong = runner.invoke(app, ["verify", str(package), "--fingerprint", "0" * 64])
    assert wrong.exit_code == 1


def test_reproduce(env: Path) -> None:
    package = build(env, "repro", "reproducibility", "--metric", "KRI-06")
    result = runner.invoke(app, ["reproduce", str(package)])
    assert result.exit_code == 0, result.output
    assert "as reported" in result.stdout
    other = build(env, "mgmt", "management")
    assert runner.invoke(app, ["reproduce", str(other)]).exit_code == 1


def test_report_build_errors(env: Path) -> None:
    bad_type = runner.invoke(
        app,
        [
            "report",
            "build",
            "nonsense",
            "-o",
            str(env / "x.zip"),
            "--period-start",
            "2026-07-01",
            "--period-end",
            "2026-09-30",
        ],
    )
    assert bad_type.exit_code == 2
    unknown = runner.invoke(
        app,
        [
            "report",
            "build",
            "control",
            "--control",
            "DS-XX-99",
            "-o",
            str(env / "x.zip"),
            "--period-start",
            "2026-07-01",
            "--period-end",
            "2026-09-30",
        ],
    )
    assert unknown.exit_code == 1
    assert "unknown control" in unknown.output


def test_audit_verify_finds_the_break(env: Path, engine: Engine) -> None:
    ok = runner.invoke(app, ["audit", "verify"])
    assert ok.exit_code == 0, ok.output
    assert ok.stdout.startswith("OK ")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE audit_events SET target = 'x' WHERE seq = 7"))
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    broken = runner.invoke(app, ["audit", "verify"])
    assert broken.exit_code == 1
    assert "BROKEN at entry 7" in broken.stdout
    assert "6 entries before it are intact" in broken.stdout


def test_grant_auditor(env: Path, session_factory: sessionmaker[Session]) -> None:
    password = env / "pw"
    password.write_text("an auditor password\n", encoding="utf-8")
    args = [
        "users",
        "grant-auditor",
        "qsa",
        "--framework",
        "pci-dss-4.0.1",
        "--period-start",
        "2026-07-01",
        "--period-end",
        "2026-09-30",
        "--days",
        "14",
    ]
    missing = runner.invoke(app, args)
    assert missing.exit_code == 2
    created = runner.invoke(app, [*args, "--password-file", str(password)])
    assert created.exit_code == 0, created.output
    assert "qsa may see pci-dss-4.0.1" in created.stdout
    with session_factory() as db:
        user = find_user(db, "qsa")
        assert user is not None
        assert user.roles == ["auditor"]
    backwards = runner.invoke(
        app,
        [
            "users",
            "grant-auditor",
            "qsa",
            "--framework",
            "x",
            "--period-start",
            "2026-09-30",
            "--period-end",
            "2026-07-01",
        ],
    )
    assert backwards.exit_code == 2


def test_verify_needs_no_database(tmp_path: Path) -> None:
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    result = runner.invoke(app, ["verify", str(junk)])
    assert result.exit_code == 1
    assert "not a readable ZIP archive" in result.stdout
    assert zipfile.is_zipfile(io.BytesIO(b"")) is False
