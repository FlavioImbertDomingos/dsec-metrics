"""Read API against the 12-month demo dataset, loaded once for the module."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from dsec_metrics.api.app import create_app
from dsec_metrics.auth.users import ensure_local_user
from dsec_metrics.config import Settings
from dsec_metrics.db.engine import make_session_factory, transaction
from tests.conftest import TEST_ORIGIN, TEST_PASSWORD, TEST_USER, load_demo, login, truncate_all

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def api(engine: Engine, db_settings: Settings) -> Iterator[TestClient]:
    truncate_all(engine)
    factory = make_session_factory(engine)
    load_demo(factory, months=12)
    with transaction(factory) as db:
        ensure_local_user(db, TEST_USER, TEST_PASSWORD, "Test User", ("admin",))
    settings = db_settings.model_copy(update={"rate_limit_per_address": 100_000})
    app = create_app(settings)
    with TestClient(app, base_url=TEST_ORIGIN, headers={"Origin": TEST_ORIGIN}) as client:
        login(client)
        yield client
    truncate_all(engine)


def get(api: TestClient, path: str, **params: Any) -> Any:
    response = api.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_lists_every_metric_with_latest_status(api: TestClient) -> None:
    metrics = get(api, "/api/metrics")
    assert len(metrics) == 16
    by_id = {m["id"]: m for m in metrics}
    assert by_id["KRI-06"]["latest"]["status"] == "red"
    assert by_id["KRI-06"]["latest"]["value"] == 7
    assert by_id["KCI-02"]["latest"]["status"] == "amber"
    assert by_id["KRI-01"]["latest"]["as_of"] == "2026-09-30"
    kris = get(api, "/api/metrics", type="kri")
    assert {m["type"] for m in kris} == {"kri"}
    committee = get(api, "/api/metrics", audience="risk_committee")
    assert all("risk_committee" in m["audience"] for m in committee)


def test_metric_detail_links_frameworks_controls_and_versions(api: TestClient) -> None:
    detail = get(api, "/api/metrics/KRI-06")
    assert detail["version"] == 1
    assert len(detail["sha256"]) == 64
    assert detail["versions"][0]["current"] is True
    assert detail["bands"]["red"] == {"min": None, "max": None, "above": 6.0, "below": None}
    refs = {f["ref"]: f for f in detail["frameworks"]}
    assert refs["pci-dss-4.0.1:8.6.3"]["short_title"]
    assert detail["controls"]
    assert detail["definition"]["id"] == "KRI-06"
    assert detail["group_by"] == ["business_unit"]


def test_history_and_slices(api: TestClient) -> None:
    history = get(api, "/api/metrics/KRI-06/measurements")
    assert len(history["points"]) == 12
    assert history["points"][-1]["as_of"] == "2026-09-30"
    units = {s["dimensions"]["business_unit"] for s in history["slices"]}
    assert units == {"cards", "payments", "retail"}

    cards = get(api, "/api/metrics/KRI-06/measurements", business_unit="cards", periods=3)
    assert cards["dimensions"] == {"business_unit": "cards"}
    assert cards["applied_filters"] == {"business_unit": "cards"}
    assert len(cards["points"]) == 3
    assert cards["points"][-1]["value"] <= history["points"][-1]["value"]

    region = get(api, "/api/metrics/KRI-06/measurements", region="emea")
    assert region["dimensions"] == {}
    assert region["ignored_filters"] == ["region"]


def test_measurement_and_batch_drill_down(api: TestClient) -> None:
    point = get(api, "/api/metrics/KRI-07")["latest"]
    measurement = get(api, f"/api/measurements/{point['measurement_id']}")
    assert measurement["metric_id"] == "KRI-07"
    assert measurement["calculation"]
    assert measurement["missing_batches"] == []
    batch = measurement["batches"][0]
    assert batch["query"] == "card_data_scans"
    assert batch["redaction"]["pans_masked"] > 0

    page = get(api, f"/api/batches/{batch['sha256']}", limit=5)
    assert page["total"] == batch["record_count"]
    assert len(page["records"]) == 5
    second = get(api, f"/api/batches/{batch['sha256']}", limit=5, offset=5)
    assert second["records"] != page["records"]
    text = str(page["records"])
    assert "******" in text
    assert "card_holder_name" not in text


def test_controls_roll_up_status_and_registers(api: TestClient) -> None:
    controls = get(api, "/api/controls")
    assert len(controls) == 40
    assert {c["status"] for c in controls} <= {"green", "amber", "red", "unknown"}
    assert sum(c["open_exceptions"] for c in controls) > 0
    target = next(c for c in controls if c["open_findings"] > 0)
    detail = get(api, f"/api/controls/{target['id']}")
    assert detail["findings"]
    assert all(f["control_id"] == target["id"] for f in detail["findings"])
    assert detail["requirements"]
    assert all(e["latest"] for e in detail["evidence"])


def test_exceptions_register(api: TestClient) -> None:
    register = get(api, "/api/exceptions")
    assert register["source"]["as_of"] == "2026-09-30"
    assert register["skipped"] == 0
    items = register["items"]
    assert items
    assert all(i["age_days"] is not None for i in items)
    cards = get(api, "/api/exceptions", business_unit="cards")["items"]
    assert cards
    assert {i["business_unit"] for i in cards} == {"cards"}
    expired = get(api, "/api/exceptions", status="expired")["items"]
    assert all(i["status"] == "expired" for i in expired)
    findings = get(api, "/api/findings", severity="high")
    assert {i["severity"] for i in findings["items"]} == {"high"}


@pytest.mark.parametrize("dashboard_id", ["team-operations", "management", "risk-committee"])
def test_dashboards_resolve_every_widget(api: TestClient, dashboard_id: str) -> None:
    dashboard = get(api, f"/api/dashboards/{dashboard_id}")
    assert dashboard["as_of"] == "2026-09-30"
    assert dashboard["dimensions"]["business_unit"] == ["cards", "payments", "retail"]
    for widget in dashboard["widgets"]:
        assert widget["title"]
        kind = widget["widget"]
        if kind in {"stat", "table", "rag_list"}:
            assert widget["points"]
            assert all(p is not None for p in widget["points"].values())
        if kind in {"trend", "findings_burndown"}:
            assert all(len(s["points"]) == 12 for s in widget["series"])
        if kind in {"bar", "heatmap"}:
            assert widget["cells"]
            assert all(c["measurement_id"] for c in widget["cells"])
        if kind == "exceptions_aging":
            assert sum(b["count"] for b in widget["buckets"]) > 0


def test_dashboard_filters_say_when_they_do_not_apply(api: TestClient) -> None:
    cards = get(api, "/api/dashboards/risk-committee", business_unit="cards")
    heatmap = next(w for w in cards["widgets"] if w["widget"] == "heatmap")
    assert heatmap["rows"] == ["cards"]
    by_region = get(api, "/api/dashboards/risk-committee", region="emea")
    rag = next(w for w in by_region["widgets"] if w["widget"] == "rag_list")
    assert rag["filtered"] is False
    assert "not broken down by region" in rag["note"]


def test_listing_dashboards(api: TestClient) -> None:
    listed = get(api, "/api/dashboards")
    assert [d["id"] for d in listed] == ["management", "risk-committee", "team-operations"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/metrics/KRI-99",
        "/api/measurements/999999999",
        "/api/batches/" + "0" * 64,
        "/api/controls/DS-XX-99",
        "/api/dashboards/nope",
    ],
)
def test_unknown_ids_are_404_without_echo(api: TestClient, path: str) -> None:
    response = api.get(path)
    assert response.status_code == 404
    assert path.rsplit("/", 1)[1] not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/metrics/not-an-id",
        "/api/batches/xyz",
        "/api/metrics?type=bogus",
        "/api/dashboards/risk-committee?business_unit=%3Cscript%3E",
        "/api/metrics/KRI-06/measurements?periods=500",
    ],
)
def test_bad_parameters_are_rejected(api: TestClient, path: str) -> None:
    assert api.get(path).status_code == 422


def test_dashboard_latency_p95_under_300ms(api: TestClient) -> None:
    """The brief's target, measured on the 12-month sample dataset."""
    for dashboard_id in ("team-operations", "management", "risk-committee"):
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            assert api.get(f"/api/dashboards/{dashboard_id}").status_code == 200
            timings.append(time.perf_counter() - start)
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        assert p95 < 0.3, f"{dashboard_id} p95 {p95 * 1000:.0f} ms"
