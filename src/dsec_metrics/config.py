"""Runtime settings, read from ``DSEC_*`` environment variables.

Secrets are never passed as plain environment variables in the supported deployment.
They arrive as files (Docker secrets) and the settings hold the file path. The value
is read when needed and kept in a ``SecretStr`` so it does not end up in logs.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Mode(StrEnum):
    """Run mode. Production is the default so a missing setting fails safe."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class SslMode(StrEnum):
    """libpq ``sslmode`` values we allow."""

    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class StartupError(RuntimeError):
    """Raised when the settings describe an unsafe or impossible configuration."""


class Settings(BaseSettings):
    """All runtime settings. Field names map to ``DSEC_<NAME>`` variables."""

    model_config = SettingsConfigDict(env_prefix="DSEC_", extra="ignore", frozen=True)

    mode: Mode = Mode.PRODUCTION
    local_accounts: bool = False
    public_origin: str = "https://localhost"
    log_level: str = "INFO"

    db_host: str = "postgres"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "dsec"
    db_user: str = "dsec"
    db_password: SecretStr | None = None
    db_password_file: Path | None = None
    db_sslmode: SslMode = SslMode.VERIFY_FULL
    db_sslrootcert: Path | None = None

    session_idle_minutes: int = Field(default=30, ge=1, le=24 * 60)
    session_absolute_hours: int = Field(default=8, ge=1, le=24)

    login_window_minutes: int = Field(default=15, ge=1)
    login_max_failures_per_user: int = Field(default=5, ge=1)
    login_max_failures_per_source: int = Field(default=20, ge=1)

    content_dir: Path = Path("content")

    dev_admin_username: str = "dev-admin"
    dev_admin_password_file: Path | None = None

    # A tmpfs mounted at /run/dsec in the container, writable only by the app user.
    worker_heartbeat_file: Path = Path("/run/dsec/worker-heartbeat")
    worker_heartbeat_seconds: int = Field(default=30, ge=1)
    scheduler_poll_seconds: int = Field(default=30, ge=1)

    @field_validator("public_origin")
    @classmethod
    def _origin_is_bare(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"https", "http"} or not parts.netloc:
            raise ValueError("public_origin must look like https://host[:port]")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("public_origin must not contain a path, query or fragment")
        return f"{parts.scheme}://{parts.netloc}"

    @model_validator(mode="after")
    def _one_password_source(self) -> Settings:
        if self.db_password is not None and self.db_password_file is not None:
            raise ValueError("set DSEC_DB_PASSWORD or DSEC_DB_PASSWORD_FILE, not both")
        return self

    def database_password(self) -> SecretStr:
        """Return the database password from the file or the variable."""
        if self.db_password_file is not None:
            return SecretStr(read_secret_file(self.db_password_file))
        if self.db_password is not None:
            return self.db_password
        raise StartupError("no database password: set DSEC_DB_PASSWORD_FILE")

    def database_url(self) -> URL:
        """Build the SQLAlchemy URL. The password never appears in a string form."""
        query: dict[str, str] = {"sslmode": self.db_sslmode.value}
        if self.db_sslrootcert is not None:
            query["sslrootcert"] = str(self.db_sslrootcert)
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.database_password().get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query=query,
        )


def read_secret_file(path: Path) -> str:
    """Read a secret from a file, stripping one trailing newline."""
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StartupError(f"cannot read secret file {path}: {exc.strerror}") from exc
    value = value.removesuffix("\n")
    if not value:
        raise StartupError(f"secret file {path} is empty")
    return value


def validate_startup(settings: Settings) -> None:
    """Refuse configurations that must never run.

    Production mode forbids local accounts, requires an https public origin, and
    requires verified TLS to the database.
    """
    if settings.mode is Mode.PRODUCTION:
        if settings.local_accounts:
            raise StartupError("local accounts are not allowed in production mode")
        if not settings.public_origin.startswith("https://"):
            raise StartupError("production mode requires an https public origin")
        if settings.db_sslmode not in {SslMode.VERIFY_FULL, SslMode.VERIFY_CA}:
            raise StartupError("production mode requires DSEC_DB_SSLMODE=verify-full")
    verified = settings.db_sslmode in {SslMode.VERIFY_FULL, SslMode.VERIFY_CA}
    if verified and settings.db_sslrootcert is None:
        raise StartupError("verified database TLS needs DSEC_DB_SSLROOTCERT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
