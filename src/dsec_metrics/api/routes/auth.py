"""Development-mode sign-in, sign-out and the current user."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from dsec_metrics.api.policy import (
    DbDep,
    PrincipalDep,
    SettingsDep,
    authenticated,
    origin_allowed,
    public,
)
from dsec_metrics.api.schemas import ErrorResponse, LoginRequest, MeResponse
from dsec_metrics.auth import throttle
from dsec_metrics.auth.passwords import verify_password
from dsec_metrics.auth.sessions import COOKIE_NAME, create_session, end_session
from dsec_metrics.auth.users import find_user
from dsec_metrics.config import Settings
from dsec_metrics.logs import security_event

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])
log = logging.getLogger(__name__)

INVALID = "Invalid username or password"


def client_address(request: Request) -> str:
    """Peer address as seen by uvicorn (after the trusted proxy's forwarding header)."""
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_absolute_hours * 3600,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


@router.post(
    "/login",
    dependencies=[Depends(public("sign-in form; guarded by origin check and throttling"))],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> MeResponse:
    """Sign in with a local account. Available only when local accounts are enabled."""
    if not settings.local_accounts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not origin_allowed(request, settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")

    now = datetime.now(UTC)
    source = client_address(request)
    if throttle.is_throttled(db, body.username, source, settings, now):
        security_event(log, "login_throttled", username=body.username, source=source)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try later")

    user = find_user(db, body.username)
    ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not ok or not user.is_active:
        throttle.record_failure(db, body.username, source, now)
        security_event(log, "login_failed", username=body.username, source=source)
        db.commit()  # keep the failure record even though the request fails
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)

    throttle.clear_failures(db, user.username)
    issued = create_session(db, user, settings, now, source)
    db.commit()
    _set_cookie(response, issued.token, settings)
    security_event(log, "login_succeeded", username=user.username, source=source)
    return MeResponse(
        username=user.username, display_name=user.display_name, csrf_token=issued.csrf_token
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def logout(principal: PrincipalDep, response: Response, db: DbDep) -> None:
    """End the current session and clear the cookie."""
    end_session(db, principal.session_id)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    security_event(log, "logout", username=principal.username)


@me_router.get("/me", responses={401: {"model": ErrorResponse}})
def me(principal: PrincipalDep) -> MeResponse:
    """The signed-in user and the CSRF token to send on unsafe requests."""
    return MeResponse(
        username=principal.username,
        display_name=principal.display_name,
        csrf_token=principal.csrf_token,
    )


__all__ = ["authenticated", "me_router", "router"]
