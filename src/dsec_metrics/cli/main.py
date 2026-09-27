"""``dsec-metrics`` command line."""

from __future__ import annotations

import getpass
import http.client
import sys
from datetime import UTC, date, datetime
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
from dsec_metrics.content import Content, cross_check, load_content
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


# Definitions, collection and evaluation (M1).

ContentOpt = Annotated[
    Path | None, typer.Option("--content", help="Content directory (default: DSEC_CONTENT_DIR).")
]
AsOfOpt = Annotated[
    str | None, typer.Option("--as-of", help="Period end date, YYYY-MM-DD (default: today, UTC).")
]


def _as_of(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _fail(f"--as-of must be YYYY-MM-DD, got {value!r}") from None


def _validated_content(path: Path | None) -> Content:
    from dsec_metrics.pipeline import instance_queries

    root = path or get_settings().content_dir
    content = load_content(root)
    problems = (
        [*content.problems, *cross_check(content, instance_queries)]
        if content.ok
        else content.problems
    )
    if problems:
        for problem in problems:
            typer.echo(f"error: {problem}", err=True)
        raise _fail(f"{len(problems)} problem(s) in {root}")
    return content


@app.command()
def validate(content_dir: ContentOpt = None) -> None:
    """Validate every definition and the references between them."""
    content = _validated_content(content_dir)
    typer.echo(
        "ok: "
        f"{len(content.frameworks)} frameworks, {len(content.metrics)} metrics, "
        f"{len(content.controls)} controls, {len(content.dashboards)} dashboards, "
        f"{len(content.collectors)} collectors"
    )


@app.command()
def collect(
    instance: str,
    query: str,
    as_of: AsOfOpt = None,
    content_dir: ContentOpt = None,
) -> None:
    """Run one collector query once and store the redacted batch."""
    from dsec_metrics.pipeline import run_collection
    from dsec_metrics.plugins.sdk.registry import default_secret_resolver

    settings = _settings()
    content = _validated_content(content_dir)
    if instance not in content.collectors:
        raise _fail(f"unknown collector instance {instance!r}")
    engine = make_engine(settings)
    try:
        with transaction(make_session_factory(engine)) as db:
            result = run_collection(
                db, content.collectors[instance], query, _as_of(as_of), default_secret_resolver()
            )
    finally:
        engine.dispose()
    typer.echo(
        f"{result.status}: {result.records} records in {result.batches} batch(es), "
        f"{result.pans_masked} card numbers masked"
    )
    if result.status != "succeeded":
        raise _fail(result.error or "collection failed")


@app.command()
def evaluate(
    metric: Annotated[
        list[str] | None, typer.Option("--metric", help="Metric id; repeatable.")
    ] = None,
    as_of: AsOfOpt = None,
    content_dir: ContentOpt = None,
) -> None:
    """Evaluate metrics from the latest stored batches."""
    from dsec_metrics.pipeline import evaluate_all, sync_definitions

    settings = _settings()
    content = _validated_content(content_dir)
    unknown = [m for m in metric or [] if m not in content.metrics]
    if unknown:
        raise _fail(f"unknown metric(s): {', '.join(unknown)}")
    engine = make_engine(settings)
    try:
        with transaction(make_session_factory(engine)) as db:
            current = sync_definitions(db, content)
            count = evaluate_all(db, content, current, _as_of(as_of), metric or None)
    finally:
        engine.dispose()
    typer.echo(f"{count} new measurement(s)")


@app.command()
def demo(
    months: Annotated[
        int, typer.Option(help="Month-ends to load, ending at the sample anchor.")
    ] = 12,
    content_dir: ContentOpt = None,
) -> None:
    """Load synthetic sample data and default content, then evaluate every month."""
    from dsec_metrics.pipeline import run_period
    from dsec_metrics.plugins.collectors.sample import SampleConfig, month_ends
    from dsec_metrics.plugins.sdk.registry import default_secret_resolver

    settings = _settings()
    content = _validated_content(content_dir)
    sample = next((c for c in content.collectors.values() if c.plugin == "sample"), None)
    if sample is None:
        raise _fail("the content has no collector instance using the sample plugin")
    anchor = SampleConfig.model_validate(sample.config).anchor
    engine = make_engine(settings)
    secrets = default_secret_resolver()
    try:
        for period in month_ends(anchor, months):
            with transaction(make_session_factory(engine)) as db:
                stats = run_period(db, content, period, secrets)
            typer.echo(
                f"{period}: {stats['runs']} collections ({stats['failed_runs']} failed), "
                f"{stats['measurements']} new measurements"
            )
    finally:
        engine.dispose()


STATUS_MARK = {"green": "OK ", "amber": "!! ", "red": "XX ", "unknown": "?? "}


@app.command()
def status(as_of: AsOfOpt = None, content_dir: ContentOpt = None) -> None:
    """Print the metric catalog with the latest value and status of each metric."""
    from dsec_metrics.pipeline import latest_status

    settings = _settings()
    content = _validated_content(content_dir)
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as db:
            lines = latest_status(db, content, date.fromisoformat(as_of) if as_of else None)
    finally:
        engine.dispose()
    typer.echo(f"{'metric':<8} {'status':<9} {'value':>10}  {'as of':<10}  name")
    for line in lines:
        value = "-" if line.value is None else f"{line.value:,.2f}".rstrip("0").rstrip(".")
        if line.unit == "percent" and line.value is not None:
            value += "%"
        typer.echo(
            f"{line.metric_id:<8} {STATUS_MARK[line.status]}{line.status:<6} {value:>10}  "
            f"{line.as_of.isoformat() if line.as_of else '-':<10}  {line.name}"
        )
