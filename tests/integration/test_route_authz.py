"""Every API route declares one policy and has allowed and denied test cases.

Adding a route without adding it to ``CASES`` fails this module. That is the brief's
rule "CI fails if any API route lacks an authorization test".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from dsec_metrics.api.app import create_app
from dsec_metrics.api.policy import policy_of
from dsec_metrics.config import Mode, Settings
from tests.conftest import TEST_PASSWORD, TEST_USER, login

pytestmark = pytest.mark.integration

# Framework routes that exist only in development mode and are not APIRoutes.
DEV_DOC_ROUTES = {"/api/docs", "/api/openapi.json"}


@dataclass(frozen=True)
class Case:
    policy: str
    json: dict[str, Any] | None = field(default=None)


CASES: dict[tuple[str, str], Case] = {
    ("GET", "/api/healthz"): Case("public"),
    ("GET", "/api/readyz"): Case("public"),
    ("GET", "/api/meta"): Case("public"),
    ("POST", "/api/auth/login"): Case(
        "public", json={"username": TEST_USER, "password": TEST_PASSWORD}
    ),
    ("POST", "/api/auth/logout"): Case("authenticated"),
    ("GET", "/api/me"): Case("authenticated"),
}


def _policies(dependant: Dependant) -> list[str]:
    found: list[str] = []
    for dep in dependant.dependencies:
        name = policy_of(dep.call)
        if name is not None:
            found.append(name)
        found.extend(_policies(dep))
    return found


def _api_routes(app: FastAPI) -> dict[tuple[str, str], Dependant]:
    """Map (method, path) to the effective dependency tree, router dependencies included."""
    routes: dict[tuple[str, str], Dependant] = {}
    for ctx in iter_route_contexts(app.routes):
        if isinstance(ctx.original_route, APIRoute) and ctx.path and ctx.methods:
            dependant: Dependant = getattr(ctx, "dependant")  # noqa: B009
            for method in ctx.methods:
                routes[(method, ctx.path)] = dependant
    return routes


def _other_paths(app: FastAPI) -> set[str]:
    return {
        ctx.path or ""
        for ctx in iter_route_contexts(app.routes)
        if not isinstance(ctx.original_route, APIRoute)
    }


@pytest.fixture
def app(client: TestClient) -> FastAPI:
    assert isinstance(client.app, FastAPI)
    return client.app


def test_every_route_has_a_case(app: FastAPI) -> None:
    assert set(_api_routes(app)) == set(CASES)


def test_no_unexpected_non_api_routes(app: FastAPI) -> None:
    assert _other_paths(app) <= DEV_DOC_ROUTES


def test_every_route_declares_exactly_one_policy(app: FastAPI) -> None:
    for key, dependant in _api_routes(app).items():
        policies = _policies(dependant)
        assert len(policies) == 1, f"{key} declares {policies or 'no policy'}"
        assert policies[0] == CASES[key].policy, f"{key} policy mismatch"


@pytest.mark.parametrize(("method", "path"), sorted(CASES))
def test_allowed(client: TestClient, user: str, method: str, path: str) -> None:
    case = CASES[(method, path)]
    headers: dict[str, str] = {}
    if case.policy == "authenticated":
        headers["X-CSRF-Token"] = login(client)
    response = client.request(method, path, json=case.json, headers=headers)
    assert 200 <= response.status_code < 300, response.text


@pytest.mark.parametrize(("method", "path"), sorted(CASES))
def test_denied(client: TestClient, user: str, method: str, path: str) -> None:
    case = CASES[(method, path)]
    response = client.request(method, path, json=case.json)
    if case.policy == "public":
        # Public routes must not demand credentials; denial is not applicable.
        assert response.status_code not in (401, 403)
    else:
        assert response.status_code == 401


def test_production_hides_openapi(db_settings: Settings, tmp_path: Any) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text("unused", encoding="utf-8")
    prod = db_settings.model_copy(
        update={"mode": Mode.PRODUCTION, "local_accounts": False, "db_sslrootcert": ca}
    )
    prod = prod.model_copy(update={"db_sslmode": "verify-full"})
    app = create_app(prod)
    assert _other_paths(app) == set()
