"""``dsec-metrics`` command line."""

from __future__ import annotations

import getpass
import http.client
import sys
from datetime import UTC, date, datetime, timedelta
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
                    db, settings.dev_admin_username, password, "Development admin", ("admin",)
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
    role: Annotated[
        list[str] | None,
        typer.Option(help="Role to give the user; repeat for several. Default: viewer."),
    ] = None,
) -> None:
    """Create a local account, or reset its password and roles. Development mode only."""
    from dsec_metrics.api.policy import ROLES

    roles = tuple(role or ["viewer"])
    unknown = sorted(set(roles) - ROLES)
    if unknown:
        raise _fail(f"unknown role {', '.join(unknown)}; use {', '.join(sorted(ROLES))}", 2)
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
            created = ensure_local_user(db, username, password, display_name or username, roles)
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
        f"{len(content.collectors)} collectors, {len(content.registers)} registers"
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
                db,
                content.collectors[instance],
                query,
                _as_of(as_of),
                default_secret_resolver(),
                actor="cli",
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
            current = sync_definitions(db, content, "cli")
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
                stats = run_period(db, content, period, secrets, actor="cli")
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


# Reports, verification and the audit log (M3).

report_app = typer.Typer(help="Build evidence packages.", no_args_is_help=True)
keys_app = typer.Typer(help="Signing keys for evidence packages.", no_args_is_help=True)
audit_app = typer.Typer(help="The hash-chained audit log.", no_args_is_help=True)
users_app = typer.Typer(help="Users and auditor grants.", no_args_is_help=True)
app.add_typer(report_app, name="report")
app.add_typer(keys_app, name="keys")
app.add_typer(audit_app, name="audit")
app.add_typer(users_app, name="users")


@keys_app.command("generate")
def keys_generate(
    private_key: Annotated[Path, typer.Option(help="Where to write the private key (PEM).")],
    public_key: Annotated[Path, typer.Option(help="Where to write the public key (PEM).")],
) -> None:
    """Create an Ed25519 key pair for signing packages. Refuses to overwrite a file that
    has contents (an empty placeholder is replaced)."""
    import os

    from dsec_metrics.reports.signing import generate, load_private

    for path in (private_key, public_key):
        if path.exists() and path.stat().st_size > 0:
            raise _fail(f"{path} already exists")
    private_pem, public_pem = generate()
    fd = os.open(private_key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(private_pem)
    public_key.write_bytes(public_pem)
    typer.echo(f"fingerprint {load_private(private_key).fingerprint}")


@report_app.command("build")
def report_build(
    report_type: Annotated[
        str,
        typer.Argument(
            help="control, framework, reproducibility, risk_committee, management or exceptions"
        ),
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write the ZIP.")],
    period_start: Annotated[str, typer.Option(help="First day, YYYY-MM-DD.")],
    period_end: Annotated[str, typer.Option(help="Last day, YYYY-MM-DD.")],
    control: Annotated[str | None, typer.Option(help="Control id (control reports).")] = None,
    framework: Annotated[str | None, typer.Option(help="Framework pack id.")] = None,
    requirement: Annotated[
        list[str] | None, typer.Option(help="Requirement id or prefix; repeat for several.")
    ] = None,
    metric: Annotated[str | None, typer.Option(help="Metric id (reproducibility).")] = None,
    prepared_for: Annotated[str, typer.Option(help="The 'Prepared for' line.")] = "",
) -> None:
    """Build, sign and store a package, and write a copy to a file."""
    from pydantic import ValidationError

    from dsec_metrics.reports.builder import generate
    from dsec_metrics.reports.data import ReportError, ReportRequest
    from dsec_metrics.reports.signing import SigningKeyError, load_private

    settings = _settings()
    if settings.report_signing_key_file is None:
        raise _fail("set DSEC_REPORT_SIGNING_KEY_FILE to the signing key", 2)
    try:
        key = load_private(settings.report_signing_key_file)
        request = ReportRequest(
            report_type=report_type,  # type: ignore[arg-type]
            period_start=date.fromisoformat(period_start),
            period_end=date.fromisoformat(period_end),
            control_id=control,
            framework=framework,
            requirements=requirement or [],
            metric_id=metric,
            prepared_for=prepared_for,
        )
    except (SigningKeyError, ValidationError, ValueError) as exc:
        raise _fail(
            str(exc).splitlines()[0] if isinstance(exc, ValidationError) else str(exc), 2
        ) from None
    engine = make_engine(settings)
    try:
        with transaction(make_session_factory(engine)) as db:
            generated = generate(db, request, key, "cli")
            content = generated.built.content
            package_id = generated.row.id
    except ReportError as exc:
        raise _fail(str(exc)) from None
    finally:
        engine.dispose()
    output.write_bytes(content)
    typer.echo(f"{output}: package {package_id}, {len(content)} bytes, key {key.fingerprint}")


@app.command()
def verify(
    package: Annotated[Path, typer.Argument(help="The package ZIP.")],
    public_key: Annotated[
        Path | None, typer.Option(help="Public key (PEM) the package must be signed with.")
    ] = None,
    fingerprint: Annotated[
        str | None, typer.Option(help="SHA-256 fingerprint the signing key must have.")
    ] = None,
) -> None:
    """Check a package's signature and every file hash. Exits 1 on any mismatch.

    Needs no database and no network."""
    from dsec_metrics.reports.verify import verify_package

    key = public_key.read_bytes() if public_key else None
    result = verify_package(package, public_key=key, expected_fingerprint=fingerprint)
    for problem in result.problems:
        typer.echo(f"FAIL {problem}")
    if not result.ok:
        raise typer.Exit(1)
    pinned = (
        "pinned"
        if result.pinned
        else "embedded in the package; compare it with the one you were given"
    )
    typer.echo(f"OK {result.files_checked} files match the signed manifest")
    typer.echo(f"signing key {result.fingerprint} ({pinned})")


@app.command()
def reproduce(
    package: Annotated[Path, typer.Argument(help="A metric reproducibility package.")],
    public_key: Annotated[Path | None, typer.Option(help="Public key (PEM) to pin.")] = None,
) -> None:
    """Verify a reproducibility package, then recompute its number from its own evidence."""
    from dsec_metrics.reports.builder import reproduce as run

    result = run(package.read_bytes(), public_key.read_bytes() if public_key else None)
    for problem in result.problems:
        typer.echo(f"FAIL {problem}")
    if not result.ok:
        raise typer.Exit(1)
    typer.echo(f"OK recomputed {result.recomputed} ({result.recomputed_status}), as reported")


@audit_app.command("verify")
def audit_verify() -> None:
    """Recompute the audit chain and report the first broken link. Exits 1 if broken."""
    from dsec_metrics import audit

    settings = _settings()
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as db:
            result = audit.verify_chain(db)
    finally:
        engine.dispose()
    if not result.ok:
        typer.echo(f"BROKEN at entry {result.broken_at}: {result.reason}")
        typer.echo(f"{result.checked} entries before it are intact")
        raise typer.Exit(1)
    typer.echo(f"OK {result.checked} entries, head {result.head}")


@users_app.command("grant-auditor")
def grant_auditor(
    username: str,
    framework: Annotated[list[str], typer.Option(help="Framework pack id; repeat for several.")],
    period_start: Annotated[str, typer.Option(help="First day the auditor may see.")],
    period_end: Annotated[str, typer.Option(help="Last day the auditor may see.")],
    days: Annotated[int, typer.Option(help="Days until the grant expires.", min=1, max=365)] = 30,
    password_file: Annotated[
        Path | None,
        typer.Option(
            help="Create the local account with the password in this file ('-' for stdin)."
        ),
    ] = None,
) -> None:
    """Give a user the auditor role and a time-boxed grant. Local accounts are
    development only; with OIDC (M5) the role comes from the identity provider."""
    from dsec_metrics import audit
    from dsec_metrics.auth.users import find_user
    from dsec_metrics.db.models import AuditorGrant

    settings = _settings()
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    if end < start:
        raise _fail("period_end is before period_start", 2)
    engine = make_engine(settings)
    try:
        with transaction(make_session_factory(engine)) as db:
            user = find_user(db, username)
            if user is None:
                if password_file is None:
                    raise _fail(f"no user {username}; pass --password-file to create one", 2)
                if settings.mode is not Mode.DEVELOPMENT or not settings.local_accounts:
                    raise _fail("local accounts are available only in development mode", 2)
                secret = (
                    sys.stdin.read().strip()
                    if str(password_file) == "-"
                    else read_secret_file(password_file)
                )
                ensure_local_user(db, username, secret, username, ("auditor",))
                user = find_user(db, username)
            if user is None:  # pragma: no cover (just created)
                raise _fail("could not create the user")
            user.roles = sorted({*(user.roles or []), "auditor"})
            now = datetime.now(UTC)
            grant = AuditorGrant(
                user_id=user.id,
                frameworks=sorted(set(framework)),
                period_start=start,
                period_end=end,
                expires_at=now + timedelta(days=days),
                created_by="cli",
            )
            db.add(grant)
            db.flush()
            audit.record(
                db,
                "cli",
                "auditor.grant",
                f"user:{username}",
                {
                    "grant_id": str(grant.id),
                    "frameworks": grant.frameworks,
                    "period": [start.isoformat(), end.isoformat()],
                    "expires_at": grant.expires_at.isoformat(),
                },
            )
            expires = grant.expires_at
    except PasswordPolicyError as exc:
        raise _fail(str(exc)) from None
    finally:
        engine.dispose()
    typer.echo(
        f"{username} may see {', '.join(sorted(set(framework)))} for {start} to {end}"
        f" until {expires:%Y-%m-%d %H:%M} UTC"
    )


# Plugins and collectors (M4).

plugin_app = typer.Typer(help="Installed plugins and new plugin packages.", no_args_is_help=True)
plugin_new_app = typer.Typer(help="Scaffold a new plugin package.", no_args_is_help=True)
app.add_typer(plugin_app, name="plugin")
plugin_app.add_typer(plugin_new_app, name="new")


@plugin_app.command("list")
def plugin_list() -> None:
    """List installed collectors with their version, queries and read-only permissions."""
    from dsec_metrics.plugins.sdk.registry import COLLECTORS, collector_class, plugin_names

    for name in plugin_names(COLLECTORS):
        cls = collector_class(name)
        typer.echo(f"{name} {cls.version}")
        for query, description in sorted(cls.queries.items()):
            typer.echo(f"  query {query}: {description}")
        for permission in cls.required_permissions:
            typer.echo(f"  needs {permission}")


@plugin_new_app.command("collector")
def plugin_new_collector(
    name: Annotated[str, typer.Argument(help="Plugin name, for example asset_inventory.")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Where to create the package.")
    ] = Path(),
) -> None:
    """Create a collector package with an entry point, a config model, fixtures and tests."""
    from dsec_metrics.plugins.scaffold import ScaffoldError, new_collector

    try:
        root = new_collector(name, directory)
    except ScaffoldError as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"created {root}")
    typer.echo(f"next: pip install -e {root} && pytest {root}")


@app.command("test-connection")
def connection_test(instance: str, content_dir: ContentOpt = None) -> None:
    """Check that a collector instance can reach its source with its read-only access."""
    from dsec_metrics.pipeline import build_collector
    from dsec_metrics.plugins.sdk.base import CollectorError
    from dsec_metrics.plugins.sdk.registry import PluginError, default_secret_resolver
    from dsec_metrics.plugins.sdk.secrets import SecretError

    _settings()
    content = _validated_content(content_dir)
    if instance not in content.collectors:
        raise _fail(f"unknown collector instance {instance!r}")
    try:
        collector = build_collector(content.collectors[instance], default_secret_resolver())
        result = collector.test_connection()
    except (CollectorError, PluginError, SecretError, ValueError) as exc:
        raise _fail(f"{instance}: {exc}") from None
    typer.echo(f"{'ok' if result.ok else 'failed'}: {result.detail}")
    if not result.ok:
        raise typer.Exit(1)
