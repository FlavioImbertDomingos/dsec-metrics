"""The one place where API access decisions are made.

Every route declares exactly one policy dependency from this module: either
:func:`public` with a reason, or :func:`authenticated` (roles arrive in M5). The test
``tests/integration/test_route_authz.py`` walks the app's routes and fails when a route
declares no policy, declares two, or has no allowed and denied test cases.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from dsec_metrics.auth.sessions import COOKIE_NAME, load_session
from dsec_metrics.auth.tokens import tokens_equal
from dsec_metrics.config import Settings

POLICY_ATTR = "__dsec_policy__"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _tag(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, POLICY_ATTR, name)
        return func

    return wrap


def policy_of(call: object) -> str | None:
    """Return the policy name attached to a dependency callable, if any."""
    value = getattr(call, POLICY_ATTR, None)
    return value if isinstance(value, str) else None


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller."""

    user_id: UUID
    username: str
    display_name: str
    session_id: UUID
    csrf_token: str


def get_settings_dep(request: Request) -> Settings:
    """Settings stored on the app at startup."""
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    """One database session per request.

    Pending changes are committed after the handler returns and rolled back if it
    raises. Handlers whose writes must be durable before the response goes out (sign-in,
    sign-out, failure records) call ``db.commit()`` themselves.
    """
    factory = request.app.state.session_factory
    with factory() as db:
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        db.commit()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def origin_allowed(request: Request, settings: Settings) -> bool:
    """True when the request's Origin header is the configured public origin."""
    origin = request.headers.get("origin")
    return origin is not None and tokens_equal(origin, settings.public_origin)


def public(reason: str) -> Callable[[], None]:
    """Mark a route as reachable without signing in. ``reason`` documents why."""
    if not reason.strip():
        raise ValueError("public routes need a reason")

    @_tag("public")
    def _public() -> None:
        return None

    _public.__doc__ = f"Public: {reason}"
    return _public


@_tag("authenticated")
def authenticated(request: Request, db: DbDep, settings: SettingsDep) -> Principal:
    """Require a live session. Unsafe methods also need the CSRF token and origin."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    row = load_session(db, token, settings, datetime.now(UTC))
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not (header and tokens_equal(header, row.csrf_token)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed")
        if not origin_allowed(request, settings):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
    return Principal(
        user_id=row.user_id,
        username=row.user.username,
        display_name=row.user.display_name,
        session_id=row.id,
        csrf_token=row.csrf_token,
    )


PrincipalDep = Annotated[Principal, Depends(authenticated)]
