from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.api import limits
from dsec_metrics.api.app import create_app
from dsec_metrics.auth.ratelimit import count_request, purge_old_windows
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import RateLimitWindow
from tests.conftest import TEST_ORIGIN, login
from tests.integration.test_route_authz import CASES

pytestmark = pytest.mark.integration


def make_client(settings: Settings, **overrides: int) -> Iterator[TestClient]:
    app = create_app(settings.model_copy(update=overrides))
    with TestClient(app, base_url=TEST_ORIGIN, headers={"Origin": TEST_ORIGIN}) as client:
        yield client


@pytest.fixture
def strict(db_settings: Settings, session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    yield from make_client(db_settings, rate_limit_per_address=3)


def test_address_limit_returns_429_with_retry_after(strict: TestClient) -> None:
    for _ in range(3):
        assert strict.get("/api/meta").status_code == 200
    response = strict.get("/api/meta")
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 61
    assert response.headers["Cache-Control"] == "no-store"
    # Unknown paths count and are limited too.
    assert strict.get("/api/nothing-here").status_code == 429


def test_every_route_is_limited(
    db_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    for client in make_client(db_settings, rate_limit_per_address=1):
        assert client.get("/api/healthz").status_code == 200
        for method, path in CASES:
            response = client.request(method, path.replace("{", "x").replace("}", ""))
            assert response.status_code == 429, (method, path)


def test_session_limit_is_separate_from_address_limit(
    db_settings: Settings, session_factory: sessionmaker[Session], user: str
) -> None:
    for client in make_client(db_settings, rate_limit_per_session=3):
        login(client)  # the sign-in request itself carries no cookie yet
        assert client.get("/api/me").status_code == 200
        assert client.get("/api/me").status_code == 200
        assert client.get("/api/me").status_code == 200
        assert client.get("/api/me").status_code == 429
        client.cookies.clear()
        assert client.get("/api/meta").status_code == 200


def test_body_limits(db_settings: Settings, session_factory: sessionmaker[Session]) -> None:
    for client in make_client(db_settings, max_request_bytes=2048):
        big = client.post(
            "/api/auth/login",
            content=b"x" * 4096,
            headers={"Content-Type": "application/json"},
        )
        assert big.status_code == 413
        bad = client.post("/api/auth/login", headers={"Content-Length": "abc"})
        assert bad.status_code in (400, 413)

        def chunks() -> Iterator[bytes]:
            yield b"{}"

        chunked = client.post(
            "/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert chunked.status_code == 411


def test_counter_failure_lets_requests_through(
    strict: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> dict[str, int]:
        raise OperationalError("select 1", {}, Exception("down"))

    monkeypatch.setattr(limits, "count_request", broken)
    for _ in range(5):
        assert strict.get("/api/meta").status_code == 200


def test_counters_store_hashes_and_are_purged(session_factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 9, 27, 10, 0, 30, tzinfo=UTC)
    with transaction(session_factory) as db:
        assert count_request(db, ["a:10.0.0.1", "s:abc"], now) == {"a:10.0.0.1": 1, "s:abc": 1}
        assert count_request(db, ["a:10.0.0.1"], now + timedelta(seconds=10)) == {"a:10.0.0.1": 2}
        assert count_request(db, ["a:10.0.0.1"], now + timedelta(minutes=1)) == {"a:10.0.0.1": 1}
    with transaction(session_factory) as db:
        purge_old_windows(db, now + timedelta(minutes=11))
        assert db.scalar(select(func.count()).select_from(RateLimitWindow)) == 0


def test_session_cookie_is_not_stored(
    db_settings: Settings, session_factory: sessionmaker[Session], user: str
) -> None:
    for client in make_client(db_settings):
        login(client)
        client.get("/api/me")
        cookie = next(iter(client.cookies.values()))
        with session_factory() as db:
            keys = db.scalars(select(RateLimitWindow.key)).all()
        assert any(k.startswith("s:") for k in keys)
        assert all(cookie not in k for k in keys)
