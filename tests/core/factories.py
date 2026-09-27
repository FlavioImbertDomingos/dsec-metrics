"""Helpers to build metric definitions and record batches in tests."""

from __future__ import annotations

from typing import Any

from dsec_metrics.core.definitions import Metric

BUSINESS_UNITS = ["cards", "payments", "retail"]


def metric(
    evaluation: dict[str, Any], thresholds: dict[str, Any] | None = None, **extra: Any
) -> Metric:
    """A valid metric with the given evaluation block."""
    body: dict[str, Any] = {
        "id": "KRI-99",
        "name": "Test metric",
        "type": "kri",
        "question": "Is the test passing?",
        "owner": "test-owner",
        "audience": ["management"],
        "source": {"collector": "sample", "query": "things"},
        "evaluation": evaluation,
        "frequency": "monthly",
        "thresholds": thresholds
        or {"green": {"max": 5}, "amber": {"max": 15}, "red": {"above": 15}},
        "action_when_red": "Escalate.",
    }
    body.update(extra)
    return Metric.model_validate(body)
