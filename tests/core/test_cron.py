from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from dsec_metrics.core.cron import CronError, CronSchedule, parse_cron


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        ("5 2 * * *", "2026-09-26T10:00", "2026-09-27T02:05"),
        ("5 2 * * *", "2026-09-26T02:04", "2026-09-26T02:05"),
        ("5 2 * * *", "2026-09-26T02:05", "2026-09-27T02:05"),
        ("*/15 * * * *", "2026-09-26T10:07:30", "2026-09-26T10:15"),
        ("0 9 * * 1-5", "2026-09-25T09:00", "2026-09-28T09:00"),  # Friday -> Monday
        ("0 0 * * 0", "2026-09-26T12:00", "2026-09-27T00:00"),  # Sunday as 0
        ("0 0 * * 7", "2026-09-26T12:00", "2026-09-27T00:00"),  # Sunday as 7
        ("0 0 29 2 *", "2026-03-01T00:00", "2028-02-29T00:00"),
        ("0 0 31 * *", "2026-09-01T00:00", "2026-10-31T00:00"),
        ("30 23 31 12 *", "2026-12-31T23:30", "2027-12-31T23:30"),
        ("0 12 1-7/3 * *", "2026-09-02T00:00", "2026-09-04T12:00"),
        ("0 6 5/10 * *", "2026-09-06T00:00", "2026-09-15T06:00"),
        # Both day fields restricted: either one matching is enough (classic cron).
        ("0 0 13 * 5", "2026-09-26T00:00", "2026-10-02T00:00"),
        ("0 0 13 * 5", "2026-10-09T00:00", "2026-10-13T00:00"),
    ],
)
def test_next_after(expr: str, after: str, expected: str) -> None:
    assert parse_cron(expr).next_after(at(after)) == at(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * 32 * *",
        "* * * 13 *",
        "* * * * 8",
        "5-1 * * * *",
        "*/0 * * * *",
        "a * * * *",
        "* * * JAN *",
        "1,,2 * * * *",
        "-1 * * * *",
        "0 0 30 2 *",  # never fires
        "0 0 31 4,6,9,11 *",  # never fires
    ],
)
def test_rejects(expr: str) -> None:
    with pytest.raises(CronError):
        parse_cron(expr)


def test_requires_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone"):
        parse_cron("* * * * *").next_after(datetime(2026, 1, 1))  # noqa: DTZ001


def test_other_timezones_are_converted_to_utc() -> None:
    plus_two = datetime(2026, 9, 26, 3, 0, tzinfo=UTC).astimezone(timezone(timedelta(hours=2)))
    assert parse_cron("5 2 * * *").next_after(plus_two) == at("2026-09-27T02:05")


def naive_matches(schedule: CronSchedule, t: datetime) -> bool:
    """Independent restatement of cron matching used as a test oracle."""
    dow = (t.weekday() + 1) % 7
    dom_ok = t.day in schedule.days
    dow_ok = dow in schedule.weekdays
    if schedule.days_restricted and schedule.weekdays_restricted:
        day_ok = dom_ok or dow_ok
    else:
        day_ok = dom_ok and dow_ok
    return (
        t.minute in schedule.minutes
        and t.hour in schedule.hours
        and t.month in schedule.months
        and day_ok
    )


def field(lo: int, hi: int) -> st.SearchStrategy[str]:
    single = st.integers(lo, hi).map(str)
    rng = st.tuples(st.integers(lo, hi), st.integers(lo, hi)).map(lambda p: f"{min(p)}-{max(p)}")
    step = st.tuples(st.sampled_from(["*", str(lo)]), st.integers(1, hi - lo + 1)).map(
        lambda p: f"{p[0]}/{p[1]}"
    )
    part = st.one_of(single, rng, step)
    return st.one_of(st.just("*"), st.lists(part, min_size=1, max_size=3).map(",".join))


# Expressions that fire often enough to check every minute in between by brute force.
frequent = st.tuples(
    field(0, 59), field(0, 23), st.just("*"), st.just("*"), st.one_of(st.just("*"), field(0, 6))
).map(" ".join)

moments = st.datetimes(
    min_value=datetime(2020, 1, 1),  # noqa: DTZ001 (Hypothesis wants naive bounds)
    max_value=datetime(2035, 12, 31),  # noqa: DTZ001
    timezones=st.just(UTC),
)


@settings(max_examples=150, deadline=None)
@given(expr=frequent, start=moments)
def test_next_after_is_the_first_matching_minute(expr: str, start: datetime) -> None:
    schedule = parse_cron(expr)
    result = schedule.next_after(start)
    assert result > start
    assert result.second == 0
    assert result.microsecond == 0
    assert naive_matches(schedule, result)
    t = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while t < result:
        assert not naive_matches(schedule, t), f"{expr} matched earlier at {t}"
        t += timedelta(minutes=1)


any_expr = st.tuples(
    field(0, 59), field(0, 23), field(1, 28), field(1, 12), st.one_of(st.just("*"), field(0, 7))
).map(" ".join)


@settings(max_examples=150, deadline=None)
@given(expr=any_expr, start=moments)
def test_next_after_always_matches(expr: str, start: datetime) -> None:
    try:
        schedule = parse_cron(expr)
    except CronError:
        assume(False)  # for example "0 0 1/29 2 *", which never fires
        raise
    result = schedule.next_after(start)
    assert result > start
    assert naive_matches(schedule, result)
    assert schedule.next_after(result) > result
