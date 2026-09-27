"""Status from a value, the metric's bands and per-dimension overrides."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from dsec_metrics.core.definitions import Band, Override, Thresholds


class Status(StrEnum):
    """Measurement status. ``unknown`` is never shown as green."""

    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    UNKNOWN = "unknown"


def matching_override(thresholds: Thresholds, dimensions: Mapping[str, str]) -> Override | None:
    """The most specific override whose dimensions all match; first one wins on a tie."""
    best: Override | None = None
    for override in thresholds.overrides:
        applies = all(dimensions.get(k) == v for k, v in override.dimension.items())
        if applies and (best is None or len(override.dimension) > len(best.dimension)):
            best = override
    return best


def effective_bands(
    thresholds: Thresholds, dimensions: Mapping[str, str]
) -> tuple[Band, Band | None, Band | None]:
    """Green, amber and red bands after applying any matching override."""
    override = matching_override(thresholds, dimensions)
    green, amber, red = thresholds.green, thresholds.amber, thresholds.red
    if override is not None:
        green = override.green or green
        amber = override.amber or amber
        red = override.red or red
    return green, amber, red


def status_for(
    value: float | None, thresholds: Thresholds, dimensions: Mapping[str, str] | None = None
) -> Status:
    """Green, amber or red by first matching band; red when none match; unknown for None."""
    if value is None:
        return Status.UNKNOWN
    green, amber, red = effective_bands(thresholds, dimensions or {})
    if green.contains(value):
        return Status.GREEN
    if amber is not None and amber.contains(value):
        return Status.AMBER
    if red is not None and red.contains(value):
        return Status.RED
    return Status.RED
