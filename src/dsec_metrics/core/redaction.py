"""Redaction applied to every collected record before anything is stored.

Two rules:

1. Fields marked sensitive (by the collector, plus a global list) are dropped.
2. Anything that looks like a card number is masked to its first six and last four
   digits. "Looks like" means 13 to 19 digits, optionally separated by single spaces or
   dashes, that pass the Luhn check. Integers (and whole-number floats) of that length
   are checked too, and so are the keys of nested objects.

The functions are pure and return a summary of what changed, which is stored with the
record batch.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

GLOBAL_SENSITIVE_FIELDS = frozenset(
    {
        "cvv",
        "cvv2",
        "cvc",
        "cvc2",
        "cid",
        "pin",
        "pin_block",
        "track1",
        "track2",
        "track_data",
        "magstripe",
        "password",
        "secret",
        "private_key",
    }
)

# A run of digits with optional single space or dash separators, not glued to other digits.
_CANDIDATE = re.compile(r"(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![0-9])")


def luhn_valid(digits: str) -> bool:
    """Luhn (mod 10) check on a string of digits."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_pan(digits: str) -> str:
    """First six, asterisks, last four."""
    return f"{digits[:6]}{'*' * (len(digits) - 10)}{digits[-4:]}"


def _mask_text(text: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        raw = match.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            count += 1
            return mask_pan(digits)
        return raw

    return _CANDIDATE.sub(repl, text), count


@dataclass(slots=True)
class RedactionSummary:
    """What redaction changed in one batch."""

    records: int = 0
    pans_masked: int = 0
    fields_dropped: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, stored with the record batch."""
        return {
            "records": self.records,
            "pans_masked": self.pans_masked,
            "fields_dropped": dict(sorted(self.fields_dropped.items())),
        }


def _normalize(name: str) -> str:
    """Compare field names ignoring case and separators: ``Track-2`` matches ``track2``."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _redact_value(value: Any, sensitive: frozenset[str], summary: RedactionSummary) -> Any:
    if isinstance(value, str):
        masked, n = _mask_text(value)
        summary.pans_masked += n
        return masked
    if isinstance(value, bool):
        return value
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        digits = str(abs(int(value)))
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            summary.pans_masked += 1
            return mask_pan(digits)
        return value
    if isinstance(value, Mapping):
        return _redact_mapping(value, sensitive, summary)
    if isinstance(value, list | tuple):
        return [_redact_value(v, sensitive, summary) for v in value]
    return value


def _redact_mapping(
    record: Mapping[str, Any], sensitive: frozenset[str], summary: RedactionSummary
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if _normalize(str(key)) in sensitive:
            summary.fields_dropped[str(key)] = summary.fields_dropped.get(str(key), 0) + 1
            continue
        # Keys are data too: a collector could key an object by card number.
        masked_key, n = _mask_text(str(key))
        summary.pans_masked += n
        out[masked_key] = _redact_value(value, sensitive, summary)
    return out


def redact_records(
    records: Iterable[Mapping[str, Any]], sensitive_fields: Sequence[str] = ()
) -> tuple[list[dict[str, Any]], RedactionSummary]:
    """Redact a batch. Returns new records; the input is not modified."""
    sensitive = frozenset(_normalize(f) for f in (*GLOBAL_SENSITIVE_FIELDS, *sensitive_fields))
    summary = RedactionSummary()
    out = []
    for record in records:
        summary.records += 1
        out.append(_redact_mapping(record, sensitive, summary))
    return out, summary
