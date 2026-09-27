"""Helpers for collector contract tests. CI never calls live services."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from dsec_metrics.plugins.sdk.base import Collector, RecordBatch


def check_collector_class(cls: type[Collector]) -> None:
    """Assert the class declares everything the platform and the docs rely on."""
    for attr in ("name", "version", "config_model", "queries", "required_permissions"):
        if not hasattr(cls, attr):
            raise AssertionError(f"{cls.__name__} is missing {attr}")
    if not cls.queries:
        raise AssertionError(f"{cls.__name__} declares no queries")
    for description in cls.queries.values():
        if not description.strip():
            raise AssertionError(f"{cls.__name__} has a query without a description")


def collect_all(collector: Collector, query: str, as_of: date, **params: Any) -> list[RecordBatch]:
    """Run a query and check every batch is JSON-serializable and labelled correctly."""
    batches = list(collector.collect(query, dict(params), as_of))
    for batch in batches:
        if batch.query != query:
            raise AssertionError(f"batch labelled {batch.query!r}, expected {query!r}")
        json.dumps(batch.records, allow_nan=False)
    return batches
