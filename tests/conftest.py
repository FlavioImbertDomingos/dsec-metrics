"""Shared fixtures. Integration tests run against a real Postgres in a container."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from dsec_metrics.api.app import create_app
from dsec_metrics.auth.users import ensure_local_user
from dsec_metrics.config import Mode, Settings, SslMode
from dsec_metrics.content import load_content
from dsec_metrics.db.engine import make_engine, make_session_factory, transaction
from dsec_metrics.db.migrate import upgrade
from dsec_metrics.pipeline import run_period
from dsec_metrics.plugins.collectors.sample import SampleConfig, month_ends
from dsec_metrics.plugins.sdk.registry import default_secret_resolver
from dsec_metrics.reports.signing import generate as generate_key

# Same image as compose.yaml. Override to test against another Postgres build.
POSTGRES_IMAGE = os.environ.get(
    "DSEC_TEST_POSTGRES_IMAGE",
    "postgres:16@sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54",
)
TEST_ORIGIN = "https://testserver"
CONTENT_DIR = Path(__file__).resolve().parents[1] / "content"
TEST_USER = "tester"
TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """One Postgres container for the whole test session."""
    with PostgresContainer(POSTGRES_IMAGE, username="dsec", password="dsec", dbname="dsec") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_settings(postgres: PostgresContainer, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Development-mode settings pointing at the test container.

    The test container has no TLS, so ``db_sslmode`` is ``disable`` here. Production
    mode refuses that setting; see ``tests/unit/test_config.py``.
    """
    heartbeat = tmp_path_factory.mktemp("worker") / "heartbeat"
    signing_key = tmp_path_factory.mktemp("keys") / "report-signing.pem"
    signing_key.write_bytes(generate_key()[0])
    return Settings(
        mode=Mode.DEVELOPMENT,
        local_accounts=True,
        public_origin=TEST_ORIGIN,
        db_host=postgres.get_container_host_ip(),
        db_port=int(postgres.get_exposed_port(5432)),
        db_name="dsec",
        db_user="dsec",
        db_password="dsec",  # type: ignore[arg-type]
        db_sslmode=SslMode.DISABLE,
        worker_heartbeat_file=Path(heartbeat),
        worker_heartbeat_seconds=1,
        report_signing_key_file=signing_key,
    )


@pytest.fixture(scope="session")
def engine(db_settings: Settings) -> Iterator[Engine]:
    """Migrated database engine."""
    eng = make_engine(db_settings)
    upgrade(eng)
    yield eng
    eng.dispose()


def truncate_all(engine: Engine) -> None:
    """Empty every application table. The audit log's append-only trigger is lifted for
    the truncate only; tests that check the trigger run with it in place."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        conn.execute(
            text(
                "TRUNCATE auth_failures, sessions, users, measurements, record_batches,"
                " collection_runs, collector_instances, definitions, schedules, rate_limits,"
                " auditor_grants, report_links, report_packages, audit_events"
                " RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))


def load_demo(factory: sessionmaker[Session], months: int = 1) -> None:
    """Sync the default content and run the sample collector for the last month-ends."""
    content = load_content(CONTENT_DIR)
    anchor = SampleConfig.model_validate(content.collectors["sample"].config).anchor
    secrets = default_secret_resolver()
    for period in month_ends(anchor, months):
        with transaction(factory) as db:
            run_period(db, content, period, secrets)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Clean tables before each test, then hand out sessions."""
    truncate_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def user(session_factory: sessionmaker[Session]) -> str:
    """A local account with a known password."""
    with transaction(session_factory) as db:
        ensure_local_user(db, TEST_USER, TEST_PASSWORD, "Test User", ("admin",))
    return TEST_USER


@pytest.fixture
def client(db_settings: Settings, session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """API client over https so the Secure cookie is sent back."""
    app = create_app(db_settings)
    with TestClient(app, base_url=TEST_ORIGIN, headers={"Origin": TEST_ORIGIN}) as test_client:
        yield test_client


def login(client: TestClient, username: str = TEST_USER, password: str = TEST_PASSWORD) -> str:
    """Sign in and return the CSRF token."""
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["csrf_token"]
    return token
