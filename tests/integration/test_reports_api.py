"""Report packages over the API: roles, auditor grants, links and download logging."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from dsec_metrics import audit
from dsec_metrics.api.app import create_app
from dsec_metrics.auth.users import ensure_local_user, find_user
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import make_session_factory, transaction
from dsec_metrics.db.models import AuditEvent, AuditorGrant, ReportLink
from dsec_metrics.reports.signing import generate
from dsec_metrics.reports.verify import verify_package
from tests.conftest import TEST_ORIGIN, load_demo, truncate_all

pytestmark = pytest.mark.integration

PASSWORD = "a long enough password"
Q3 = {"period_start": "2026-07-01", "period_end": "2026-09-30"}


@pytest.fixture(scope="module")
def setup(
    engine: Engine, db_settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Settings]:
    truncate_all(engine)
    factory = make_session_factory(engine)
    load_demo(factory, months=3)
    private, _ = generate()
    key_file = tmp_path_factory.mktemp("keys") / "signing.pem"
    key_file.write_bytes(private)
    with transaction(factory) as db:
        for name, roles in [
            ("author", ("reviewer",)),
            ("viewer", ("viewer",)),
            ("boss", ("admin",)),
            ("pci-auditor", ("auditor",)),
            ("soc-auditor", ("auditor",)),
            ("nobody", ()),
        ]:
            ensure_local_user(db, name, PASSWORD, name, roles)
        now = datetime.now(UTC)
        pci = find_user(db, "pci-auditor")
        soc = find_user(db, "soc-auditor")
        assert pci is not None
        assert soc is not None
        db.add_all(
            [
                AuditorGrant(
                    user_id=pci.id,
                    frameworks=["pci-dss-4.0.1"],
                    period_start=date(2026, 7, 1),
                    period_end=date(2026, 12, 31),
                    expires_at=now + timedelta(days=10),
                    created_by="test",
                ),
                AuditorGrant(
                    user_id=soc.id,
                    frameworks=["soc2-tsc"],
                    period_start=date(2026, 7, 1),
                    period_end=date(2026, 12, 31),
                    expires_at=now - timedelta(days=1),  # expired
                    created_by="test",
                ),
            ]
        )
    yield db_settings.model_copy(
        update={"report_signing_key_file": key_file, "rate_limit_per_address": 100_000}
    )
    truncate_all(engine)


def client_for(settings: Settings, username: str) -> TestClient:
    client = TestClient(create_app(settings), base_url=TEST_ORIGIN, headers={"Origin": TEST_ORIGIN})
    client.__enter__()
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture(scope="module")
def clients(setup: Settings) -> Iterator[dict[str, TestClient]]:
    made = {
        name: client_for(setup, name)
        for name in ("author", "viewer", "boss", "pci-auditor", "soc-auditor", "nobody")
    }
    yield made
    for c in made.values():
        c.__exit__(None, None, None)


@pytest.fixture(scope="module")
def pci_report(clients: dict[str, TestClient]) -> dict[str, object]:
    response = clients["author"].post(
        "/api/reports",
        json={
            "report_type": "framework",
            "framework": "pci-dss-4.0.1",
            "requirements": ["3"],
            "prepared_for": "Example QSA",
            **Q3,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_authors_generate_and_everyone_on_staff_can_download(
    clients: dict[str, TestClient], pci_report: dict[str, object], setup: Settings
) -> None:
    assert pci_report["frameworks"] == ["pci-dss-4.0.1"]
    assert pci_report["generated_by"] == "author"
    listed = clients["viewer"].get("/api/reports").json()
    assert pci_report["id"] in [r["id"] for r in listed]
    download = clients["viewer"].get(f"/api/reports/{pci_report['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert "attachment" in download.headers["content-disposition"]
    key = clients["viewer"].get("/api/reports/public-key").json()
    assert key["fingerprint"] == pci_report["key_fingerprint"]
    result = verify_package(io.BytesIO(download.content), public_key=key["pem"].encode())
    assert result.ok, result.problems


def test_viewers_cannot_generate_and_bad_requests_are_explained(
    clients: dict[str, TestClient],
) -> None:
    body = {"report_type": "management", **Q3}
    assert clients["viewer"].post("/api/reports", json=body).status_code == 403
    assert clients["pci-auditor"].post("/api/reports", json=body).status_code == 403
    missing = clients["author"].post("/api/reports", json={"report_type": "control", **Q3})
    assert missing.status_code == 422
    unknown = clients["author"].post(
        "/api/reports", json={"report_type": "control", "control_id": "DS-XX-99", **Q3}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "unknown control"


def test_auditors_see_only_what_a_current_grant_covers(
    clients: dict[str, TestClient], pci_report: dict[str, object]
) -> None:
    management = clients["author"].post("/api/reports", json={"report_type": "management", **Q3})
    assert management.status_code == 201
    pci = clients["pci-auditor"]
    ids = [r["id"] for r in pci.get("/api/reports").json()]
    assert pci_report["id"] in ids
    # The management report maps to several packs, including PCI DSS, so it is covered too;
    # a report outside the grant period is not.
    older = clients["author"].post(
        "/api/reports",
        json={
            "report_type": "framework",
            "framework": "pci-dss-4.0.1",
            "period_start": "2026-07-01",
            "period_end": "2027-01-15",
        },
    )
    assert older.status_code == 201
    assert older.json()["id"] not in [r["id"] for r in pci.get("/api/reports").json()]
    assert pci.get(f"/api/reports/{older.json()['id']}").status_code == 404
    assert pci.get(f"/api/reports/{pci_report['id']}/download").status_code == 200
    # Expired grant: nothing.
    assert clients["soc-auditor"].get("/api/reports").json() == []
    assert clients["soc-auditor"].get(f"/api/reports/{pci_report['id']}").status_code == 404
    # No roles at all: refused.
    assert clients["nobody"].get("/api/reports").status_code == 403
    assert clients["nobody"].get("/api/audit-room").status_code == 403
    # Auditors are not staff.
    assert pci.get("/api/metrics").status_code == 403
    assert pci.get("/api/dashboards/risk-committee").status_code == 403


def test_links_are_personal_and_time_limited(
    clients: dict[str, TestClient], pci_report: dict[str, object], engine: Engine
) -> None:
    author = clients["author"]
    path = f"/api/reports/{pci_report['id']}/links"
    assert author.post(path, json={"username": "viewer"}).status_code == 422
    assert author.post(path, json={"username": "soc-auditor"}).status_code == 422
    assert clients["viewer"].post(path, json={"username": "pci-auditor"}).status_code == 403
    link = author.post(path, json={"username": "pci-auditor", "days": 90})
    assert link.status_code == 201
    body = link.json()
    # Capped at the grant's expiry (10 days), not the 90 asked for.
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires < datetime.now(UTC) + timedelta(days=11)
    url = body["url"]
    assert clients["pci-auditor"].get(url).status_code == 200
    assert clients["boss"].get(url).status_code == 404
    assert clients["pci-auditor"].get(url + "x").status_code == 404
    factory = make_session_factory(engine)
    with transaction(factory) as db:
        db.execute(update(ReportLink).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert clients["pci-auditor"].get(url).status_code == 404
    with factory() as db:
        stored = db.scalars(select(ReportLink.token_hash)).all()
        assert all(url.rsplit("/", 1)[1].encode() not in h for h in stored)


def test_every_download_is_in_the_audit_log(
    clients: dict[str, TestClient], pci_report: dict[str, object], engine: Engine
) -> None:
    clients["pci-auditor"].get(f"/api/reports/{pci_report['id']}/download")
    with make_session_factory(engine)() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "report.download")).all()
        assert any(e.actor == "pci-auditor" and e.details["auditor"] for e in events)
        assert all(e.target.startswith("report:") for e in events)
        assert audit.verify_chain(db).ok
    room = clients["pci-auditor"].get("/api/audit-room").json()
    assert room["auditor"] is True
    assert [g["username"] for g in room["grants"]] == ["pci-auditor"]
    assert {e["actor"] for e in room["access_log"]} == {"pci-auditor"}
    staff_room = clients["boss"].get("/api/audit-room").json()
    assert staff_room["auditor"] is False
    assert {g["username"] for g in staff_room["grants"]} == {"pci-auditor", "soc-auditor"}


def test_audit_log_is_for_admins(clients: dict[str, TestClient]) -> None:
    assert clients["viewer"].get("/api/audit/events").status_code == 403
    assert clients["pci-auditor"].get("/api/audit/verify").status_code == 403
    events = clients["boss"].get("/api/audit/events", params={"limit": 5}).json()
    assert len(events) == 5
    assert events[0]["seq"] > events[-1]["seq"]
    older = clients["boss"].get(
        "/api/audit/events", params={"before": events[-1]["seq"], "limit": 2}
    )
    assert all(e["seq"] < events[-1]["seq"] for e in older.json())
    logins = clients["boss"].get("/api/audit/events", params={"action": "auth.login"}).json()
    assert logins
    assert {e["action"] for e in logins} == {"auth.login"}
    verified = clients["boss"].get("/api/audit/verify").json()
    assert verified["ok"] is True
    assert verified["checked"] > 10


def test_no_signing_key_means_no_reports(db_settings: Settings, setup: Settings) -> None:
    unsigned = setup.model_copy(update={"report_signing_key_file": None})
    client = client_for(unsigned, "author")
    try:
        response = client.post("/api/reports", json={"report_type": "management", **Q3})
        assert response.status_code == 503
        assert client.get("/api/reports/public-key").status_code == 503
    finally:
        client.__exit__(None, None, None)
    broken = setup.model_copy(update={"report_signing_key_file": Path("/nonexistent/key.pem")})
    client = client_for(broken, "author")
    try:
        assert client.get("/api/reports/public-key").status_code == 503
    finally:
        client.__exit__(None, None, None)
