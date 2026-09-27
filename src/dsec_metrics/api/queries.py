"""Read-side queries for the API.

Definitions come from the ``definitions`` table (the versions the evaluator used), not
from the files on disk. Dashboards read stored measurements only; the evaluator has
already done the aggregation.

Every query takes a :class:`Scope`. Until M5 adds business-unit grants the scope allows
everything, but the filter already runs, so M5 changes one constructor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import Row, and_, func, select, tuple_
from sqlalchemy.orm import Session, defer

from dsec_metrics.api import responses as r
from dsec_metrics.core.canonical import canonical_json
from dsec_metrics.core.definitions import (
    Control,
    Dashboard,
    Framework,
    Metric,
    Register,
    Strict,
    Thresholds,
)
from dsec_metrics.core.thresholds import effective_bands
from dsec_metrics.db.models import (
    CollectionRun,
    DefinitionVersion,
    MeasurementRow,
    RecordBatchRow,
)

DIMENSIONS = ("business_unit", "application", "environment", "region")
OVERALL = "{}"
STATUS_RANK = {"green": 0, "unknown": 1, "amber": 2, "red": 3}
CLOSED_EXCEPTION = frozenset({"closed", "rejected", "withdrawn", "revoked"})
CLOSED_FINDING = frozenset({"closed", "resolved", "risk_accepted"})
AGE_BUCKETS = ((90, "0 to 90 days"), (180, "91 to 180 days"), (365, "181 to 365 days"))


@dataclass(frozen=True)
class Scope:
    """What the caller may see. ``None`` means every business unit."""

    business_units: frozenset[str] | None = None

    def allows(self, dimensions: Mapping[str, Any]) -> bool:
        """True when a slice or record is inside the caller's business units."""
        if self.business_units is None:
            return True
        unit = dimensions.get("business_unit")
        return unit is None or unit in self.business_units


EVERYTHING = Scope()


# Definitions.


@dataclass
class Catalog:
    """The current version of every definition."""

    versions: dict[tuple[str, str], DefinitionVersion] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)
    controls: dict[str, Control] = field(default_factory=dict)
    frameworks: dict[str, Framework] = field(default_factory=dict)
    dashboards: dict[str, Dashboard] = field(default_factory=dict)
    registers: dict[str, Register] = field(default_factory=dict)

    def controls_for_metric(self, metric_id: str) -> list[str]:
        """Ids of controls that use a metric."""
        return sorted(cid for cid, c in self.controls.items() if metric_id in c.metrics)

    def requirement(self, ref: str) -> r.Requirement:
        """Resolve ``pack:ref`` to a requirement with our short title."""
        pack, _, local = ref.partition(":")
        fw = self.frameworks.get(pack)
        title = None
        if fw is not None:
            title = next((q.short_title for q in fw.requirements if q.ref == local), None)
        return r.Requirement(
            ref=ref, framework=pack, framework_name=fw.name if fw else pack, short_title=title
        )


_MODELS: dict[str, type[Strict]] = {
    "metric": Metric,
    "control": Control,
    "framework": Framework,
    "dashboard": Dashboard,
    "register": Register,
}


def load_catalog(db: Session) -> Catalog:
    """Parse the current definitions. Rows that no longer validate are skipped."""
    catalog = Catalog()
    rows = db.scalars(select(DefinitionVersion).where(DefinitionVersion.current.is_(True)))
    stores: dict[str, dict[str, Any]] = {
        "metric": catalog.metrics,
        "control": catalog.controls,
        "framework": catalog.frameworks,
        "dashboard": catalog.dashboards,
        "register": catalog.registers,
    }
    for row in rows:
        model = _MODELS.get(row.kind)
        if model is None:
            continue
        try:
            stores[row.kind][row.def_id] = model.model_validate(row.body)
        except ValidationError:
            continue
        catalog.versions[(row.kind, row.def_id)] = row
    return catalog


def versions_of(db: Session, kind: str, def_id: str) -> list[r.DefinitionVersionOut]:
    """Every stored version of one definition, newest first."""
    rows = db.execute(
        select(
            DefinitionVersion.version,
            DefinitionVersion.sha256,
            DefinitionVersion.created_at,
            DefinitionVersion.current,
        )
        .where(DefinitionVersion.kind == kind, DefinitionVersion.def_id == def_id)
        .order_by(DefinitionVersion.version.desc())
    ).all()
    return [
        r.DefinitionVersionOut(version=v, sha256=s, created_at=c, current=cur)
        for v, s, c, cur in rows
    ]


# Measurements.

_POINT_COLUMNS = (
    MeasurementRow.id,
    MeasurementRow.metric_id,
    MeasurementRow.dims_key,
    MeasurementRow.dimensions,
    MeasurementRow.as_of,
    MeasurementRow.value,
    MeasurementRow.status,
    MeasurementRow.delta_previous,
    MeasurementRow.delta_baseline,
    MeasurementRow.distance_to_target,
    MeasurementRow.definition_version,
)


def to_point(row: Row[Any] | MeasurementRow) -> r.Point:
    """Trim a measurement to what lists and charts need."""
    return r.Point(
        measurement_id=row.id,
        as_of=row.as_of,
        value=row.value,
        status=cast("r.Status", row.status),
        delta_previous=row.delta_previous,
        delta_baseline=row.delta_baseline,
        distance_to_target=row.distance_to_target,
        definition_version=row.definition_version,
    )


def latest_overall(db: Session, metric_ids: Iterable[str]) -> dict[str, r.Point]:
    """The newest overall measurement per metric."""
    ids = list(metric_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(*_POINT_COLUMNS)
        .where(MeasurementRow.metric_id.in_(ids), MeasurementRow.dims_key == OVERALL)
        .distinct(MeasurementRow.metric_id)
        .order_by(MeasurementRow.metric_id, MeasurementRow.as_of.desc(), MeasurementRow.id.desc())
    ).all()
    return {row.metric_id: to_point(row) for row in rows}


def histories(
    db: Session, keys: Iterable[tuple[str, str]], periods: int
) -> dict[tuple[str, str], list[r.Point]]:
    """The last ``periods`` dates for each (metric id, dims key), oldest first.

    When a date has rows from several definition versions, the newest row wins.
    """
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    rows = db.execute(
        select(*_POINT_COLUMNS)
        .where(tuple_(MeasurementRow.metric_id, MeasurementRow.dims_key).in_(wanted))
        .distinct(MeasurementRow.metric_id, MeasurementRow.dims_key, MeasurementRow.as_of)
        .order_by(
            MeasurementRow.metric_id,
            MeasurementRow.dims_key,
            MeasurementRow.as_of,
            MeasurementRow.id.desc(),
        )
    ).all()
    out: dict[tuple[str, str], list[r.Point]] = defaultdict(list)
    for row in rows:
        out[(row.metric_id, row.dims_key)].append(to_point(row))
    return {key: points[-periods:] for key, points in out.items()}


def latest_slices(db: Session, metric_ids: Iterable[str], scope: Scope) -> dict[str, list[r.Slice]]:
    """Every non-overall slice on each metric's newest date."""
    ids = list(metric_ids)
    if not ids:
        return {}
    newest = (
        select(MeasurementRow.metric_id, func.max(MeasurementRow.as_of).label("as_of"))
        .where(MeasurementRow.metric_id.in_(ids))
        .group_by(MeasurementRow.metric_id)
        .subquery()
    )
    rows = db.execute(
        select(*_POINT_COLUMNS)
        .join(
            newest,
            and_(
                newest.c.metric_id == MeasurementRow.metric_id,
                newest.c.as_of == MeasurementRow.as_of,
            ),
        )
        .where(MeasurementRow.dims_key != OVERALL)
        .distinct(MeasurementRow.metric_id, MeasurementRow.dims_key)
        .order_by(MeasurementRow.metric_id, MeasurementRow.dims_key, MeasurementRow.id.desc())
    ).all()
    out: dict[str, list[r.Slice]] = defaultdict(list)
    for row in rows:
        if scope.allows(row.dimensions):
            out[row.metric_id].append(r.Slice(dimensions=row.dimensions, point=to_point(row)))
    return dict(out)


@dataclass(frozen=True)
class SliceChoice:
    """Which slice answers a filter, and which filters it could not honour."""

    dimensions: dict[str, str]
    key: str
    applied: dict[str, str]
    ignored: list[str]


def choose_slice(metric: Metric, filters: Mapping[str, str]) -> SliceChoice:
    """Use the stored slice that matches the filters exactly, or the overall value.

    A filter on a dimension the metric is not grouped by is reported as ignored instead
    of producing a number that looks filtered but is not.
    """
    group_by = list(metric.evaluation.group_by)
    applied = {str(k): v for k, v in filters.items() if k in group_by}
    ignored = sorted(k for k in filters if k not in group_by)
    if applied and set(applied) == set(group_by):
        return SliceChoice(applied, canonical_json(applied), applied, ignored)
    # A partial match (grouped by two dimensions, filtered by one) has no stored slice.
    return SliceChoice({}, OVERALL, {}, sorted(filters))


def bands_for(thresholds: Thresholds, dimensions: Mapping[str, str]) -> r.Bands:
    """Threshold bands in effect for a slice."""
    green, amber, red = effective_bands(thresholds, dimensions)
    return r.Bands(
        green=r.Band.model_validate(green.model_dump()),
        amber=r.Band.model_validate(amber.model_dump()) if amber else None,
        red=r.Band.model_validate(red.model_dump()) if red else None,
    )


def metric_summary(metric: Metric, latest: r.Point | None) -> r.MetricSummary:
    """Catalog entry for a metric."""
    return r.MetricSummary(
        id=metric.id,
        name=metric.name,
        type=metric.type.value,
        question=metric.question,
        owner=metric.owner,
        audience=[a.value for a in metric.audience],
        unit=metric.unit,
        frequency=metric.frequency.value,
        higher_is_better=metric.higher_is_better,
        target=metric.target,
        action_when_red=metric.action_when_red,
        latest=latest,
    )


def worst(statuses: Iterable[str]) -> str:
    """The worst status; ``unknown`` ranks above green so it never reads as fine."""
    found = list(statuses)
    return max(found, key=lambda s: STATUS_RANK.get(s, 1)) if found else "unknown"


# Batches.


def batch_ref(row: RecordBatchRow) -> r.BatchRef:
    """Batch metadata for responses."""
    return r.BatchRef(
        sha256=row.sha256,
        collector=row.collector,
        collector_version=row.collector_version,
        instance_id=row.instance_id,
        query=row.query,
        params=row.params,
        as_of=row.as_of,
        collected_at=row.collected_at,
        record_count=row.record_count,
        redaction=row.redaction,
        storage_ref=row.storage_ref,
    )


def batches_by_hash(db: Session, hashes: Sequence[str]) -> dict[str, RecordBatchRow]:
    """The most recently collected batch for each hash, without its records."""
    if not hashes:
        return {}
    rows = db.scalars(
        select(RecordBatchRow)
        .options(defer(RecordBatchRow.records))
        .where(RecordBatchRow.sha256.in_(list(hashes)))
        .order_by(RecordBatchRow.collected_at)
    ).all()
    return {row.sha256: row for row in rows}


def latest_source_batches(
    db: Session,
    sources: Iterable[tuple[str, str]],
    *,
    with_records: bool,
    as_of_min: date | None = None,
    as_of_max: date | None = None,
) -> dict[tuple[str, str], list[RecordBatchRow]]:
    """Batches from the newest successful run of each (instance, query), optionally
    limited to runs whose ``as_of`` falls in a period."""
    out: dict[tuple[str, str], list[RecordBatchRow]] = {}
    for instance_id, query in sorted(set(sources)):
        conditions = [
            CollectionRun.instance_id == instance_id,
            CollectionRun.query == query,
            CollectionRun.status == "succeeded",
        ]
        if as_of_min is not None:
            conditions.append(CollectionRun.as_of >= as_of_min)
        if as_of_max is not None:
            conditions.append(CollectionRun.as_of <= as_of_max)
        run_id = db.scalar(
            select(CollectionRun.id)
            .where(*conditions)
            .order_by(CollectionRun.as_of.desc(), CollectionRun.finished_at.desc())
            .limit(1)
        )
        if run_id is None:
            out[(instance_id, query)] = []
            continue
        stmt = select(RecordBatchRow).where(RecordBatchRow.run_id == run_id)
        if not with_records:
            stmt = stmt.options(defer(RecordBatchRow.records))
        out[(instance_id, query)] = list(db.scalars(stmt))
    return out


# Registers.


def _days(later: date | None, earlier: date | None) -> int | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).days


def _parse_date(value: Any) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _matches(record: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
    return all(str(record.get(k)) == v for k, v in filters.items())


@dataclass
class RegisterData:
    """Parsed register rows and where they came from."""

    source: r.RegisterSource | None
    exceptions: list[r.ExceptionItem] = field(default_factory=list)
    findings: list[r.FindingItem] = field(default_factory=list)
    skipped: int = 0
    batches: list[RecordBatchRow] = field(default_factory=list)


def load_register(
    db: Session,
    catalog: Catalog,
    register_id: str,
    scope: Scope,
    filters: Mapping[str, str] | None = None,
    as_of_max: date | None = None,
) -> RegisterData:
    """Read a register from the latest batch of its source (at or before ``as_of_max``
    when given). Invalid rows are counted."""
    register = catalog.registers.get(register_id)
    if register is None:
        return RegisterData(source=None)
    key = (register.source.collector, register.source.query)
    batches = latest_source_batches(db, [key], with_records=True, as_of_max=as_of_max)[key]
    if not batches:
        return RegisterData(source=None)
    first = batches[0]
    data = RegisterData(
        source=r.RegisterSource(
            sha256=first.sha256, as_of=first.as_of, collected_at=first.collected_at
        ),
        batches=list(batches),
    )
    as_of = first.as_of
    for batch in batches:
        for record in batch.records:
            if not scope.allows(record) or not _matches(record, filters or {}):
                continue
            try:
                if register_id == "exceptions":
                    approved = _parse_date(record.get("approved_at"))
                    expires = _parse_date(record.get("expires_at"))
                    data.exceptions.append(
                        r.ExceptionItem.model_validate(
                            {
                                **record,
                                "age_days": _days(as_of, approved),
                                "days_to_expiry": _days(expires, as_of),
                            }
                        )
                    )
                else:
                    opened = _parse_date(record.get("opened"))
                    due = _parse_date(record.get("due_date"))
                    status = str(record.get("status", ""))
                    past_due = _days(as_of, due)
                    data.findings.append(
                        r.FindingItem.model_validate(
                            {
                                **record,
                                "days_open": _days(as_of, opened),
                                "days_past_due": max(past_due, 0)
                                if past_due is not None and status not in CLOSED_FINDING
                                else 0,
                            }
                        )
                    )
            except ValidationError:
                data.skipped += 1
    return data


def is_open_exception(item: r.ExceptionItem) -> bool:
    """Approved, pending and expired exceptions still need attention."""
    return item.status not in CLOSED_EXCEPTION


def is_open_finding(item: r.FindingItem) -> bool:
    """Anything not closed or resolved."""
    return item.status not in CLOSED_FINDING


def age_buckets(items: Iterable[r.ExceptionItem]) -> list[r.Bucket]:
    """Open exceptions by age since approval."""
    counts = [0] * (len(AGE_BUCKETS) + 1)
    for item in items:
        if not is_open_exception(item) or item.age_days is None:
            continue
        index = next((i for i, (limit, _) in enumerate(AGE_BUCKETS) if item.age_days <= limit), 3)
        counts[index] += 1
    labels = [label for _, label in AGE_BUCKETS] + ["over 365 days"]
    return [r.Bucket(label=label, count=n) for label, n in zip(labels, counts, strict=True)]
