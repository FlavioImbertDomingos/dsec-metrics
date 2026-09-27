"""The evaluator: definition + input batches + ``as_of`` -> measurements.

A pure function. The same inputs always give the same outputs, independent of record
order. Every measurement carries a ``calculation`` record detailed enough for an auditor
to recompute the number by hand.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from dsec_metrics.core.canonical import canonical_json
from dsec_metrics.core.definitions import (
    AgeOverEval,
    CountEval,
    Filter,
    LatestValueEval,
    MedianEval,
    Metric,
    PercentageEval,
    PercentileEval,
    RatioEval,
    SlaBreachEval,
    SumEval,
    definition_hash,
)
from dsec_metrics.core.filters import Record, apply, as_date, as_number
from dsec_metrics.core.thresholds import Status, status_for

UNSET_DIMENSION = "unassigned"


@dataclass(frozen=True, slots=True)
class InputBatch:
    """One stored record batch: its hash and its (already redacted) records."""

    sha256: str
    records: Sequence[Record]


@dataclass(frozen=True, slots=True)
class Measurement:
    """One metric value for one ``as_of`` date and one dimension slice."""

    metric_id: str
    definition_sha256: str
    as_of: date
    dimensions: Mapping[str, str]
    value: float | None
    status: Status
    input_batch_hashes: tuple[str, ...]
    delta_previous: float | None = None
    delta_baseline: float | None = None
    distance_to_target: float | None = None
    calculation: Mapping[str, Any] = field(default_factory=dict)

    @property
    def dims_key(self) -> str:
        """Stable key for the dimension slice; ``{}`` for the overall value."""
        return dims_key(self.dimensions)


def dims_key(dimensions: Mapping[str, str]) -> str:
    """Canonical JSON of a dimension mapping."""
    return canonical_json(dict(dimensions))


def _numbers(records: Sequence[Record], fld: str) -> tuple[list[float], int]:
    values = [as_number(r.get(fld)) for r in records]
    kept = [v for v in values if v is not None]
    return kept, len(values) - len(kept)


def _side(
    records: Sequence[Record], filters: Sequence[Filter], fld: str | None
) -> tuple[float, int]:
    chosen = apply(records, filters)
    if fld is None:
        return float(len(chosen)), 0
    numbers, skipped = _numbers(chosen, fld)
    return math.fsum(numbers), skipped


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile: the smallest value with at least p% of values at or below."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def median(values: Sequence[float]) -> float:
    """Median; the mean of the two middle values for an even count."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute(
    metric: Metric, records: Sequence[Record], as_of: date
) -> tuple[float | None, dict[str, Any]]:
    """The value for one slice's filtered records, and the calculation steps."""
    ev = metric.evaluation
    calc: dict[str, Any] = {"kind": ev.kind, "records": len(records)}
    if isinstance(ev, CountEval):
        calc["formula"] = "count(records)"
        return float(len(records)), calc
    if isinstance(ev, SumEval):
        numbers, skipped = _numbers(records, ev.field)
        calc.update(formula=f"sum({ev.field})", summed=len(numbers), skipped_non_numeric=skipped)
        return math.fsum(numbers), calc
    if isinstance(ev, RatioEval | PercentageEval):
        scale = ev.scale if isinstance(ev, RatioEval) else 100.0
        num, num_skip = _side(records, ev.numerator, ev.numerator_field)
        den, den_skip = _side(records, ev.denominator, ev.denominator_field)
        calc.update(
            formula="numerator / denominator * scale",
            numerator=num,
            denominator=den,
            scale=scale,
            skipped_non_numeric=num_skip + den_skip,
        )
        if den == 0:
            calc["note"] = "denominator is zero"
            return None, calc
        return num / den * scale, calc
    if isinstance(ev, MedianEval | PercentileEval):
        numbers, skipped = _numbers(records, ev.field)
        calc.update(values=len(numbers), skipped_non_numeric=skipped)
        if not numbers:
            calc["note"] = "no numeric values"
            return None, calc
        if isinstance(ev, MedianEval):
            calc["formula"] = f"median({ev.field})"
            return median(numbers), calc
        calc["formula"] = f"nearest_rank_percentile({ev.field}, {ev.percentile})"
        return nearest_rank(numbers, ev.percentile), calc
    if isinstance(ev, AgeOverEval):
        dates = [as_date(r.get(ev.date_field)) for r in records]
        valid = [d for d in dates if d is not None]
        over = sum(1 for d in valid if (as_of - d).days > ev.days)
        calc.update(
            formula=f"count(as_of - {ev.date_field} > {ev.days} days)",
            undated=len(dates) - len(valid),
        )
        return float(over), calc
    if isinstance(ev, SlaBreachEval):
        breached = 0
        considered = 0
        for r in records:
            opened = as_date(r.get(ev.opened_field))
            if opened is None:
                continue
            closed = as_date(r.get(ev.closed_field)) if ev.closed_field else None
            end = closed or as_of
            considered += 1
            if (end - opened).days > ev.sla_days:
                breached += 1
        calc.update(
            formula=(
                f"count(({ev.closed_field or 'as_of'} or as_of) - {ev.opened_field}"
                f" > {ev.sla_days} days)"
            ),
            considered=considered,
            breached=breached,
        )
        if ev.as_percentage:
            if considered == 0:
                calc["note"] = "no dated records"
                return None, calc
            return breached / considered * 100.0, calc
        return float(breached), calc
    assert isinstance(ev, LatestValueEval)  # noqa: S101 (exhaustive match for type checkers)
    candidates = [
        (str(r.get(ev.order_by)), as_number(r.get(ev.field)))
        for r in records
        if r.get(ev.order_by) is not None
    ]
    numeric = [(k, v) for k, v in candidates if v is not None]
    calc.update(formula=f"{ev.field} of record with max({ev.order_by})", candidates=len(numeric))
    if not numeric:
        calc["note"] = "no records with a value"
        return None, calc
    # Ties on the ordering key resolve to the largest value, so record order never matters.
    key, value = max(numeric, key=lambda kv: (kv[0], kv[1]))
    calc["latest"] = key
    return value, calc


def _slices(
    metric: Metric, records: Sequence[Record]
) -> dict[str, tuple[dict[str, str], list[Record]]]:
    group_by = list(metric.evaluation.group_by)
    slices: dict[str, tuple[dict[str, str], list[Record]]] = {"{}": ({}, list(records))}
    if not group_by:
        return slices
    for record in records:
        dims: dict[str, str] = {str(d): str(record.get(d) or UNSET_DIMENSION) for d in group_by}
        key = dims_key(dims)
        slices.setdefault(key, (dims, []))[1].append(record)
    return slices


def is_stale(metric: Metric, as_of: date, last_collected_at: datetime | None) -> bool:
    """True when the last successful collection is older than twice the frequency."""
    if last_collected_at is None:
        return True
    return (as_of - last_collected_at.date()).days > 2 * metric.frequency.days


def evaluate(
    metric: Metric,
    batches: Sequence[InputBatch],
    as_of: date,
    *,
    last_collected_at: datetime | None = None,
    previous: Mapping[str, float | None] | None = None,
) -> list[Measurement]:
    """Evaluate one metric. Returns the overall measurement first, then slices by key.

    ``previous`` maps a slice's ``dims_key`` to the previous period's value.
    ``last_collected_at`` defaults to "fresh" when batches are given without it.
    """
    def_hash = definition_hash(metric)
    hashes = tuple(sorted(b.sha256 for b in batches))
    if not batches or (
        last_collected_at is not None and is_stale(metric, as_of, last_collected_at)
    ):
        reason = "no input data" if not batches else "last collection is stale"
        return [
            Measurement(
                metric_id=metric.id,
                definition_sha256=def_hash,
                as_of=as_of,
                dimensions={},
                value=None,
                status=Status.UNKNOWN,
                input_batch_hashes=hashes,
                calculation={"kind": metric.evaluation.kind, "note": reason},
            )
        ]

    all_records = [r for b in sorted(batches, key=lambda b: b.sha256) for r in b.records]
    filtered = apply(all_records, metric.evaluation.filters)
    results: list[Measurement] = []
    for key, (dims, recs) in sorted(
        _slices(metric, filtered).items(), key=lambda kv: (kv[0] != "{}", kv[0])
    ):
        value, calc = compute(metric, recs, as_of)
        calc = {"input_records": len(all_records), "filtered_records": len(filtered), **calc}
        prev = (previous or {}).get(key)
        overall = key == "{}"
        results.append(
            Measurement(
                metric_id=metric.id,
                definition_sha256=def_hash,
                as_of=as_of,
                dimensions=dims,
                value=value,
                status=status_for(value, metric.thresholds, dims),
                input_batch_hashes=hashes,
                delta_previous=_diff(value, prev),
                delta_baseline=_diff(value, metric.baseline.value)
                if overall and metric.baseline
                else None,
                distance_to_target=_diff(value, metric.target) if overall else None,
                calculation=calc,
            )
        )
    return results


def _diff(value: float | None, other: float | None) -> float | None:
    if value is None or other is None:
        return None
    return value - other
