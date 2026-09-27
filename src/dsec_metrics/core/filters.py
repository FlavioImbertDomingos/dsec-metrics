"""Structured record filters and value coercion. No expression language, no ``eval``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from dsec_metrics.core.definitions import Filter, FilterOp

Record = Mapping[str, Any]


def as_number(value: Any) -> float | None:
    """Return ``value`` as a float if it is an int or float (not bool), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def as_date(value: Any) -> date | None:
    """Parse an ISO date or date-time string (or a date) into a date, else ``None``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _ordered(left: Any, right: Any) -> tuple[Any, Any] | None:
    """A comparable pair: both numbers, or both strings. Otherwise ``None``."""
    ln, rn = as_number(left), as_number(right)
    if ln is not None and rn is not None:
        return ln, rn
    if isinstance(left, str) and isinstance(right, str):
        return left, right
    return None


def _equal(left: Any, right: Any) -> bool:
    ln, rn = as_number(left), as_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return bool(left == right)


def matches(record: Record, flt: Filter) -> bool:
    """True when ``record`` satisfies one filter. A missing field reads as ``None``."""
    actual = record.get(flt.field)
    op = flt.op
    if op is FilterOp.EXISTS:
        return actual is not None
    if op is FilterOp.MISSING:
        return actual is None
    if op is FilterOp.EQ:
        return _equal(actual, flt.value)
    if op is FilterOp.NE:
        return not _equal(actual, flt.value)
    if op in (FilterOp.IN, FilterOp.NOT_IN):
        options = flt.value if isinstance(flt.value, list) else []
        found = any(_equal(actual, option) for option in options)
        return found if op is FilterOp.IN else not found
    pair = _ordered(actual, flt.value)
    if pair is None:
        return False
    left, right = pair
    if op is FilterOp.GT:
        return bool(left > right)
    if op is FilterOp.GTE:
        return bool(left >= right)
    if op is FilterOp.LT:
        return bool(left < right)
    return bool(left <= right)


def apply(records: Iterable[Record], filters: Sequence[Filter]) -> list[Record]:
    """Records that satisfy every filter, in their original order."""
    return [r for r in records if all(matches(r, f) for f in filters)]
