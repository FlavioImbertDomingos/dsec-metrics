"""Collect everything a report needs from stored data, for one type, scope and period.

Reports never collect anything live. Measurements are the newest in the period for each
metric; evidence and registers come from the newest successful collection in the period.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from dsec_metrics.api import queries as q
from dsec_metrics.api import responses as r
from dsec_metrics.core.definitions import Control, Metric
from dsec_metrics.db.models import DefinitionVersion, MeasurementRow, RecordBatchRow


class ReportType(StrEnum):
    """The six report types from the brief."""

    CONTROL = "control"
    FRAMEWORK = "framework"
    REPRODUCIBILITY = "reproducibility"
    RISK_COMMITTEE = "risk_committee"
    MANAGEMENT = "management"
    EXCEPTIONS = "exceptions"


TITLES = {
    ReportType.CONTROL: "Control evidence package",
    ReportType.FRAMEWORK: "Framework period report",
    ReportType.REPRODUCIBILITY: "Metric reproducibility report",
    ReportType.RISK_COMMITTEE: "Risk committee pack",
    ReportType.MANAGEMENT: "Management report",
    ReportType.EXCEPTIONS: "Exceptions register export",
}

METHOD = {
    ReportType.CONTROL: (
        "Each metric shows its newest measurement in the period. Evidence is the newest "
        "successful collection in the period from each source the control names, "
        "included in full under evidence/."
    ),
    ReportType.FRAMEWORK: (
        "Controls are included when they map to a selected requirement. Each shows the "
        "newest measurement of its metrics in the period and the evidence collected for it."
    ),
    ReportType.REPRODUCIBILITY: (
        "The definition version, the input batches and the calculation record are included, "
        "so the value can be recomputed. Run `dsec-metrics reproduce` on this package to do "
        "that with the same evaluator."
    ),
    ReportType.RISK_COMMITTEE: (
        "Key risk indicators for the risk committee, newest measurement in the period, with "
        "owner and the agreed action for anything red."
    ),
    ReportType.MANAGEMENT: (
        "Program indicators for management: every measurement in the period, with baseline "
        "and target."
    ),
    ReportType.EXCEPTIONS: (
        "The exceptions register from its newest collection in the period. Ages and days to "
        "expiry are counted to that collection's as-of date."
    ),
}


class ReportRequest(BaseModel):
    """What to build. ``scope`` keys depend on the type (see ``check_scope``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_type: ReportType
    period_start: date
    period_end: date
    control_id: str | None = Field(default=None, pattern=r"^[A-Z]{2,4}-[A-Z]{2,4}-[0-9]{2,3}$")
    framework: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")
    requirements: list[str] = Field(default_factory=list, max_length=50)
    metric_id: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,7}-[0-9]{2,4}$")
    measurement_id: int | None = Field(default=None, ge=1)
    prepared_for: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def check_scope(self) -> ReportRequest:
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        if (self.period_end - self.period_start).days > 732:
            raise ValueError("period is longer than two years")
        needs = {
            ReportType.CONTROL: ("control_id", self.control_id),
            ReportType.FRAMEWORK: ("framework", self.framework),
            ReportType.REPRODUCIBILITY: ("metric_id", self.metric_id),
        }
        if self.report_type in needs:
            name, value = needs[self.report_type]
            if not value:
                raise ValueError(f"{self.report_type.value} reports need {name}")
        for ref in self.requirements:
            if not ref or len(ref) > 32 or not all(c.isalnum() or c in ".-" for c in ref):
                raise ValueError("requirements are requirement ids or prefixes like 3.7")
        return self

    def scope(self) -> dict[str, Any]:
        """The scope fields that apply to this type, for the manifest."""
        keys = {
            ReportType.CONTROL: ["control_id"],
            ReportType.FRAMEWORK: ["framework", "requirements"],
            ReportType.REPRODUCIBILITY: ["metric_id", "measurement_id"],
        }.get(self.report_type, [])
        return {k: getattr(self, k) for k in keys if getattr(self, k) not in (None, [])}


class ReportError(ValueError):
    """The request names something that does not exist or has no data in the period."""


@dataclass
class MetricLine:
    """One metric's value in the report."""

    metric: Metric
    version: int
    sha256: str
    point: r.Point | None
    history: list[r.Point] = field(default_factory=list)
    input_batches: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.point.status if self.point else "unknown"


@dataclass
class ControlSection:
    """One control with its requirements, metrics, evidence and open items."""

    control: Control
    status: str
    requirements: list[r.Requirement]
    metrics: list[MetricLine]
    evidence: list[RecordBatchRow]
    exceptions: list[r.ExceptionItem]
    findings: list[r.FindingItem]


@dataclass
class Reproduction:
    """What a reproducibility report needs beyond a metric line."""

    measurement_id: int
    as_of: date
    dimensions: dict[str, str]
    definition: dict[str, Any]
    calculation: dict[str, Any]


@dataclass
class ReportData:
    """Everything the renderers need, gathered once."""

    request: ReportRequest
    title: str
    generated_at: datetime
    generated_by: str
    key_fingerprint: str
    method: str
    controls: list[ControlSection] = field(default_factory=list)
    metrics: list[MetricLine] = field(default_factory=list)
    exceptions: list[r.ExceptionItem] = field(default_factory=list)
    findings: list[r.FindingItem] = field(default_factory=list)
    register_source: r.RegisterSource | None = None
    reproduction: Reproduction | None = None
    batches: dict[str, RecordBatchRow] = field(default_factory=dict)
    definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        """Counts by status: of controls when there are any, otherwise of metrics."""
        statuses = [c.status for c in self.controls] or [m.status for m in self.metrics]
        counts = Counter(statuses)
        return {s: counts.get(s, 0) for s in ("red", "amber", "unknown", "green")}

    def all_metric_lines(self) -> list[MetricLine]:
        """Every metric line, from controls and from the top level, without repeats."""
        seen: dict[str, MetricLine] = {}
        for line in [*self.metrics, *(m for c in self.controls for m in c.metrics)]:
            seen.setdefault(line.metric.id, line)
        return list(seen.values())


def _history(
    db: Session, metric_ids: list[str], start: date, end: date
) -> dict[str, list[tuple[r.Point, list[str], str]]]:
    """Overall measurements per metric in the period, oldest first, newest row per date,
    with each one's input batch hashes and definition hash."""
    if not metric_ids:
        return {}
    rows = db.execute(
        select(
            MeasurementRow.id,
            MeasurementRow.metric_id,
            MeasurementRow.as_of,
            MeasurementRow.value,
            MeasurementRow.status,
            MeasurementRow.delta_previous,
            MeasurementRow.delta_baseline,
            MeasurementRow.distance_to_target,
            MeasurementRow.definition_version,
            MeasurementRow.definition_sha256,
            MeasurementRow.input_batch_hashes,
        )
        .where(
            and_(
                MeasurementRow.metric_id.in_(metric_ids),
                MeasurementRow.dims_key == q.OVERALL,
                MeasurementRow.as_of >= start,
                MeasurementRow.as_of <= end,
            )
        )
        .distinct(MeasurementRow.metric_id, MeasurementRow.as_of)
        .order_by(MeasurementRow.metric_id, MeasurementRow.as_of, MeasurementRow.id.desc())
    ).all()
    out: dict[str, list[tuple[r.Point, list[str], str]]] = {}
    for row in rows:
        out.setdefault(row.metric_id, []).append(
            (q.to_point(row), list(row.input_batch_hashes), row.definition_sha256)
        )
    return out


class Collector:
    """Builds ``ReportData`` for one request."""

    def __init__(
        self,
        db: Session,
        request: ReportRequest,
        generated_by: str,
        generated_at: datetime,
        key_fingerprint: str,
    ) -> None:
        self.db = db
        self.req = request
        self.catalog = q.load_catalog(db)
        self.data = ReportData(
            request=request,
            title=TITLES[request.report_type],
            generated_at=generated_at,
            generated_by=generated_by,
            key_fingerprint=key_fingerprint,
            method=METHOD[request.report_type],
        )

    # Building blocks.

    def lines(self, metric_ids: list[str]) -> list[MetricLine]:
        ids = [m for m in metric_ids if m in self.catalog.metrics]
        history = _history(self.db, ids, self.req.period_start, self.req.period_end)
        out = []
        for mid in ids:
            points = history.get(mid, [])
            current = self.catalog.versions[("metric", mid)]
            latest = points[-1] if points else None
            # Report the definition version the newest measurement actually used.
            used = current
            if latest is not None and latest[2] != current.sha256:
                used = (
                    self.db.scalars(
                        select(DefinitionVersion).where(
                            DefinitionVersion.kind == "metric",
                            DefinitionVersion.def_id == mid,
                            DefinitionVersion.sha256 == latest[2],
                        )
                    ).first()
                    or current
                )
            out.append(
                MetricLine(
                    metric=self.catalog.metrics[mid],
                    version=used.version,
                    sha256=used.sha256,
                    point=latest[0] if latest else None,
                    history=[p for p, _, _ in points],
                    input_batches=latest[1] if latest else [],
                )
            )
            self.data.definitions[mid] = used.body
        return out

    def add_batches(self, hashes: list[str]) -> None:
        wanted = [h for h in hashes if h not in self.data.batches]
        if not wanted:
            return
        rows = self.db.scalars(
            select(RecordBatchRow)
            .where(RecordBatchRow.sha256.in_(wanted))
            .order_by(RecordBatchRow.collected_at)
        ).all()
        for row in rows:
            self.data.batches[row.sha256] = row

    def evidence(self, control: Control) -> list[RecordBatchRow]:
        found = q.latest_source_batches(
            self.db,
            [(e.collector, e.query) for e in control.evidence],
            with_records=True,
            as_of_min=self.req.period_start,
            as_of_max=self.req.period_end,
        )
        batches = [b for rows in found.values() for b in rows]
        for b in batches:
            self.data.batches.setdefault(b.sha256, b)
        return batches

    def registers(self) -> tuple[q.RegisterData, q.RegisterData]:
        exc = q.load_register(
            self.db, self.catalog, "exceptions", q.EVERYTHING, as_of_max=self.req.period_end
        )
        fnd = q.load_register(
            self.db, self.catalog, "findings", q.EVERYTHING, as_of_max=self.req.period_end
        )
        for reg in (exc, fnd):
            for b in reg.batches:
                self.data.batches.setdefault(b.sha256, b)
        return exc, fnd

    def section(self, control: Control, exc: q.RegisterData, fnd: q.RegisterData) -> ControlSection:
        metrics = self.lines(list(control.metrics))
        for line in metrics:
            self.add_batches(line.input_batches)
        return ControlSection(
            control=control,
            status=q.worst(line.status for line in metrics) if metrics else "unknown",
            requirements=[self.catalog.requirement(ref) for ref in control.requirements],
            metrics=metrics,
            evidence=self.evidence(control),
            exceptions=[e for e in exc.exceptions if e.control_id == control.id],
            findings=[f for f in fnd.findings if f.control_id == control.id],
        )

    def packs(self, refs: list[str]) -> None:
        packs = {ref.split(":", 1)[0] for ref in refs}
        self.data.frameworks = sorted(set(self.data.frameworks) | packs)

    # Types.

    def build(self) -> ReportData:
        handler = {
            ReportType.CONTROL: self.control,
            ReportType.FRAMEWORK: self.framework,
            ReportType.REPRODUCIBILITY: self.reproducibility,
            ReportType.RISK_COMMITTEE: lambda: self.audience("risk_committee"),
            ReportType.MANAGEMENT: lambda: self.audience("management"),
            ReportType.EXCEPTIONS: self.exceptions,
        }[self.req.report_type]
        handler()
        return self.data

    def control(self) -> None:
        control = self.catalog.controls.get(self.req.control_id or "")
        if control is None:
            raise ReportError("unknown control")
        exc, fnd = self.registers()
        self.data.controls = [self.section(control, exc, fnd)]
        self.data.title = f"{TITLES[ReportType.CONTROL]}: {control.id}"
        self.packs(list(control.requirements))

    def framework(self) -> None:
        pack = self.catalog.frameworks.get(self.req.framework or "")
        if pack is None:
            raise ReportError("unknown framework")
        prefixes = self.req.requirements

        def selected(ref: str) -> bool:
            name, _, local = ref.partition(":")
            if name != pack.id:
                return False
            return not prefixes or any(
                local == p or local.startswith((p + ".", p + "-")) for p in prefixes
            )

        controls = [
            c
            for c in sorted(self.catalog.controls.values(), key=lambda c: c.id)
            if any(selected(ref) for ref in c.requirements)
        ]
        if not controls:
            raise ReportError("no control maps to the selected requirements")
        exc, fnd = self.registers()
        self.data.controls = [self.section(c, exc, fnd) for c in controls]
        chosen = ", ".join(prefixes) if prefixes else "all requirements"
        self.data.title = f"{pack.name} {pack.version}: {chosen}"
        self.data.frameworks = [pack.id]

    def reproducibility(self) -> None:
        metric = self.catalog.metrics.get(self.req.metric_id or "")
        if metric is None:
            raise ReportError("unknown metric")
        stmt = select(MeasurementRow).where(MeasurementRow.metric_id == metric.id)
        if self.req.measurement_id is not None:
            stmt = stmt.where(MeasurementRow.id == self.req.measurement_id)
        else:
            stmt = stmt.where(
                MeasurementRow.dims_key == q.OVERALL,
                MeasurementRow.as_of >= self.req.period_start,
                MeasurementRow.as_of <= self.req.period_end,
            )
        row = self.db.scalars(
            stmt.order_by(MeasurementRow.as_of.desc(), MeasurementRow.id.desc()).limit(1)
        ).first()
        if row is None:
            raise ReportError("no measurement of this metric in the period")
        definition = self.db.get(DefinitionVersion, row.definition_id)
        body = definition.body if definition else {}
        self.data.metrics = [
            MetricLine(
                metric=metric,
                version=row.definition_version,
                sha256=row.definition_sha256,
                point=q.to_point(row),
                history=[q.to_point(row)],
                input_batches=list(row.input_batch_hashes),
            )
        ]
        self.data.definitions[metric.id] = body
        self.data.reproduction = Reproduction(
            measurement_id=row.id,
            as_of=row.as_of,
            dimensions=dict(row.dimensions),
            definition=body,
            calculation=dict(row.calculation),
        )
        self.add_batches(list(row.input_batch_hashes))
        self.data.title = f"{TITLES[ReportType.REPRODUCIBILITY]}: {metric.id}"
        self.packs(list(metric.frameworks))

    def audience(self, audience: str) -> None:
        ids = sorted(
            m.id for m in self.catalog.metrics.values() if audience in {a.value for a in m.audience}
        )
        self.data.metrics = self.lines(ids)
        for line in self.data.metrics:
            self.add_batches(line.input_batches)
            self.packs(list(line.metric.frameworks))

    def exceptions(self) -> None:
        exc, _ = self.registers()
        if exc.source is None:
            raise ReportError("the exceptions register has no collection in the period")
        self.data.exceptions = exc.exceptions
        self.data.register_source = exc.source
        refs = [
            ref
            for e in exc.exceptions
            if e.control_id and e.control_id in self.catalog.controls
            for ref in self.catalog.controls[e.control_id].requirements
        ]
        self.packs(refs)


def collect(
    db: Session,
    request: ReportRequest,
    generated_by: str,
    generated_at: datetime,
    key_fingerprint: str,
) -> ReportData:
    """Gather the data for one report."""
    return Collector(db, request, generated_by, generated_at, key_fingerprint).build()
