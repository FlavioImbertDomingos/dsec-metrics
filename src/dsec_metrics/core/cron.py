"""Five-field cron expressions, evaluated in UTC.

Supported syntax per field: ``*``, a number, a range ``a-b``, a step ``*/n``, ``a-b/n`` or
``a/n``, and comma-separated lists of those. Month and weekday names, ``L``, ``W``, ``#``
and ``?`` are not supported. Weekday 0 and 7 are both Sunday.

When both day-of-month and day-of-week are restricted (anything other than a bare ``*``),
a day matches if either one matches, as in classic cron. Expressions that can never fire,
such as ``0 0 30 2 *``, are rejected when parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# (name, low, high) for each field, in order.
FIELDS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)

# Search horizon for the next fire time. Eight years always includes a 29 February.
HORIZON_YEARS = 8


class CronError(ValueError):
    """The expression is not a valid five-field cron expression."""


def _number(text: str, name: str, lo: int, hi: int) -> int:
    if not text.isdigit():
        raise CronError(f"{name}: {text!r} is not a number")
    value = int(text)
    if not lo <= value <= hi:
        raise CronError(f"{name}: {value} is outside {lo}-{hi}")
    return value


def _field(text: str, name: str, lo: int, hi: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{name}: empty list item")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) == 0:
                raise CronError(f"{name}: step must be a positive number")
            step = int(step_text)
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = _number(a, name, lo, hi), _number(b, name, lo, hi)
            if start > end:
                raise CronError(f"{name}: range {base} runs backwards")
        else:
            start = _number(base, name, lo, hi)
            end = hi if step_text else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class CronSchedule:
    """A parsed expression. Weekdays use 0 for Sunday."""

    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    days_restricted: bool
    weekdays_restricted: bool

    def _day_matches(self, t: datetime) -> bool:
        dom = t.day in self.days
        dow = (t.weekday() + 1) % 7 in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return dom or dow
        return dom and dow

    def next_after(self, moment: datetime) -> datetime:
        """The first matching minute strictly after ``moment``, in UTC."""
        if moment.tzinfo is None:
            raise ValueError("moment must be timezone-aware")
        t = moment.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = t.year + HORIZON_YEARS
        while t.year <= limit:
            if t.month not in self.months:
                year, month = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
                t = t.replace(year=year, month=month, day=1, hour=0, minute=0)
            elif not self._day_matches(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            elif t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
            elif t.minute not in self.minutes:
                t += timedelta(minutes=1)
            else:
                return t
        raise CronError(f"{self.expression!r} does not fire within {HORIZON_YEARS} years")


def parse_cron(expression: str) -> CronSchedule:
    """Parse and check an expression. Raises ``CronError`` if it is invalid or never fires."""
    parts = expression.split()
    if len(parts) != len(FIELDS):
        raise CronError("cron expression needs five fields: minute hour day month weekday")
    sets = [_field(p, name, lo, hi) for p, (name, lo, hi) in zip(parts, FIELDS, strict=True)]
    weekdays = frozenset(d % 7 for d in sets[4])
    schedule = CronSchedule(
        expression=" ".join(parts),
        minutes=sets[0],
        hours=sets[1],
        days=sets[2],
        months=sets[3],
        weekdays=weekdays,
        days_restricted=parts[2] != "*",
        weekdays_restricted=parts[4] != "*",
    )
    schedule.next_after(datetime(2000, 1, 1, tzinfo=UTC))
    return schedule
