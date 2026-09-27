"""Canonical JSON and SHA-256, the basis for every hash the platform records.

Canonical form: keys sorted, no insignificant whitespace, UTF-8, non-ASCII kept as is,
floats in Python's shortest round-trip form. Two equal documents always hash the same.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize ``value`` in canonical form. Raises on NaN and infinities."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(data: bytes | str) -> str:
    """Hex SHA-256 of bytes, or of a string encoded as UTF-8."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON of ``value``."""
    return sha256_hex(canonical_json(value))
