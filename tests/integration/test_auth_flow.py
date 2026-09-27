from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.auth.sessions import COOKIE_NAME
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import AuthFailure, User, UserSession
from tests.conftest import TEST_PASSWORD, TEST_USER, login

pytestmark = pytest.mark.integration


def test_login_sets_hardened_cookie(client: TestClient, user: str) -> None:
    response = client.post(
        "/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert attribute.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["username"] == TEST_USER


def test_only_token_hash_is_stored(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    login(client)
    token = client.cookies[COOKIE_NAME]
    with session_factory() as db:
        stored = db.scalars(select(UserSession.token_hash)).one()
    assert token.encode() not in stored
    assert len(stored) == 32


def test_me_and_logout(client: TestClient, user: str) -> None:
    csrf = login(client)
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {
        "username": TEST_USER,
        "display_name": "Test User",
        "csrf_token": csrf,
        "roles": ["admin"],
    }

    out = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 204
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    ("username", "password"), [(TEST_USER, "wrong password!"), ("nobody", TEST_PASSWORD)]
)
def test_bad_credentials_get_one_generic_answer(
    client: TestClient, user: str, username: str, password: str
) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert COOKIE_NAME not in client.cookies


def test_failures_are_recorded_and_throttled(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    for _ in range(5):
        bad = client.post("/api/auth/login", json={"username": TEST_USER, "password": "nope"})
        assert bad.status_code == 401
    with session_factory() as db:
        assert len(db.scalars(select(AuthFailure)).all()) == 5
    # The right password is refused too while the user is throttled.
    good = client.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD})
    assert good.status_code == 429


def test_source_throttle(client: TestClient, user: str, db_settings: Settings) -> None:
    for i in range(db_settings.login_max_failures_per_source):
        client.post("/api/auth/login", json={"username": f"user{i}", "password": "nope"})
    response = client.post(
        "/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD}
    )
    assert response.status_code == 429


def test_success_clears_failures(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    client.post("/api/auth/login", json={"username": TEST_USER, "password": "nope"})
    login(client)
    with session_factory() as db:
        assert db.scalars(select(AuthFailure)).all() == []


def test_login_requires_matching_origin(client: TestClient, user: str) -> None:
    body = {"username": TEST_USER, "password": TEST_PASSWORD}
    evil = client.post("/api/auth/login", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    del client.headers["Origin"]
    assert client.post("/api/auth/login", json=body).status_code == 403


def test_login_absent_when_local_accounts_disabled(
    db_settings: Settings, session_factory: sessionmaker[Session], user: str
) -> None:
    from dsec_metrics.api.app import create_app

    app = create_app(db_settings.model_copy(update={"local_accounts": False}))
    origin = {"Origin": "https://testserver"}
    with TestClient(app, base_url="https://testserver", headers=origin) as c:
        body = {"username": TEST_USER, "password": TEST_PASSWORD}
        assert c.post("/api/auth/login", json=body).status_code == 404


def test_unsafe_request_needs_csrf_and_origin(client: TestClient, user: str) -> None:
    csrf = login(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "x" * 43}).status_code == 403
    wrong_origin = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}
    )
    assert wrong_origin.status_code == 403
    assert client.get("/api/me").status_code == 200


def test_unknown_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(COOKIE_NAME, "forged-token", domain="testserver")
    assert client.get("/api/me").status_code == 401
    client.cookies.set(COOKIE_NAME, "non-ascii-é", domain="testserver")
    assert client.get("/api/me").status_code == 401


def _age_session(factory: sessionmaker[Session], **values: datetime) -> None:
    with transaction(factory) as db:
        db.execute(update(UserSession).values(**values))


def test_idle_timeout(
    client: TestClient, user: str, session_factory: sessionmaker[Session], db_settings: Settings
) -> None:
    login(client)
    past = datetime.now(UTC) - timedelta(minutes=db_settings.session_idle_minutes + 1)
    _age_session(session_factory, last_seen_at=past)
    assert client.get("/api/me").status_code == 401


def test_absolute_timeout(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    login(client)
    _age_session(session_factory, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert client.get("/api/me").status_code == 401


def test_activity_refreshes_last_seen(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    login(client)
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    _age_session(session_factory, last_seen_at=earlier)
    assert client.get("/api/me").status_code == 200
    with session_factory() as db:
        assert db.scalars(select(UserSession.last_seen_at)).one() > earlier


def test_disabled_user_loses_session(
    client: TestClient, user: str, session_factory: sessionmaker[Session]
) -> None:
    login(client)
    with transaction(session_factory) as db:
        db.execute(update(User).values(is_active=False))
    assert client.get("/api/me").status_code == 401
    body = {"username": TEST_USER, "password": TEST_PASSWORD}
    assert client.post("/api/auth/login", json=body).status_code == 401


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "<script>", "password": "p", "extra": "x"}
    )
    assert response.status_code == 422
    assert "<script>" not in response.text
    assert response.json()["detail"] == "Invalid request"
