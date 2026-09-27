from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from dsec_metrics import __version__

pytestmark = pytest.mark.integration


def test_healthz(client: TestClient) -> None:
    assert client.get("/api/healthz").json() == {"status": "ok"}


def test_readyz(client: TestClient) -> None:
    assert client.get("/api/readyz").json() == {"status": "ready"}


def test_readyz_reports_database_down(client: TestClient) -> None:
    app = client.app
    real = app.state.engine  # type: ignore[attr-defined]
    app.state.engine = create_engine(  # type: ignore[attr-defined]
        "postgresql+psycopg://x:y@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    try:
        response = client.get("/api/readyz")
    finally:
        app.state.engine.dispose()  # type: ignore[attr-defined]
        app.state.engine = real  # type: ignore[attr-defined]
    assert response.status_code == 503
    assert response.json() == {"detail": "Not ready"}


def test_meta(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert body == {"product_name": "dsec-metrics", "version": __version__, "mode": "development"}


def test_openapi_only_in_development(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
