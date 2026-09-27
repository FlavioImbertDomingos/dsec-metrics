"""Definition language: frameworks, metrics, controls, dashboards and collector instances.

These models are the schema behind ``dsec-metrics validate``. They reject unknown fields
so a typo in a YAML file is an error, not a silently ignored setting.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dsec_metrics.core.canonical import canonical_hash
from dsec_metrics.core.cron import parse_cron

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
METRIC_ID_PATTERN = r"^[A-Z][A-Z0-9]{1,7}-[0-9]{2,4}$"
REF_PATTERN = re.compile(r"^(?P<pack>[a-z0-9][a-z0-9.-]*):(?P<ref>[A-Za-z0-9][A-Za-z0-9._-]*)$")

DIMENSIONS: tuple[str, ...] = ("business_unit", "application", "environment", "region")


class Strict(BaseModel):
    """Base model: unknown fields are errors; instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Audience(StrEnum):
    """Who a metric or dashboard is for."""

    TEAM_OPERATIONS = "team_operations"
    MANAGEMENT = "management"
    RISK_COMMITTEE = "risk_committee"


class MetricType(StrEnum):
    """Key performance, risk or control indicator."""

    KPI = "kpi"
    KRI = "kri"
    KCI = "kci"


class Frequency(StrEnum):
    """How often a metric is measured."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"

    @property
    def days(self) -> int:
        """Nominal period length in days, used for staleness checks."""
        return {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92}[self.value]


class FilterOp(StrEnum):
    """Structured filter operators. There is no expression language."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    MISSING = "missing"


Scalar = str | int | float | bool | None


class Filter(Strict):
    """One condition on one record field."""

    field: str = Field(min_length=1, max_length=64)
    op: FilterOp
    value: Scalar | list[Scalar] = None

    @model_validator(mode="after")
    def _value_matches_op(self) -> Filter:
        if self.op in (FilterOp.IN, FilterOp.NOT_IN) and not isinstance(self.value, list):
            raise ValueError(f"filter op {self.op.value} needs a list value")
        if self.op not in (FilterOp.IN, FilterOp.NOT_IN) and isinstance(self.value, list):
            raise ValueError(f"filter op {self.op.value} takes a single value")
        if self.op in (FilterOp.EXISTS, FilterOp.MISSING) and self.value is not None:
            raise ValueError(f"filter op {self.op.value} takes no value")
        return self


GroupBy = Annotated[
    list[Literal["business_unit", "application", "environment", "region"]], Field(max_length=4)
]


class _EvalBase(Strict):
    filters: list[Filter] = Field(default_factory=list)
    group_by: GroupBy = Field(default_factory=list)


class CountEval(_EvalBase):
    """Number of records that pass the filters."""

    kind: Literal["count"]


class SumEval(_EvalBase):
    """Sum of a numeric field over records that pass the filters."""

    kind: Literal["sum"]
    field: str


class _RatioBase(_EvalBase):
    numerator: list[Filter] = Field(default_factory=list)
    denominator: list[Filter] = Field(default_factory=list)
    numerator_field: str | None = None
    denominator_field: str | None = None


class RatioEval(_RatioBase):
    """Numerator divided by denominator, times ``scale``.

    Both sides start from the records that pass ``filters``. Each side then applies its
    own filters, and counts records, or sums ``numerator_field``/``denominator_field``
    when one is given.
    """

    kind: Literal["ratio"]
    scale: float = Field(default=1.0, gt=0)


class PercentageEval(_RatioBase):
    """A ratio expressed in percent."""

    kind: Literal["percentage"]


class MedianEval(_EvalBase):
    """Median of a numeric field."""

    kind: Literal["median"]
    field: str


class PercentileEval(_EvalBase):
    """Nearest-rank percentile of a numeric field."""

    kind: Literal["percentile"]
    field: str
    percentile: float = Field(gt=0, le=100)


class AgeOverEval(_EvalBase):
    """Records whose date field is more than ``days`` before ``as_of``."""

    kind: Literal["age_over"]
    date_field: str
    days: int = Field(ge=0)


class SlaBreachEval(_EvalBase):
    """Records open longer than ``sla_days``, measured to their close date or ``as_of``.

    With ``as_percentage`` the value is the share of records in breach.
    """

    kind: Literal["sla_breach"]
    opened_field: str
    closed_field: str | None = None
    sla_days: int = Field(ge=0)
    as_percentage: bool = False


class LatestValueEval(_EvalBase):
    """The numeric ``field`` of the record with the greatest ``order_by`` value."""

    kind: Literal["latest_value"]
    field: str
    order_by: str


Evaluation = Annotated[
    CountEval
    | SumEval
    | RatioEval
    | PercentageEval
    | MedianEval
    | PercentileEval
    | AgeOverEval
    | SlaBreachEval
    | LatestValueEval,
    Field(discriminator="kind"),
]


class Band(Strict):
    """Bounds for one status. ``min``/``max`` are inclusive, ``above``/``below`` exclusive."""

    min: float | None = None
    max: float | None = None
    above: float | None = None
    below: float | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Band:
        if all(v is None for v in (self.min, self.max, self.above, self.below)):
            raise ValueError("a threshold band needs at least one bound")
        return self

    def contains(self, value: float) -> bool:
        """True when ``value`` is within every bound given."""
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        if self.above is not None and value <= self.above:
            return False
        return not (self.below is not None and value >= self.below)


class Override(Strict):
    """Replacement bands for slices whose dimensions match ``dimension``."""

    dimension: dict[str, str] = Field(min_length=1)
    green: Band | None = None
    amber: Band | None = None
    red: Band | None = None

    @field_validator("dimension")
    @classmethod
    def _known_dimensions(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown dimension(s): {', '.join(sorted(unknown))}")
        return value


class Thresholds(Strict):
    """Status bands and per-dimension overrides."""

    green: Band
    amber: Band | None = None
    red: Band | None = None
    overrides: list[Override] = Field(default_factory=list)


class Source(Strict):
    """Where a metric's input comes from."""

    collector: str = Field(pattern=ID_PATTERN)
    query: str = Field(pattern=ID_PATTERN)
    params: dict[str, Scalar] = Field(default_factory=dict)


class Baseline(Strict):
    """The starting point a metric is measured against."""

    value: float
    method: str
    date: date


class Metric(Strict):
    """A KPI, KRI or KCI definition."""

    id: str = Field(pattern=METRIC_ID_PATTERN)
    name: str = Field(min_length=3, max_length=160)
    type: MetricType
    question: str = Field(min_length=3)
    owner: str = Field(pattern=ID_PATTERN)
    audience: list[Audience] = Field(min_length=1)
    source: Source
    evaluation: Evaluation
    frequency: Frequency
    thresholds: Thresholds
    action_when_red: str = Field(min_length=3)
    frameworks: list[str] = Field(default_factory=list)
    baseline: Baseline | None = None
    target: float | None = None
    unit: Literal["count", "percent", "days", "ratio", "value"] = "count"
    higher_is_better: bool = False
    approved_by: list[str] = Field(default_factory=list)
    review_by: date | None = None

    @field_validator("frameworks")
    @classmethod
    def _refs(cls, value: list[str]) -> list[str]:
        for ref in value:
            if not REF_PATTERN.match(ref):
                raise ValueError(f"framework reference {ref!r} must look like pack-id:ref")
        return value


class Requirement(Strict):
    """One requirement inside a framework pack."""

    ref: str = Field(min_length=1, max_length=32)
    short_title: str = Field(min_length=3, max_length=200)
    text: str | None = Field(
        default=None, description="Official text; only for public-domain frameworks."
    )


class Framework(Strict):
    """A framework pack: IDs and short titles written by the project."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")
    name: str
    version: str
    source_url: str = Field(pattern=r"^https://")
    public_domain: bool = False
    requirements: list[Requirement] = Field(min_length=1)

    @model_validator(mode="after")
    def _text_only_when_allowed(self) -> Framework:
        if not self.public_domain and any(r.text for r in self.requirements):
            raise ValueError("requirement text is allowed only for public-domain frameworks")
        refs = [r.ref for r in self.requirements]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate requirement refs")
        return self


class EvidenceSpec(Strict):
    """Evidence a control collects, and how long to keep it."""

    collector: str = Field(pattern=ID_PATTERN)
    query: str = Field(pattern=ID_PATTERN)
    retain_days: int = Field(ge=1, le=3650)


class Control(Strict):
    """An internal control the company operates."""

    id: str = Field(pattern=r"^[A-Z]{2,4}-[A-Z]{2,4}-[0-9]{2,3}$")
    name: str = Field(min_length=3)
    owner: str = Field(pattern=ID_PATTERN)
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpec] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _refs(cls, value: list[str]) -> list[str]:
        for ref in value:
            if not REF_PATTERN.match(ref):
                raise ValueError(f"requirement reference {ref!r} must look like pack-id:ref")
        return value


WidgetType = Literal[
    "stat", "trend", "bar", "table", "rag_list", "heatmap", "exceptions_aging", "findings_burndown"
]


class Widget(Strict):
    """One dashboard tile."""

    widget: WidgetType
    title: str | None = None
    metric: str | None = None
    metrics: list[str] = Field(default_factory=list)
    periods: int = Field(default=12, ge=1, le=36)
    rows: Literal["business_unit", "application", "environment", "region", "metric"] | None = None
    columns: Literal["business_unit", "control", "metric", "period"] | None = None
    value: Literal["status", "value"] | None = None
    width: int = Field(default=12, ge=1, le=12)

    def metric_ids(self) -> list[str]:
        """Every metric this widget reads."""
        return [*self.metrics, *([self.metric] if self.metric else [])]


class Dashboard(Strict):
    """A dashboard layout for one audience."""

    id: str = Field(pattern=ID_PATTERN)
    title: str
    audience: Audience
    refresh: Frequency
    layout: list[Widget] = Field(min_length=1)


class CollectorInstance(Strict):
    """A configured collector plugin. Secrets are references, never values."""

    id: str = Field(pattern=ID_PATTERN)
    plugin: str = Field(pattern=ID_PATTERN)
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    schedule: str | None = Field(
        default=None, description="Five-field cron expression in UTC, or empty for manual runs."
    )

    @field_validator("schedule")
    @classmethod
    def _cron_fields(cls, value: str | None) -> str | None:
        if value is not None:
            parse_cron(value)
        return value


Definition = Framework | Metric | Control | Dashboard | CollectorInstance

KINDS: dict[str, type[Strict]] = {
    "framework": Framework,
    "metric": Metric,
    "control": Control,
    "dashboard": Dashboard,
    "collector": CollectorInstance,
}


def definition_hash(definition: Strict) -> str:
    """Version hash: SHA-256 of the canonical JSON of the validated definition."""
    return canonical_hash(definition.model_dump(mode="json"))
