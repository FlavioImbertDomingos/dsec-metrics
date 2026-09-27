"""Request size and rate limits applied to every request before routing.

Being middleware, the limits cover every path, including unknown ones and the public
routes. If the counter table cannot be reached the request goes through and a warning is
logged: every route except the health checks needs the database anyway, and failing
closed would turn a counter problem into an outage.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dsec_metrics.auth.ratelimit import (
    WINDOW,
    address_key,
    count_request,
    session_key,
    window_start,
)
from dsec_metrics.auth.sessions import COOKIE_NAME
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import transaction
from dsec_metrics.logs import security_event

log = logging.getLogger(__name__)

Handler = Callable[[Request], Awaitable[Response]]


def _count(factory: sessionmaker[Session], keys: list[str], now: datetime) -> dict[str, int]:
    with transaction(factory) as db:
        return count_request(db, keys, now)


def _error(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


async def enforce_limits(request: Request, call_next: Handler) -> Response:
    """Reject oversized bodies (413, or 411 without a length) and over-limit clients (429)."""
    settings: Settings = request.app.state.settings
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > settings.max_request_bytes):
        return _error(413, "Request body too large")
    if length is None and request.headers.get("transfer-encoding"):
        return _error(411, "Content-Length required")

    address = request.client.host if request.client else "unknown"
    limits = {address_key(address): settings.rate_limit_per_address}
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        limits[session_key(cookie)] = settings.rate_limit_per_session

    now = datetime.now(UTC)
    try:
        counts = await run_in_threadpool(
            _count, request.app.state.session_factory, list(limits), now
        )
    except SQLAlchemyError as exc:
        log.warning(
            "rate limit counters unavailable",
            extra={"event": "rate_limit_unavailable", "error": type(exc).__name__},
        )
        return await call_next(request)

    over = [key for key, limit in limits.items() if counts.get(key, 0) > limit]
    if over:
        # Log once per key and window, not once per rejected request.
        if any(counts[key] == limits[key] + 1 for key in over):
            security_event(
                log,
                "rate_limited",
                source=address,
                scope="session" if any(k.startswith("s:") for k in over) else "address",
                path=request.url.path,
            )
        retry = int((window_start(now) + WINDOW - now).total_seconds()) + 1
        return _error(429, "Too many requests", {"Retry-After": str(retry)})
    return await call_next(request)
