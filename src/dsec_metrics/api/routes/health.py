"""Liveness and readiness."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from dsec_metrics.api.policy import public
from dsec_metrics.api.schemas import HealthResponse
from dsec_metrics.db.engine import ping

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get(
    "/healthz",
    dependencies=[Depends(public("container liveness probe, reveals nothing"))],
)
def healthz() -> HealthResponse:
    """The process is up. Checks nothing else."""
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    dependencies=[Depends(public("readiness probe for the proxy and orchestrator"))],
    responses={503: {"description": "Database unreachable"}},
)
def readyz(request: Request) -> HealthResponse:
    """The API can reach the database."""
    try:
        ping(request.app.state.engine)
    except SQLAlchemyError:
        log.warning("readiness check failed", extra={"event": "readyz_failed"})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Not ready") from None
    return HealthResponse(status="ready")
