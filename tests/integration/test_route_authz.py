"""Every API route declares one policy and has allowed and denied test cases.

Adding a route without adding it to ``CASES`` fails this module. That is the brief's
rule "CI fails if any API route lacks an authorization test".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.api.app import create_app
from dsec_metrics.api.policy import policy_of
from dsec_metrics.auth.users import ensure_local_user, find_user
from dsec_metrics.config import Mode, Settings
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import AuditorGrant
from tests.conftest import TEST_PASSWORD, TEST_USER, load_demo, login

pytestmark = pytest.mark.integration

# Framework routes that exist only in development mode and are not APIRoutes.
DEV_DOC_ROUTES = {"/api/docs", "/api/openapi.json"}


AUDITOR = "route-auditor"
REPORT = {"report_type": "management", "period_start": "2026-09-01", "period_end": "2026-09-30"}


@dataclass(frozen=True)
class Case:
    policy: str
    json: dict[str, Any] | None = field(default=None)
    # A concrete URL for routes with path parameters. "{measurement_id}" and "{sha256}"
    # are filled from the demo data at test time.
    url: str | None = None
    needs_data: bool = False


CASES: dict[tuple[str, str], Case] = {
    ("GET", "/api/healthz"): Case("public"),
    ("GET", "/api/readyz"): Case("public"),
    ("GET", "/api/meta"): Case("public"),
    ("POST", "/api/auth/login"): Case(
        "public", json={"username": TEST_USER, "password": TEST_PASSWORD}
    ),
    ("POST", "/api/auth/logout"): Case("authenticated"),
    ("GET", "/api/me"): Case("authenticated"),
    ("GET", "/api/metrics"): Case("staff"),
    ("GET", "/api/metrics/{metric_id}"): Case("staff", url="/api/metrics/KRI-01", needs_data=True),
    ("GET", "/api/metrics/{metric_id}/measurements"): Case(
        "staff", url="/api/metrics/KRI-01/measurements", needs_data=True
    ),
    ("GET", "/api/measurements/{measurement_id}"): Case(
        "staff", url="/api/measurements/{measurement_id}", needs_data=True
    ),
    ("GET", "/api/batches/{sha256}"): Case("staff", url="/api/batches/{sha256}", needs_data=True),
    ("GET", "/api/controls"): Case("staff"),
    ("GET", "/api/controls/{control_id}"): Case(
        "staff", url="/api/controls/DS-KM-01", needs_data=True
    ),
    ("GET", "/api/exceptions"): Case("staff"),
    ("GET", "/api/findings"): Case("staff"),
    ("GET", "/api/dashboards"): Case("staff"),
    ("GET", "/api/dashboards/{dashboard_id}"): Case(
        "staff", url="/api/dashboards/risk-committee", needs_data=True
    ),
    ("GET", "/api/reports"): Case("authenticated"),
    ("POST", "/api/reports"): Case("author", json=REPORT, needs_data=True),
    ("GET", "/api/reports/public-key"): Case("authenticated"),
    ("GET", "/api/reports/{package_id}"): Case("authenticated", needs_data=True),
    ("GET", "/api/reports/{package_id}/download"): Case("authenticated", needs_data=True),
    ("POST", "/api/reports/{package_id}/links"): Case(
        "author", json={"username": AUDITOR}, needs_data=True
    ),
    ("GET", "/api/links/{token}"): Case("authenticated", needs_data=True),
    ("GET", "/api/audit-room"): Case("authenticated"),
    ("GET", "/api/audit/events"): Case("admin"),
    ("GET", "/api/audit/verify"): Case("admin"),
}


def _auditor(factory: sessionmaker[Session]) -> None:
    """An auditor with a grant covering the test report."""
    with transaction(factory) as db:
        ensure_local_user(db, AUDITOR, TEST_PASSWORD, "Auditor", ("auditor",))
        found = find_user(db, AUDITOR)
        assert found is not None
        db.add(
            AuditorGrant(
                user_id=found.id,
                frameworks=["pci-dss-4.0.1", "nist-csf-2.0", "iso-27001-2022", "soc2-tsc"],
                period_start=date(2026, 1, 1),
                period_end=date(2026, 12, 31),
                expires_at=datetime.now(UTC) + timedelta(days=1),
                created_by="test",
            )
        )


def _url(client: TestClient, path: str, case: Case, headers: dict[str, str]) -> str:
    url = case.url or path
    if "{" not in url:
        return url
    values: dict[str, str] = {}
    if "{measurement_id}" in url or "{sha256}" in url:
        measurement = client.get("/api/metrics/KRI-01").json()["latest"]
        detail = client.get(f"/api/measurements/{measurement['measurement_id']}").json()
        values["measurement_id"] = str(measurement["measurement_id"])
        values["sha256"] = detail["batches"][0]["sha256"]
    if "{package_id}" in url or "{token}" in url:
        created = client.post("/api/reports", json=REPORT, headers=headers)
        assert created.status_code == 201, created.text
        values["package_id"] = created.json()["id"]
    if "{token}" in url:
        link = client.post(
            f"/api/reports/{values['package_id']}/links",
            json={"username": AUDITOR},
            headers=headers,
        )
        assert link.status_code == 201, link.text
        values["token"] = link.json()["url"].rsplit("/", 1)[1]
    return url.format(**values)


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
def test_allowed(
    client: TestClient,
    user: str,
    session_factory: sessionmaker[Session],
    method: str,
    path: str,
) -> None:
    case = CASES[(method, path)]
    if case.needs_data:
        load_demo(session_factory, months=1)
        _auditor(session_factory)
    headers: dict[str, str] = {}
    if case.policy != "public":
        headers["X-CSRF-Token"] = login(client)
    url = _url(client, path, case, headers)
    if path == "/api/links/{token}":
        # A link works only for the auditor it was made for.
        client.cookies.clear()
        headers["X-CSRF-Token"] = login(client, AUDITOR)
    response = client.request(method, url, json=case.json, headers=headers)
    assert 200 <= response.status_code < 300, response.text


@pytest.mark.parametrize(("method", "path"), sorted(CASES))
def test_denied(client: TestClient, user: str, method: str, path: str) -> None:
    case = CASES[(method, path)]
    url = (case.url or path).format(
        measurement_id=1,
        sha256="0" * 64,
        package_id="00000000-0000-0000-0000-000000000000",
        token="x" * 43,
    )
    response = client.request(method, url, json=case.json)
    if case.policy == "public":
        # Public routes must not demand credentials; denial is not applicable.
        assert response.status_code not in (401, 403)
    else:
        assert response.status_code == 401


ROLE_POLICIES = {"staff", "author", "admin"}


@pytest.mark.parametrize(
    ("method", "path"), sorted(k for k, c in CASES.items() if c.policy in ROLE_POLICIES)
)
def test_forbidden_without_the_role(
    client: TestClient, session_factory: sessionmaker[Session], method: str, path: str
) -> None:
    """A signed-in user whose roles do not include the policy's gets 403."""
    case = CASES[(method, path)]
    with transaction(session_factory) as db:
        # An auditor is signed in but is none of staff, author or admin.
        ensure_local_user(db, AUDITOR, TEST_PASSWORD, "Auditor", ("auditor",))
    token = login(client, AUDITOR)
    url = (case.url or path).format(
        measurement_id=1, sha256="0" * 64, package_id="00000000-0000-0000-0000-000000000000"
    )
    response = client.request(method, url, json=case.json, headers={"X-CSRF-Token": token})
    assert response.status_code == 403, response.text


def test_production_hides_openapi(db_settings: Settings, tmp_path: Any) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text("unused", encoding="utf-8")
    prod = db_settings.model_copy(
        update={"mode": Mode.PRODUCTION, "local_accounts": False, "db_sslrootcert": ca}
    )
    prod = prod.model_copy(update={"db_sslmode": "verify-full"})
    app = create_app(prod)
    assert _other_paths(app) == set()
