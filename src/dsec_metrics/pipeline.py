"""Services that connect content, collectors, the evaluator and the database.

Order of operations for one period: sync definitions, run collections (collect, redact,
hash, store), evaluate metrics from the stored batches, store measurements. Stored rows
are never updated: new definitions and recomputations add rows.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dsec_metrics import audit
from dsec_metrics.content import Content
from dsec_metrics.core.canonical import canonical_hash
from dsec_metrics.core.definitions import CollectorInstance, Metric, definition_hash
from dsec_metrics.core.evaluator import InputBatch, evaluate
from dsec_metrics.core.redaction import redact_records
from dsec_metrics.db.models import (
    CollectionRun,
    CollectorInstanceRow,
    DefinitionVersion,
    MeasurementRow,
    RecordBatchRow,
)
from dsec_metrics.plugins.collectors.file import FileCollector
from dsec_metrics.plugins.sdk.base import Collector, CollectorError
from dsec_metrics.plugins.sdk.registry import PluginError, collector_class
from dsec_metrics.plugins.sdk.secrets import SecretError, SecretResolver

log = logging.getLogger(__name__)


def instance_queries(instance: CollectorInstance) -> list[str] | None:
    """Queries an instance offers, or ``None`` if its plugin is not installed."""
    try:
        cls = collector_class(instance.plugin)
    except PluginError:
        return None
    if cls is FileCollector:
        files = instance.config.get("files")
        return sorted(files) if isinstance(files, dict) else []
    return sorted(cls.queries)


def build_collector(instance: CollectorInstance, secrets: SecretResolver) -> Collector:
    """Instantiate the plugin for an instance with its validated config."""
    cls = collector_class(instance.plugin)
    return cls.from_mapping(dict(instance.config), secrets)


# Definitions.


def sync_definitions(
    db: Session, content: Content, actor: str = "system"
) -> dict[tuple[str, str], DefinitionVersion]:
    """Store any new definition versions and mark the current ones. Returns current rows.
    Each new version is written to the audit log."""
    current: dict[tuple[str, str], DefinitionVersion] = {}
    for kind, def_id, definition in content.items():
        sha = definition_hash(definition)
        row = db.scalars(
            select(DefinitionVersion).where(
                DefinitionVersion.kind == kind,
                DefinitionVersion.def_id == def_id,
                DefinitionVersion.sha256 == sha,
            )
        ).first()
        if row is None:
            latest = db.scalar(
                select(func.max(DefinitionVersion.version)).where(
                    DefinitionVersion.kind == kind, DefinitionVersion.def_id == def_id
                )
            )
            row = DefinitionVersion(
                kind=kind,
                def_id=def_id,
                version=(latest or 0) + 1,
                sha256=sha,
                body=definition.model_dump(mode="json"),
                source=content.sources.get((kind, def_id)),
                current=True,
            )
            db.add(row)
            db.flush()
            audit.record(
                db,
                actor,
                "definition.version",
                f"{kind}:{def_id}",
                {"version": row.version, "sha256": sha, "source": row.source},
            )
            log.info(
                "definition stored",
                extra={
                    "event": "definition_version",
                    "kind": kind,
                    "id": def_id,
                    "version": row.version,
                },
            )
        db.execute(
            update(DefinitionVersion)
            .where(
                DefinitionVersion.kind == kind,
                DefinitionVersion.def_id == def_id,
                DefinitionVersion.id != row.id,
            )
            .values(current=False)
        )
        row.current = True
        current[(kind, def_id)] = row
    for inst in content.collectors.values():
        sync_instance(db, inst)
    return current


def sync_instance(db: Session, instance: CollectorInstance) -> CollectorInstanceRow:
    """Insert or refresh the stored copy of a collector instance."""
    cls = collector_class(instance.plugin)
    row = db.get(CollectorInstanceRow, instance.id)
    if row is None:
        row = CollectorInstanceRow(id=instance.id)
        db.add(row)
    row.plugin = instance.plugin
    row.plugin_version = cls.version
    row.config = dict(instance.config)
    row.schedule = instance.schedule
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


# Collection.


@dataclass(frozen=True)
class CollectionResult:
    """Outcome of one collection run."""

    run_id: str
    status: str
    batches: int
    records: int
    pans_masked: int
    error: str | None = None


def run_collection(
    db: Session,
    instance: CollectorInstance,
    query: str,
    as_of: date,
    secrets: SecretResolver,
    params: dict[str, Any] | None = None,
    actor: str = "system",
) -> CollectionResult:
    """Collect, redact, hash and store. A failed run is recorded, not raised. Either way
    the run is written to the audit log."""
    params = dict(params or {})
    sync_instance(db, instance)
    run = CollectionRun(
        instance_id=instance.id,
        query=query,
        params=params,
        as_of=as_of,
        started_at=datetime.now(UTC),
        status="running",
        record_count=0,
    )
    db.add(run)
    db.flush()
    total = masked = batches = 0
    try:
        collector = build_collector(instance, secrets)
        sensitive = [*collector.sensitive_fields, *instance.config.get("sensitive_fields", [])]
        for batch in collector.collect(query, params, as_of):
            records, summary = redact_records(batch.records, sensitive)
            db.add(
                RecordBatchRow(
                    run_id=run.id,
                    instance_id=instance.id,
                    collector=collector.name,
                    collector_version=collector.version,
                    query=query,
                    params=params,
                    as_of=as_of,
                    collected_at=batch.collected_at,
                    sha256=canonical_hash(records),
                    record_count=len(records),
                    redaction=summary.as_dict(),
                    storage_ref="db:inline",
                    records=records,
                )
            )
            total += len(records)
            masked += summary.pans_masked
            batches += 1
    except (CollectorError, SecretError, PluginError, ValueError) as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        _audit_run(db, actor, instance, query, as_of, run, batches, total, masked)
        log.warning(
            "collection failed",
            extra={"event": "collection_failed", "instance": instance.id, "query": query},
        )
        return CollectionResult(str(run.id), run.status, batches, total, masked, run.error)
    run.status = "succeeded"
    run.record_count = total
    run.finished_at = datetime.now(UTC)
    _audit_run(db, actor, instance, query, as_of, run, batches, total, masked)
    log.info(
        "collection finished",
        extra={
            "event": "collection_run",
            "instance": instance.id,
            "query": query,
            "records": total,
            "pans_masked": masked,
        },
    )
    return CollectionResult(str(run.id), run.status, batches, total, masked)


def _audit_run(
    db: Session,
    actor: str,
    instance: CollectorInstance,
    query: str,
    as_of: date,
    run: CollectionRun,
    batches: int,
    records: int,
    masked: int,
) -> None:
    audit.record(
        db,
        actor,
        "collection.run",
        f"collector:{instance.id}",
        {
            "run_id": str(run.id),
            "query": query,
            "as_of": as_of.isoformat(),
            "status": run.status,
            "batches": batches,
            "records": records,
            "pans_masked": masked,
        },
    )


def latest_batches(
    db: Session, instance_id: str, query: str, as_of: date
) -> tuple[list[RecordBatchRow], datetime | None]:
    """Batches from the most recent successful run for the source at or before ``as_of``."""
    run = db.scalars(
        select(CollectionRun)
        .where(
            CollectionRun.instance_id == instance_id,
            CollectionRun.query == query,
            CollectionRun.status == "succeeded",
            CollectionRun.as_of <= as_of,
        )
        .order_by(CollectionRun.as_of.desc(), CollectionRun.finished_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return [], None
    batches = list(db.scalars(select(RecordBatchRow).where(RecordBatchRow.run_id == run.id)))
    collected = max((b.collected_at for b in batches), default=run.finished_at)
    return batches, collected


# Evaluation.


def evaluate_metric(
    db: Session, metric: Metric, definition: DefinitionVersion, as_of: date
) -> list[MeasurementRow]:
    """Evaluate one metric for ``as_of`` and insert measurements that do not exist yet."""
    rows, collected_at = latest_batches(db, metric.source.collector, metric.source.query, as_of)
    batches = [InputBatch(r.sha256, r.records) for r in rows]
    previous = _previous_values(db, metric.id, as_of)
    results = evaluate(metric, batches, as_of, last_collected_at=collected_at, previous=previous)
    inserted: list[MeasurementRow] = []
    for m in results:
        values = {
            "metric_id": m.metric_id,
            "definition_id": definition.id,
            "definition_sha256": m.definition_sha256,
            "definition_version": definition.version,
            "as_of": m.as_of,
            "dims_key": m.dims_key,
            "dimensions": dict(m.dimensions),
            "value": m.value,
            "status": m.status.value,
            "input_batch_hashes": list(m.input_batch_hashes),
            "delta_previous": m.delta_previous,
            "delta_baseline": m.delta_baseline,
            "distance_to_target": m.distance_to_target,
            "calculation": dict(m.calculation),
        }
        stmt = (
            insert(MeasurementRow)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_measurements_metric_id")
            .returning(MeasurementRow.id)
        )
        new_id = db.scalar(stmt)
        if new_id is not None:
            row = db.get(MeasurementRow, new_id)
            if row is not None:
                inserted.append(row)
    return inserted


def _previous_values(db: Session, metric_id: str, as_of: date) -> dict[str, float | None]:
    prev_date = db.scalar(
        select(func.max(MeasurementRow.as_of)).where(
            MeasurementRow.metric_id == metric_id, MeasurementRow.as_of < as_of
        )
    )
    if prev_date is None:
        return {}
    rows = db.execute(
        select(MeasurementRow.dims_key, MeasurementRow.value)
        .where(MeasurementRow.metric_id == metric_id, MeasurementRow.as_of == prev_date)
        .order_by(MeasurementRow.id)
    ).all()
    return dict(rows)  # type: ignore[arg-type]


def evaluate_all(
    db: Session,
    content: Content,
    current: dict[tuple[str, str], DefinitionVersion],
    as_of: date,
    metric_ids: Iterable[str] | None = None,
) -> int:
    """Evaluate every metric (or the given ones). Returns the number of new rows."""
    wanted = set(metric_ids) if metric_ids is not None else set(content.metrics)
    count = 0
    for mid in sorted(wanted):
        metric = content.metrics[mid]
        count += len(evaluate_metric(db, metric, current[("metric", mid)], as_of))
    return count


def sources_needed(content: Content) -> dict[str, set[str]]:
    """Collector instance id -> queries that metrics, control evidence and registers use."""
    needed: dict[str, set[str]] = {}
    for metric in content.metrics.values():
        needed.setdefault(metric.source.collector, set()).add(metric.source.query)
    for control in content.controls.values():
        for ev in control.evidence:
            needed.setdefault(ev.collector, set()).add(ev.query)
    for register in content.registers.values():
        needed.setdefault(register.source.collector, set()).add(register.source.query)
    return needed


def run_period(
    db: Session, content: Content, as_of: date, secrets: SecretResolver, actor: str = "system"
) -> dict[str, int]:
    """Collect every needed source and evaluate every metric for one period."""
    current = sync_definitions(db, content, actor)
    runs = failed = 0
    for instance_id, queries in sorted(sources_needed(content).items()):
        instance = content.collectors[instance_id]
        for query in sorted(queries):
            result = run_collection(db, instance, query, as_of, secrets, actor=actor)
            runs += 1
            failed += result.status != "succeeded"
    measurements = evaluate_all(db, content, current, as_of)
    return {"runs": runs, "failed_runs": failed, "measurements": measurements}


@dataclass(frozen=True)
class StatusLine:
    """One metric's latest overall measurement."""

    metric_id: str
    name: str
    type: str
    as_of: date | None
    value: float | None
    status: str
    unit: str
    definition_version: int | None


def latest_status(db: Session, content: Content, as_of: date | None = None) -> list[StatusLine]:
    """The latest overall measurement per metric, at or before ``as_of`` if given."""
    lines = []
    for mid, metric in sorted(content.metrics.items()):
        cond = [MeasurementRow.metric_id == mid, MeasurementRow.dims_key == "{}"]
        if as_of is not None:
            cond.append(MeasurementRow.as_of <= as_of)
        row = db.scalars(
            select(MeasurementRow)
            .where(and_(*cond))
            .order_by(MeasurementRow.as_of.desc(), MeasurementRow.id.desc())
            .limit(1)
        ).first()
        lines.append(
            StatusLine(
                metric_id=mid,
                name=metric.name,
                type=metric.type.value,
                as_of=row.as_of if row else None,
                value=row.value if row else None,
                status=row.status if row else "unknown",
                unit=metric.unit,
                definition_version=row.definition_version if row else None,
            )
        )
    return lines
