"""``dsec-metrics`` command line."""

from __future__ import annotations

import getpass
import http.client
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from dsec_metrics.__about__ import PRODUCT_NAME, __version__
from dsec_metrics.auth.users import PasswordPolicyError, ensure_local_user
from dsec_metrics.config import (
    Mode,
    Settings,
    StartupError,
    get_settings,
    read_secret_file,
    validate_startup,
)
from dsec_metrics.db.engine import make_engine, make_session_factory, transaction
from dsec_metrics.db.migrate import upgrade
from dsec_metrics.logs import configure_logging
from dsec_metrics.worker.main import heartbeat_age

app = typer.Typer(
    name=PRODUCT_NAME,
    help="Compliance metrics and audit evidence for data security teams.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
dev_app = typer.Typer(help="Development-mode commands. Refused in production mode.")
app.add_typer(db_app, name="db")
app.add_typer(dev_app, name="dev")


class Component(StrEnum):
    """A long-running process."""

    API = "api"
    WORKER = "worker"


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


def _settings() -> Settings:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        validate_startup(settings)
    except StartupError as exc:
        raise _fail(str(exc), 2) from None
    return settings


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"{PRODUCT_NAME} {__version__}")


@app.command()
def serve(
    component: Component,
    host: Annotated[str, typer.Option(help="Address for the API to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port for the API to listen on.")] = 8000,
) -> None:
    """Run the API server or the worker."""
    settings = _settings()
    if component is Component.WORKER:
        from dsec_metrics.worker.main import main as worker_main

        worker_main()
        return
    import uvicorn

    uvicorn.run(
        "dsec_metrics.api.app:app_factory",
        factory=True,
        host=host,
        port=port,
        # The API listens only on the internal network, where the reverse proxy is the
        # only client, so the proxy's forwarding headers are trusted.
        proxy_headers=True,
        forwarded_allow_ips="*",
        server_header=False,
        log_config=None,
        log_level=settings.log_level.lower(),
    )


@app.command()
def health(
    component: Component,
    port: Annotated[int, typer.Option(help="API port to probe.")] = 8000,
    max_age: Annotated[int, typer.Option(help="Worker heartbeat age limit, seconds.")] = 90,
) -> None:
    """Container health check. Exit code 0 when healthy."""
    if component is Component.API:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request("GET", "/api/healthz")
            status = conn.getresponse().status
        except OSError as exc:
            raise _fail(f"api unreachable: {exc}") from None
        finally:
            conn.close()
        if status != http.client.OK:
            raise _fail(f"api returned {status}")
        return
    age = heartbeat_age(get_settings().worker_heartbeat_file)
    if age is None or age > max_age:
        raise _fail("worker heartbeat missing or stale")


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply database migrations."""
    settings = _settings()
    engine = make_engine(settings)
    try:
        upgrade(engine, revision)
    finally:
        engine.dispose()
    typer.echo(f"database at {revision}")


@app.command()
def bootstrap() -> None:
    """Apply migrations, then in development mode create or update the dev admin.

    The dev admin is created only when local accounts are enabled and
    ``DSEC_DEV_ADMIN_PASSWORD_FILE`` is set.
    """
    settings = _settings()
    engine = make_engine(settings)
    try:
        upgrade(engine)
        typer.echo("database migrated")
        if (
            settings.mode is Mode.DEVELOPMENT
            and settings.local_accounts
            and settings.dev_admin_password_file is not None
        ):
            password = read_secret_file(settings.dev_admin_password_file)
            with transaction(make_session_factory(engine)) as db:
                created = ensure_local_user(
                    db, settings.dev_admin_username, password, "Development admin"
                )
            typer.echo(
                f"dev user {settings.dev_admin_username} {'created' if created else 'up to date'}"
            )
    except (StartupError, PasswordPolicyError) as exc:
        raise _fail(str(exc)) from None
    finally:
        engine.dispose()


@dev_app.command("create-user")
def dev_create_user(
    username: str,
    display_name: Annotated[str | None, typer.Option(help="Name shown in the UI.")] = None,
    password_file: Annotated[
        Path | None, typer.Option(help="Read the password from this file instead of a prompt.")
    ] = None,
) -> None:
    """Create a local account, or reset its password. Development mode only."""
    settings = _settings()
    if settings.mode is not Mode.DEVELOPMENT or not settings.local_accounts:
        raise _fail("local accounts are available only in development mode", 2)
    if password_file is not None:
        password = read_secret_file(password_file)
    elif sys.stdin.isatty():
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise _fail("passwords do not match")
    else:
        raise _fail("no terminal: use --password-file")
    engine = make_engine(settings)
    try:
        with transaction(make_session_factory(engine)) as db:
            created = ensure_local_user(db, username, password, display_name or username)
    except PasswordPolicyError as exc:
        raise _fail(str(exc)) from None
    finally:
        engine.dispose()
    typer.echo(f"user {username} {'created' if created else 'updated'}")
