"""Property-based tests for every evaluation kind and every threshold shape."""

from __future__ import annotations

import math
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dsec_metrics.core.canonical import canonical_json
from dsec_metrics.core.definitions import Filter, FilterOp
from dsec_metrics.core.evaluator import InputBatch, evaluate, median, nearest_rank
from dsec_metrics.core.filters import apply, matches
from dsec_metrics.core.thresholds import Status, status_for
from tests.core.factories import BUSINESS_UNITS, metric

AS_OF = date(2026, 9, 30)

record_st = st.fixed_dictionaries(
    {
        "business_unit": st.sampled_from(BUSINESS_UNITS),
        "status": st.sampled_from(["open", "approved", "closed"]),
        "value": st.one_of(
            st.integers(-1000, 1000),
            st.floats(-1e6, 1e6, allow_nan=False),
            st.none(),
            st.just("n/a"),
        ),
        "opened": st.dates(date(2024, 1, 1), AS_OF).map(date.isoformat),
        "closed": st.one_of(st.none(), st.dates(date(2024, 1, 1), AS_OF).map(date.isoformat)),
        "seq": st.integers(0, 50),
    }
)
records_st = st.lists(record_st, max_size=40)
approved = [Filter(field="status", op=FilterOp.EQ, value="approved")]


def run(ev: dict[str, Any], records: list[dict[str, Any]], **kw: Any) -> list[Any]:
    return evaluate(metric(ev, **kw), [InputBatch("a" * 64, records)], AS_OF)


def snapshot(results: list[Any]) -> str:
    return canonical_json(
        [[dict(r.dimensions), r.value, r.status.value, dict(r.calculation)] for r in results]
    )


def numbers(records: list[dict[str, Any]]) -> list[float]:
    return [
        float(r["value"])
        for r in records
        if isinstance(r["value"], int | float) and not isinstance(r["value"], bool)
    ]


# Determinism and order independence, across every kind.

ALL_KINDS = [
    {"kind": "count", "filters": [{"field": "status", "op": "eq", "value": "approved"}]},
    {"kind": "sum", "field": "value", "group_by": ["business_unit"]},
    {
        "kind": "ratio",
        "numerator": [{"field": "status", "op": "eq", "value": "closed"}],
        "scale": 100,
    },
    {"kind": "percentage", "numerator": [{"field": "closed", "op": "exists"}]},
    {"kind": "median", "field": "value"},
    {"kind": "percentile", "field": "value", "percentile": 90},
    {"kind": "age_over", "date_field": "opened", "days": 180, "group_by": ["business_unit"]},
    {"kind": "sla_breach", "opened_field": "opened", "closed_field": "closed", "sla_days": 30},
    {"kind": "latest_value", "field": "value", "order_by": "seq"},
]


@settings(max_examples=60)
@given(records=records_st, kind=st.sampled_from(ALL_KINDS), data=st.data())
def test_same_inputs_same_outputs_in_any_order(
    records: list[dict[str, Any]], kind: dict[str, Any], data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(records))
    first = run(kind, records)
    assert snapshot(first) == snapshot(run(kind, records))
    assert snapshot(first) == snapshot(run(kind, list(shuffled)))
    assert first[0].dimensions == {}
    assert all(r.definition_sha256 == first[0].definition_sha256 for r in first)


# Each kind against a simple reference implementation.


@given(records=records_st)
def test_count(records: list[dict[str, Any]]) -> None:
    out = run(
        {"kind": "count", "filters": [{"field": "status", "op": "eq", "value": "approved"}]},
        records,
    )
    assert out[0].value == sum(1 for r in records if r["status"] == "approved")


@given(records=records_st)
def test_count_slices_add_up(records: list[dict[str, Any]]) -> None:
    out = run({"kind": "count", "group_by": ["business_unit"]}, records)
    overall, slices = out[0], out[1:]
    assert sum(s.value or 0 for s in slices) == overall.value
    assert {s.dimensions["business_unit"] for s in slices} == {r["business_unit"] for r in records}


@given(records=records_st)
def test_sum(records: list[dict[str, Any]]) -> None:
    out = run({"kind": "sum", "field": "value"}, records)
    assert out[0].value is not None
    assert math.isclose(out[0].value, math.fsum(numbers(records)), rel_tol=1e-9, abs_tol=1e-6)


@given(records=records_st, scale=st.floats(0.5, 1000))
def test_ratio_and_percentage(records: list[dict[str, Any]], scale: float) -> None:
    closed = sum(1 for r in records if r["status"] == "closed")
    ratio = run(
        {
            "kind": "ratio",
            "numerator": [{"field": "status", "op": "eq", "value": "closed"}],
            "scale": scale,
        },
        records,
    )[0]
    pct = run(
        {"kind": "percentage", "numerator": [{"field": "status", "op": "eq", "value": "closed"}]},
        records,
    )[0]
    if not records:
        assert ratio.value is None
        assert ratio.status is Status.UNKNOWN
        assert pct.value is None
    else:
        assert ratio.value is not None
        assert pct.value is not None
        assert math.isclose(ratio.value, closed / len(records) * scale)
        assert math.isclose(pct.value, closed / len(records) * 100)
        assert 0 <= pct.value <= 100


@given(records=records_st)
def test_ratio_with_fields(records: list[dict[str, Any]]) -> None:
    out = run({"kind": "ratio", "numerator_field": "value", "denominator_field": "seq"}, records)[0]
    den = math.fsum(float(r["seq"]) for r in records)
    if den == 0:
        assert out.value is None
    else:
        assert out.value is not None
        assert math.isclose(
            out.value, math.fsum(numbers(records)) / den, rel_tol=1e-9, abs_tol=1e-9
        )


@given(records=records_st)
def test_median(records: list[dict[str, Any]]) -> None:
    out = run({"kind": "median", "field": "value"}, records)[0]
    vals = numbers(records)
    if not vals:
        assert out.value is None
    else:
        assert out.value is not None
        assert math.isclose(out.value, statistics.median(vals), rel_tol=1e-12, abs_tol=1e-9)


@given(
    values=st.lists(st.floats(-1e6, 1e6, allow_nan=False), min_size=1, max_size=50),
    p=st.floats(0.01, 100),
)
def test_nearest_rank_definition(values: list[float], p: float) -> None:
    result = nearest_rank(values, p)
    assert result in values
    at_or_below = sum(1 for v in values if v <= result)
    assert at_or_below / len(values) * 100 >= p - 1e-9
    below = sum(1 for v in values if v < result)
    assert below / len(values) * 100 < p + 1e-9
    assert median([result]) == result


@given(records=records_st, days=st.integers(0, 800))
def test_age_over(records: list[dict[str, Any]], days: int) -> None:
    out = run({"kind": "age_over", "date_field": "opened", "days": days}, records)[0]
    expected = sum(1 for r in records if (AS_OF - date.fromisoformat(r["opened"])).days > days)
    assert out.value == expected


@given(records=records_st, sla=st.integers(0, 400), pct=st.booleans())
def test_sla_breach(records: list[dict[str, Any]], sla: int, pct: bool) -> None:
    out = run(
        {
            "kind": "sla_breach",
            "opened_field": "opened",
            "closed_field": "closed",
            "sla_days": sla,
            "as_percentage": pct,
        },
        records,
    )[0]
    breached = 0
    for r in records:
        end = date.fromisoformat(r["closed"]) if r["closed"] else AS_OF
        breached += (end - date.fromisoformat(r["opened"])).days > sla
    if pct:
        assert (out.value is None) == (not records)
        if records:
            assert out.value is not None
            assert math.isclose(out.value, breached / len(records) * 100)
    else:
        assert out.value == breached


@given(records=records_st)
def test_latest_value(records: list[dict[str, Any]]) -> None:
    out = run({"kind": "latest_value", "field": "value", "order_by": "seq"}, records)[0]
    candidates = [
        (str(r["seq"]), float(r["value"])) for r in records if isinstance(r["value"], int | float)
    ]
    if not candidates:
        assert out.value is None
    else:
        assert out.value == max(candidates)[1]


# Filters.


@given(record=record_st, op=st.sampled_from(["gt", "gte", "lt", "lte"]), n=st.integers(-1000, 1000))
def test_ordering_filters_match_python(record: dict[str, Any], op: str, n: int) -> None:
    flt = Filter(field="value", op=FilterOp(op), value=n)
    v = record["value"]
    if isinstance(v, int | float):
        expected = {"gt": v > n, "gte": v >= n, "lt": v < n, "lte": v <= n}[op]
        assert matches(record, flt) is expected
    else:
        assert matches(record, flt) is False


@given(records=records_st)
def test_filters_are_conjunctive(records: list[dict[str, Any]]) -> None:
    both = [
        Filter(field="status", op=FilterOp.IN, value=["open", "approved"]),
        Filter(field="business_unit", op=FilterOp.NE, value="cards"),
    ]
    got = apply(records, both)
    assert got == [
        r for r in records if r["status"] in ("open", "approved") and r["business_unit"] != "cards"
    ]
    assert apply(records, [Filter(field="closed", op=FilterOp.MISSING)]) == [
        r for r in records if r["closed"] is None
    ]
    assert apply(records, [Filter(field="status", op=FilterOp.NOT_IN, value=["open"])]) == [
        r for r in records if r["status"] != "open"
    ]


def test_bool_and_number_are_not_equal() -> None:
    assert not matches({"x": True}, Filter(field="x", op=FilterOp.EQ, value=1))
    assert matches({"x": 1}, Filter(field="x", op=FilterOp.EQ, value=1.0))
    assert matches({"x": "2026-01-02"}, Filter(field="x", op=FilterOp.GT, value="2026-01-01"))


# Threshold shapes.

lower_is_better = st.tuples(st.floats(0, 100), st.floats(0, 100)).map(sorted)


@given(bounds=lower_is_better, value=st.floats(-10, 300))
def test_lower_is_better_bands(bounds: list[float], value: float) -> None:
    g, a = bounds
    th = {"green": {"max": g}, "amber": {"max": a}, "red": {"above": a}}
    m = metric({"kind": "count"}, thresholds=th)
    s = status_for(value, m.thresholds)
    assert s is (Status.GREEN if value <= g else Status.AMBER if value <= a else Status.RED)


@given(bounds=lower_is_better, value=st.floats(-10, 300))
def test_higher_is_better_bands(bounds: list[float], value: float) -> None:
    a, g = bounds
    th = {"green": {"min": g}, "amber": {"min": a}, "red": {"below": a}}
    m = metric({"kind": "count"}, thresholds=th)
    s = status_for(value, m.thresholds)
    assert s is (Status.GREEN if value >= g else Status.AMBER if value >= a else Status.RED)


@given(value=st.floats(-10, 300))
def test_two_band_and_range_shapes(value: float) -> None:
    two = metric({"kind": "count"}, thresholds={"green": {"max": 10}})
    assert status_for(value, two.thresholds) is (Status.GREEN if value <= 10 else Status.RED)
    rng = metric(
        {"kind": "count"},
        thresholds={"green": {"min": 10, "max": 20}, "amber": {"above": 5, "below": 30}},
    )
    expected = Status.GREEN if 10 <= value <= 20 else Status.AMBER if 5 < value < 30 else Status.RED
    assert status_for(value, rng.thresholds) is expected
    assert status_for(None, rng.thresholds) is Status.UNKNOWN


@given(value=st.integers(0, 30), bu=st.sampled_from(BUSINESS_UNITS))
def test_overrides_apply_only_to_matching_slices(value: int, bu: str) -> None:
    m = metric(
        {"kind": "count", "group_by": ["business_unit"]},
        thresholds={
            "green": {"max": 5},
            "amber": {"max": 15},
            "red": {"above": 15},
            "overrides": [
                {"dimension": {"business_unit": "cards"}, "amber": {"max": 8}, "red": {"above": 8}},
                {"dimension": {"business_unit": "cards", "region": "emea"}, "green": {"max": 1}},
            ],
        },
    )
    s = status_for(value, m.thresholds, {"business_unit": bu})
    amber_max = 8 if bu == "cards" else 15
    assert s is (Status.GREEN if value <= 5 else Status.AMBER if value <= amber_max else Status.RED)
    specific = status_for(value, m.thresholds, {"business_unit": "cards", "region": "emea"})
    # The more specific override replaces only green; amber and red come from the base.
    assert specific is (Status.GREEN if value <= 1 else Status.AMBER if value <= 15 else Status.RED)
    assert status_for(value, m.thresholds, {}) is status_for(
        value, metric({"kind": "count"}).thresholds
    )


# Unknown status, deltas and staleness.


def test_no_batches_is_unknown() -> None:
    out = evaluate(metric({"kind": "count"}), [], AS_OF)
    assert len(out) == 1
    assert out[0].status is Status.UNKNOWN
    assert out[0].value is None


def test_stale_collection_is_unknown() -> None:
    m = metric({"kind": "count"})
    batches = [InputBatch("b" * 64, [{"x": 1}])]
    fresh = datetime(2026, 9, 1, tzinfo=UTC)
    stale = datetime.combine(AS_OF - timedelta(days=63), datetime.min.time(), tzinfo=UTC)
    assert evaluate(m, batches, AS_OF, last_collected_at=fresh)[0].status is Status.GREEN
    assert evaluate(m, batches, AS_OF, last_collected_at=stale)[0].status is Status.UNKNOWN


def test_empty_batch_counts_zero_not_unknown() -> None:
    out = evaluate(metric({"kind": "count"}), [InputBatch("c" * 64, [])], AS_OF)
    assert out[0].value == 0
    assert out[0].status is Status.GREEN


def test_deltas_and_calculation() -> None:
    m = metric(
        {"kind": "count", "group_by": ["business_unit"]},
        baseline={"value": 22, "method": "manual count", "date": "2026-01-31"},
        target=3,
    )
    records = [{"business_unit": "cards"}] * 4 + [{"business_unit": "retail"}] * 2
    out = evaluate(
        m,
        [InputBatch("d" * 64, records), InputBatch("0" * 64, [])],
        AS_OF,
        previous={"{}": 8.0, '{"business_unit":"cards"}': 1.0},
    )
    overall = out[0]
    assert overall.value == 6
    assert overall.delta_previous == -2
    assert overall.delta_baseline == -16
    assert overall.distance_to_target == 3
    assert overall.input_batch_hashes == ("0" * 64, "d" * 64)
    assert overall.calculation["input_records"] == 6
    cards = next(o for o in out if o.dimensions == {"business_unit": "cards"})
    assert cards.delta_previous == 3
    assert cards.delta_baseline is None
    assert cards.dims_key == '{"business_unit":"cards"}'


def test_missing_dimension_value_is_grouped_as_unassigned() -> None:
    out = run({"kind": "count", "group_by": ["business_unit"]}, [{"status": "open"}])
    assert out[1].dimensions == {"business_unit": "unassigned"}
