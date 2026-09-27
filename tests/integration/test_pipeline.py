from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dsec_metrics.content import Content, load_content
from dsec_metrics.core.definitions import CollectorInstance, Metric
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import (
    Base,
    CollectionRun,
    DefinitionVersion,
    MeasurementRow,
    RecordBatchRow,
)
from dsec_metrics.pipeline import (
    evaluate_all,
    latest_status,
    run_collection,
    run_period,
    sync_definitions,
)
from dsec_metrics.plugins.sdk.registry import default_secret_resolver
from tests.conftest import CONTENT_DIR

pytestmark = pytest.mark.integration
AS_OF = date(2026, 3, 31)
PANS = ["4111111111111111", "5555555555554444", "378282246310005", "6011111111111117"]


@pytest.fixture
def content() -> Content:
    loaded = load_content(CONTENT_DIR)
    assert loaded.ok
    return loaded


def test_period_collects_evaluates_and_is_idempotent(
    session_factory: sessionmaker[Session], content: Content
) -> None:
    secrets = default_secret_resolver()
    with transaction(session_factory) as db:
        stats = run_period(db, content, AS_OF, secrets)
    assert stats["runs"] == 14
    assert stats["failed_runs"] == 0
    assert stats["measurements"] > 16
    with transaction(session_factory) as db:
        again = run_period(db, content, AS_OF, secrets)
    # Collections run again (new batches), but identical measurements are not duplicated.
    assert again["measurements"] == 0
    with session_factory() as db:
        lines = {line.metric_id: line for line in latest_status(db, content)}
        assert len(lines) == 16
        assert lines["KRI-04"].status == "red"  # the key rotation backlog in month six
        assert lines["KRI-04"].value == 12
        row = db.scalars(
            select(MeasurementRow).where(
                MeasurementRow.metric_id == "KRI-03", MeasurementRow.dims_key == "{}"
            )
        ).one()
        assert row.definition_version == 1
        assert len(row.input_batch_hashes) == 1
        assert row.calculation["kind"] == "count"
        batch = db.scalars(
            select(RecordBatchRow).where(RecordBatchRow.sha256 == row.input_batch_hashes[0])
        ).first()
        assert batch is not None
        assert batch.storage_ref == "db:inline"


def test_card_numbers_never_reach_the_database(
    session_factory: sessionmaker[Session], engine: object, tmp_path: Path, content: Content
) -> None:
    """Luhn-valid numbers go in through every collector path; none may come out unmasked."""
    (tmp_path / "pans.csv").write_text(
        "id,note,pan\n" + "\n".join(f"{i},seen {p} in logs,{p}" for i, p in enumerate(PANS)),
        encoding="utf-8",
    )
    (tmp_path / "pans.json").write_text(
        json.dumps(
            [
                {
                    "nested": {"list": [f"x {p[:4]} {p[4:8]} {p[8:]} y"]},
                    "n": int(p),
                    "f": float(p),
                    "by_card": {p: 1},
                }
                for p in PANS
            ]
        ),
        encoding="utf-8",
    )
    file_instance = CollectorInstance(
        id="files",
        plugin="file",
        config={"base_dir": str(tmp_path), "files": {"csv": "pans.csv", "json": "pans.json"}},
    )
    secrets = default_secret_resolver()
    with transaction(session_factory) as db:
        for query in ("csv", "json"):
            assert run_collection(db, file_instance, query, AS_OF, secrets).pans_masked >= len(PANS)
        for query in ("card_data_scans", "findings"):
            run_collection(db, content.collectors["sample"], query, AS_OF, secrets)
        evaluate_all(db, content, sync_definitions(db, content), AS_OF)
    with session_factory() as db:
        # Every row of every table the application owns, as text.
        dumped = " ".join(
            json.dumps([list(row) for row in db.execute(select(table)).all()], default=str)
            for table in Base.metadata.sorted_tables
        )
        assert "record_batches" in Base.metadata.tables
        normalized = dumped.replace(" ", "").replace("-", "")
        for pan in PANS:
            assert pan not in normalized
        assert "411111******1111" in dumped
        # The field name appears in redaction summaries as a count, never with a value.
        assert '"card_holder_name": "' not in dumped
        assert re.search(r'"card_holder_name": [0-9]+', dumped)


def test_failed_collection_is_recorded(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    broken = CollectorInstance(
        id="broken", plugin="file", config={"base_dir": str(tmp_path), "files": {"x": "x.json"}}
    )
    with transaction(session_factory) as db:
        result = run_collection(db, broken, "x", AS_OF, default_secret_resolver())
    assert result.status == "failed"
    assert result.error is not None
    with session_factory() as db:
        run = db.scalars(select(CollectionRun)).one()
        assert run.status == "failed"
        assert run.error is not None
        assert db.scalar(select(func.count()).select_from(RecordBatchRow)) == 0


def test_changing_a_definition_adds_a_version_and_keeps_history(
    session_factory: sessionmaker[Session], content: Content
) -> None:
    secrets = default_secret_resolver()
    with transaction(session_factory) as db:
        run_period(db, content, AS_OF, secrets)
    changed = content.metrics["KRI-03"].model_copy(update={"action_when_red": "Escalate sooner."})
    edited = Content(
        **{
            **content.__dict__,
            "metrics": {**content.metrics, "KRI-03": Metric.model_validate(changed.model_dump())},
        }
    )
    with transaction(session_factory) as db:
        current = sync_definitions(db, edited)
        assert current[("metric", "KRI-03")].version == 2
        assert evaluate_all(db, edited, current, AS_OF, ["KRI-03"]) > 0
    with session_factory() as db:
        versions = db.execute(
            select(DefinitionVersion.version, DefinitionVersion.current)
            .where(DefinitionVersion.def_id == "KRI-03")
            .order_by(DefinitionVersion.version)
        ).all()
        assert [tuple(v) for v in versions] == [(1, False), (2, True)]
        by_version = db.execute(
            select(MeasurementRow.definition_version, func.count())
            .where(MeasurementRow.metric_id == "KRI-03", MeasurementRow.as_of == AS_OF)
            .group_by(MeasurementRow.definition_version)
        ).all()
        assert {row[0] for row in by_version} == {1, 2}


def test_previous_period_deltas(session_factory: sessionmaker[Session], content: Content) -> None:
    secrets = default_secret_resolver()
    for period in (date(2026, 2, 28), AS_OF):
        with transaction(session_factory) as db:
            run_period(db, content, period, secrets)
    with session_factory() as db:
        feb, mar = (
            db.scalars(
                select(MeasurementRow.value).where(
                    MeasurementRow.metric_id == "KRI-04",
                    MeasurementRow.dims_key == "{}",
                    MeasurementRow.as_of == d,
                )
            ).one()
            for d in (date(2026, 2, 28), AS_OF)
        )
        delta = db.scalars(
            select(MeasurementRow.delta_previous).where(
                MeasurementRow.metric_id == "KRI-04",
                MeasurementRow.dims_key == "{}",
                MeasurementRow.as_of == AS_OF,
            )
        ).one()
        assert feb is not None
        assert mar is not None
        assert delta == mar - feb
