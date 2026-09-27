"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from dsec_metrics.__about__ import PRODUCT_NAME, __version__
from dsec_metrics.api.limits import enforce_limits
from dsec_metrics.api.routes import auth, health, meta
from dsec_metrics.config import Mode, Settings, get_settings, validate_startup
from dsec_metrics.db.engine import make_engine, make_session_factory
from dsec_metrics.logs import configure_logging

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Raises :class:`~dsec_metrics.config.StartupError` on unsafe settings."""
    settings = settings or get_settings()
    validate_startup(settings)
    dev = settings.mode is Mode.DEVELOPMENT

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        log.info(
            "api starting",
            extra={"event": "api_start", "mode": settings.mode.value, "version": __version__},
        )
        yield
        engine.dispose()

    app = FastAPI(
        title=f"{PRODUCT_NAME} API",
        version=__version__,
        lifespan=lifespan,
        # The interactive docs are for development. The schema is published on the
        # docs site; production does not serve it.
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(auth.me_router, prefix="/api")

    # Middleware added later runs earlier: no_store wraps the limits, so 429s are not cached.
    app.middleware("http")(enforce_limits)

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations help the client; submitted values are never echoed back.
        fields = [".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()]
        body = {"detail": "Invalid request", "fields": fields}
        return JSONResponse(status_code=422, content=body)

    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn's ``--factory`` flag."""
    settings = get_settings()
    configure_logging(settings.log_level)
    return create_app(settings)
