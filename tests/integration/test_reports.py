"""Every report type builds from the 12-month demo data, verifies, and can be reproduced."""

from __future__ import annotations

import io
import json
import time
import zipfile
from collections.abc import Iterator
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics import audit
from dsec_metrics.db.engine import make_session_factory, transaction
from dsec_metrics.db.models import ReportPackage
from dsec_metrics.plugins.renderers.pdf import PdfRenderer
from dsec_metrics.reports.builder import generate, reproduce
from dsec_metrics.reports.data import ReportError, ReportRequest, ReportType
from dsec_metrics.reports.signing import SigningKey, public_pem
from dsec_metrics.reports.verify import verify_package
from tests.conftest import load_demo, truncate_all

pytestmark = pytest.mark.integration

Q3 = {"period_start": date(2026, 7, 1), "period_end": date(2026, 9, 30)}
KEY = SigningKey(Ed25519PrivateKey.generate())


@pytest.fixture(scope="module")
def factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    truncate_all(engine)
    f = make_session_factory(engine)
    load_demo(f, months=12)
    yield f
    truncate_all(engine)


def build(factory: sessionmaker[Session], **kwargs: object) -> bytes:
    request = ReportRequest.model_validate({**Q3, "prepared_for": "Example Audit LLP", **kwargs})
    with transaction(factory) as db:
        generated = generate(db, request, KEY, "tester")
        return generated.built.content


@pytest.mark.parametrize(
    "kwargs",
    [
        {"report_type": "control", "control_id": "DS-KM-01"},
        {"report_type": "framework", "framework": "pci-dss-4.0.1", "requirements": ["3", "8"]},
        {"report_type": "reproducibility", "metric_id": "KRI-06"},
        {"report_type": "risk_committee"},
        {"report_type": "management"},
        {"report_type": "exceptions"},
    ],
    ids=lambda k: str(k["report_type"]),
)
def test_every_report_type_builds_and_verifies(
    factory: sessionmaker[Session], kwargs: dict[str, object]
) -> None:
    start = time.perf_counter()
    content = build(factory, **kwargs)
    elapsed = time.perf_counter() - start
    assert elapsed < 20, f"took {elapsed:.1f}s"
    result = verify_package(io.BytesIO(content), public_key=public_pem(KEY.public).encode())
    assert result.ok, result.problems
    assert result.pinned
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert {"report.xlsx", "report.json", "manifest.json", "manifest.sig"} <= names
    assert ("report.pdf" in names) == PdfRenderer().available()
    assert ("report.html" in names) != PdfRenderer().available()
    assert any(n.startswith("evidence/batches/") for n in names)
    assert manifest["report"]["type"] == kwargs["report_type"]
    assert manifest["report"]["prepared_for"] == "Example Audit LLP"
    assert manifest["report"]["frameworks"]
    for entry in manifest["files"]:
        assert entry["source"]
    # Nothing unmasked leaves in a package either.
    assert b"4111111111111111" not in content


def test_control_package_contents(factory: sessionmaker[Session]) -> None:
    content = build(factory, report_type="control", control_id="DS-SM-02")
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        batches = [n for n in zf.namelist() if n.startswith("evidence/batches/")]
        doc = json.loads(zf.read(batches[0]))
        report = json.loads(zf.read("report.json"))
    assert doc["records"]
    assert doc["as_of"] <= "2026-09-30"
    assert report["tables"]["controls"][0]["control_id"] == "DS-SM-02"
    entry = next(f for f in manifest["files"] if f["path"] == batches[0])
    assert entry["record"]["batch_sha256"] == doc["sha256"]
    assert entry["collected_at"]
    assert manifest["report"]["measurements"]


def test_reproducibility_package_recomputes(factory: sessionmaker[Session]) -> None:
    content = build(factory, report_type="reproducibility", metric_id="KRI-06")
    result = reproduce(content)
    assert result.ok, result.problems
    assert result.recomputed == result.expected == 7
    assert result.recomputed_status == "red"
    assert not reproduce(build(factory, report_type="management")).ok


def test_same_inputs_give_the_same_files(factory: sessionmaker[Session]) -> None:
    def hashes(content: bytes) -> dict[str, str]:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            files = json.loads(zf.read("manifest.json"))["files"]
        return {f["path"]: f["sha256"] for f in files if f["path"].startswith("evidence/")}

    a = build(factory, report_type="control", control_id="DS-SM-02")
    b = build(factory, report_type="control", control_id="DS-SM-02")
    assert hashes(a) == hashes(b)


def test_packages_are_stored_and_audited(factory: sessionmaker[Session]) -> None:
    before = 0
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(ReportPackage)) or 0
    build(factory, report_type="exceptions")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReportPackage)) == before + 1
        assert audit.verify_chain(db).ok


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"report_type": "control", "control_id": "DS-XX-99"}, "unknown control"),
        ({"report_type": "framework", "framework": "nope"}, "unknown framework"),
        (
            {"report_type": "framework", "framework": "pci-dss-4.0.1", "requirements": ["99"]},
            "no control maps",
        ),
        ({"report_type": "reproducibility", "metric_id": "KRI-99"}, "unknown metric"),
        (
            {
                "report_type": "reproducibility",
                "metric_id": "KRI-06",
                "period_start": date(2020, 1, 1),
                "period_end": date(2020, 3, 31),
            },
            "no measurement",
        ),
        (
            {
                "report_type": "exceptions",
                "period_start": date(2020, 1, 1),
                "period_end": date(2020, 3, 31),
            },
            "no collection in the period",
        ),
    ],
)
def test_bad_requests(
    factory: sessionmaker[Session], kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ReportError, match=message):
        build(factory, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"report_type": "control"}, "need control_id"),
        ({"report_type": "framework"}, "need framework"),
        ({"report_type": "reproducibility"}, "need metric_id"),
        ({"report_type": "management", "period_end": date(2026, 1, 1)}, "before"),
        ({"report_type": "management", "period_start": date(2020, 1, 1)}, "two years"),
        ({"report_type": "framework", "framework": "x", "requirements": ["a b"]}, "requirement"),
    ],
)
def test_request_validation(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ReportRequest.model_validate({**Q3, **kwargs})
    assert ReportType.CONTROL.value == "control"
