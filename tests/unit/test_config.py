from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from dsec_metrics.config import (
    Mode,
    Settings,
    SslMode,
    StartupError,
    read_secret_file,
    validate_startup,
)


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "db_password": SecretStr("pw"),
        "db_sslrootcert": Path("/run/secrets/ca.crt"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_defaults_are_production_and_verified_tls() -> None:
    s = settings()
    assert s.mode is Mode.PRODUCTION
    assert s.local_accounts is False
    assert s.db_sslmode is SslMode.VERIFY_FULL
    validate_startup(s)


def test_production_refuses_local_accounts() -> None:
    with pytest.raises(StartupError, match="local accounts"):
        validate_startup(settings(local_accounts=True))


def test_development_allows_local_accounts() -> None:
    validate_startup(settings(mode=Mode.DEVELOPMENT, local_accounts=True))


def test_production_refuses_plain_http_origin() -> None:
    with pytest.raises(StartupError, match="https"):
        validate_startup(settings(public_origin="http://localhost"))


@pytest.mark.parametrize("mode", [SslMode.DISABLE, SslMode.REQUIRE])
def test_production_refuses_unverified_database_tls(mode: SslMode) -> None:
    with pytest.raises(StartupError, match="verify-full"):
        validate_startup(settings(db_sslmode=mode))


def test_verified_tls_needs_a_root_certificate() -> None:
    with pytest.raises(StartupError, match="SSLROOTCERT"):
        validate_startup(settings(db_sslrootcert=None))


@pytest.mark.parametrize(
    "origin", ["localhost", "ftp://x", "https://x/path", "https://x?q=1", "https://x#f"]
)
def test_public_origin_must_be_bare(origin: str) -> None:
    with pytest.raises(ValidationError):
        settings(public_origin=origin)


def test_public_origin_trailing_slash_is_removed() -> None:
    assert settings(public_origin="https://dsec.example.test/").public_origin == (
        "https://dsec.example.test"
    )


def test_password_from_file(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("from-file\n", encoding="utf-8")
    s = Settings(db_password_file=secret)
    assert s.database_password().get_secret_value() == "from-file"


def test_both_password_sources_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="not both"):
        Settings(db_password=SecretStr("a"), db_password_file=tmp_path / "pw")


def test_missing_password_is_a_startup_error() -> None:
    with pytest.raises(StartupError, match="no database password"):
        Settings().database_password()


def test_database_url_hides_password() -> None:
    url = settings(db_password=SecretStr("s3cret-value")).database_url()
    assert "s3cret-value" not in str(url)
    assert url.password == "s3cret-value"
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == "/run/secrets/ca.crt"


def test_read_secret_file_errors(tmp_path: Path) -> None:
    with pytest.raises(StartupError, match="cannot read"):
        read_secret_file(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(StartupError, match="empty"):
        read_secret_file(empty)


def test_environment_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSEC_MODE", "development")
    monkeypatch.setenv("DSEC_LOCAL_ACCOUNTS", "true")
    s = Settings()
    assert s.mode is Mode.DEVELOPMENT
    assert s.local_accounts is True
