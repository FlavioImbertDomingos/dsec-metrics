"""Response models for the read API.

Every number the UI shows comes with the id of the measurement behind it, so the front
end can link it to the measurement, its definition version and its source batches.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["green", "amber", "red", "unknown"]


class Out(BaseModel):
    """Base for responses."""

    model_config = ConfigDict(frozen=True)


class Point(Out):
    """One measurement, trimmed for lists and charts."""

    measurement_id: int
    as_of: date
    value: float | None
    status: Status
    delta_previous: float | None = None
    delta_baseline: float | None = None
    distance_to_target: float | None = None
    definition_version: int


class Band(Out):
    """A threshold band. ``min``/``max`` inclusive, ``above``/``below`` exclusive."""

    min: float | None = None
    max: float | None = None
    above: float | None = None
    below: float | None = None


class Bands(Out):
    """Threshold bands in effect for a slice."""

    green: Band
    amber: Band | None = None
    red: Band | None = None


class MetricSummary(Out):
    """Catalog entry with the latest overall measurement."""

    id: str
    name: str
    type: str
    question: str
    owner: str
    audience: list[str]
    unit: str
    frequency: str
    higher_is_better: bool
    target: float | None
    action_when_red: str
    latest: Point | None


class Requirement(Out):
    """A framework requirement reference with our short title."""

    ref: str
    framework: str
    framework_name: str
    short_title: str | None


class DefinitionVersionOut(Out):
    """One stored version of a definition."""

    version: int
    sha256: str
    created_at: datetime
    current: bool


class MetricDetail(MetricSummary):
    """Everything about one metric except its history."""

    source: dict[str, Any]
    evaluation: dict[str, Any]
    thresholds: dict[str, Any]
    bands: Bands
    baseline: dict[str, Any] | None
    frameworks: list[Requirement]
    controls: list[str]
    version: int
    sha256: str
    versions: list[DefinitionVersionOut]
    definition: dict[str, Any]
    group_by: list[str]


class Slice(Out):
    """The value for one dimension slice on one date."""

    dimensions: dict[str, str]
    point: Point


class MetricHistory(Out):
    """History for one slice, and the slices on the latest date."""

    metric_id: str
    dimensions: dict[str, str]
    applied_filters: dict[str, str]
    ignored_filters: list[str]
    points: list[Point]
    slices: list[Slice]
    bands: Bands


class BatchRef(Out):
    """Metadata of one record batch."""

    sha256: str
    collector: str
    collector_version: str
    instance_id: str
    query: str
    params: dict[str, Any]
    as_of: date
    collected_at: datetime
    record_count: int
    redaction: dict[str, Any]
    storage_ref: str


class MeasurementDetail(Out):
    """One measurement with everything needed to reproduce it."""

    metric_id: str
    metric_name: str
    dimensions: dict[str, str]
    point: Point
    definition_sha256: str
    calculation: dict[str, Any]
    computed_at: datetime
    batches: list[BatchRef]
    missing_batches: list[str]


class BatchPage(Out):
    """A batch's metadata and one page of its redacted records."""

    batch: BatchRef
    offset: int
    limit: int
    total: int
    records: list[dict[str, Any]]


class RegisterSource(Out):
    """Where a register's rows came from."""

    sha256: str
    as_of: date
    collected_at: datetime


class ExceptionItem(Out):
    """One exception from the register. Ages are counted to the batch's ``as_of``."""

    exception_id: str
    status: str
    control_id: str | None = None
    reason: str | None = None
    compensating_controls: str | None = None
    risk_rating: str | None = None
    owner: str | None = None
    root_cause: str | None = None
    approved_at: date | None = None
    expires_at: date | None = None
    age_days: int | None = None
    days_to_expiry: int | None = None
    business_unit: str | None = None
    application: str | None = None
    environment: str | None = None
    region: str | None = None


class FindingItem(Out):
    """One finding from the register."""

    finding_id: str
    severity: str
    status: str
    source: str | None = None
    control_id: str | None = None
    owner: str | None = None
    opened: date | None = None
    due_date: date | None = None
    repeat: bool = False
    days_open: int | None = None
    days_past_due: int | None = None
    business_unit: str | None = None
    application: str | None = None
    environment: str | None = None
    region: str | None = None


class ExceptionRegister(Out):
    """The exceptions register."""

    source: RegisterSource | None
    items: list[ExceptionItem]
    skipped: int


class FindingRegister(Out):
    """The findings register."""

    source: RegisterSource | None
    items: list[FindingItem]
    skipped: int


class ControlSummary(Out):
    """A control with its rolled-up status."""

    id: str
    name: str
    owner: str
    status: Status
    metric_ids: list[str]
    requirement_count: int
    open_exceptions: int
    open_findings: int


class EvidenceOut(Out):
    """An evidence source for a control and its latest batch."""

    collector: str
    query: str
    retain_days: int
    latest: BatchRef | None


class ControlDetail(ControlSummary):
    """A control with its requirements, metrics, evidence, exceptions and findings."""

    description: str
    requirements: list[Requirement]
    metrics: list[MetricSummary]
    evidence: list[EvidenceOut]
    exceptions: list[ExceptionItem]
    findings: list[FindingItem]


class DashboardSummary(Out):
    """A dashboard in the list."""

    id: str
    title: str
    audience: str
    refresh: str


class Series(Out):
    """One metric's history for a chart."""

    metric: MetricSummary
    points: list[Point]
    baseline: float | None
    bands: Bands


class Cell(Out):
    """One heatmap or bar cell."""

    row: str
    column: str
    value: float | None
    status: Status
    measurement_id: int | None


class Bucket(Out):
    """A labelled count, such as exceptions in an age band."""

    label: str
    count: int


class Widget(Out):
    """A resolved widget. Which fields are set depends on ``widget``."""

    widget: str
    title: str
    width: int
    filtered: bool
    note: str | None = None
    metrics: list[MetricSummary] = []
    points: dict[str, Point | None] = {}
    series: list[Series] = []
    cells: list[Cell] = []
    rows: list[str] = []
    columns: list[str] = []
    buckets: list[Bucket] = []
    source: RegisterSource | None = None


class DashboardOut(DashboardSummary):
    """A dashboard with every widget's data."""

    as_of: date | None
    filters: dict[str, str]
    widgets: list[Widget]
