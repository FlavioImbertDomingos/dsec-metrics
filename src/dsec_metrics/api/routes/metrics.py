"""Metrics, measurements and record batches: the drill-down path."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query
from sqlalchemy import func, select, true

from dsec_metrics.api import queries as q
from dsec_metrics.api import responses as r
from dsec_metrics.api.policy import DbDep
from dsec_metrics.api.routes.common import (
    CatalogDep,
    FiltersDep,
    ScopeDep,
    not_found,
)
from dsec_metrics.core.definitions import METRIC_ID_PATTERN
from dsec_metrics.db.models import MeasurementRow, RecordBatchRow

router = APIRouter(tags=["metrics"])

MetricId = Annotated[str, Path(pattern=METRIC_ID_PATTERN)]
Sha256 = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


@router.get("/metrics")
def list_metrics(
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
    audience: Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")] = None,
    type: Annotated[str | None, Query(pattern=r"^(kpi|kri|kci)$")] = None,  # noqa: A002
) -> list[r.MetricSummary]:
    """The metric catalog with each metric's latest overall value and status."""
    del scope
    metrics = [
        m
        for m in catalog.metrics.values()
        if (audience is None or audience in {a.value for a in m.audience})
        and (type is None or m.type.value == type)
    ]
    latest = q.latest_overall(db, [m.id for m in metrics])
    return [q.metric_summary(m, latest.get(m.id)) for m in sorted(metrics, key=lambda m: m.id)]


@router.get("/metrics/{metric_id}")
def get_metric(
    metric_id: MetricId, db: DbDep, catalog: CatalogDep, scope: ScopeDep
) -> r.MetricDetail:
    """One metric: current definition, bands, framework mappings and version history."""
    del scope
    metric = catalog.metrics.get(metric_id)
    row = catalog.versions.get(("metric", metric_id))
    if metric is None or row is None:
        raise not_found("Metric")
    latest = q.latest_overall(db, [metric_id]).get(metric_id)
    summary = q.metric_summary(metric, latest)
    return r.MetricDetail(
        **summary.model_dump(),
        source=metric.source.model_dump(mode="json"),
        evaluation=metric.evaluation.model_dump(mode="json"),
        thresholds=metric.thresholds.model_dump(mode="json", exclude_none=True),
        bands=q.bands_for(metric.thresholds, {}),
        baseline=metric.baseline.model_dump(mode="json") if metric.baseline else None,
        frameworks=[catalog.requirement(ref) for ref in metric.frameworks],
        controls=catalog.controls_for_metric(metric_id),
        version=row.version,
        sha256=row.sha256,
        versions=q.versions_of(db, "metric", metric_id),
        definition=row.body,
        group_by=[str(g) for g in metric.evaluation.group_by],
    )


@router.get("/metrics/{metric_id}/measurements")
def metric_history(
    metric_id: MetricId,
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
    filters: FiltersDep,
    periods: Annotated[int, Query(ge=1, le=36)] = 12,
) -> r.MetricHistory:
    """History for the slice matching the filters, and every slice on the latest date."""
    metric = catalog.metrics.get(metric_id)
    if metric is None:
        raise not_found("Metric")
    choice = q.choose_slice(metric, filters)
    points = q.histories(db, [(metric_id, choice.key)], periods).get((metric_id, choice.key), [])
    if not scope.allows(choice.dimensions):
        points = []
    return r.MetricHistory(
        metric_id=metric_id,
        dimensions=choice.dimensions,
        applied_filters=choice.applied,
        ignored_filters=choice.ignored,
        points=points,
        slices=q.latest_slices(db, [metric_id], scope).get(metric_id, []),
        bands=q.bands_for(metric.thresholds, choice.dimensions),
    )


@router.get("/measurements/{measurement_id}")
def get_measurement(
    measurement_id: Annotated[int, Path(ge=1)],
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
) -> r.MeasurementDetail:
    """One measurement with its calculation and the batches it was computed from."""
    row = db.get(MeasurementRow, measurement_id)
    if row is None or not scope.allows(row.dimensions):
        raise not_found("Measurement")
    batches = q.batches_by_hash(db, row.input_batch_hashes)
    metric = catalog.metrics.get(row.metric_id)
    return r.MeasurementDetail(
        metric_id=row.metric_id,
        metric_name=metric.name if metric else row.metric_id,
        dimensions=row.dimensions,
        point=q.to_point(row),
        definition_sha256=row.definition_sha256,
        calculation=row.calculation,
        computed_at=row.computed_at,
        batches=[q.batch_ref(batches[h]) for h in row.input_batch_hashes if h in batches],
        missing_batches=[h for h in row.input_batch_hashes if h not in batches],
    )


@router.get("/batches/{sha256}")
def get_batch(
    sha256: Sha256,
    db: DbDep,
    scope: ScopeDep,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> r.BatchPage:
    """A batch's metadata and one page of its redacted records."""
    meta = q.batches_by_hash(db, [sha256]).get(sha256)
    if meta is None:
        raise not_found("Batch")
    # Page inside Postgres so a large batch is never loaded whole.
    elements = (
        func.jsonb_array_elements(RecordBatchRow.records)
        .table_valued("value", with_ordinality="ord")
        .render_derived()
        .lateral()
    )
    page = db.scalars(
        select(elements.c.value)
        .select_from(RecordBatchRow)
        .join(elements, true())
        .where(RecordBatchRow.id == meta.id)
        .order_by(elements.c.ord)
        .offset(offset)
        .limit(limit)
    ).all()
    records = [rec for rec in page if isinstance(rec, dict) and scope.allows(rec)]
    return r.BatchPage(
        batch=q.batch_ref(meta),
        offset=offset,
        limit=limit,
        total=meta.record_count,
        records=records,
    )
