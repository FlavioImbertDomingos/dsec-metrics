"""Tabular views of report data, shared by the XLSX and CSV renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dsec_metrics.reports.data import ReportData


@dataclass(frozen=True)
class Table:
    """A named table with a header row."""

    name: str
    columns: list[str]
    rows: list[list[Any]]


def tables(data: ReportData) -> list[Table]:
    """Every table the report has, in a stable order. Empty tables are left out."""
    out: list[Table] = []
    metrics = data.all_metric_lines()
    if metrics:
        out.append(
            Table(
                "Indicators",
                [
                    "metric_id",
                    "name",
                    "status",
                    "value",
                    "unit",
                    "as_of",
                    "delta_previous",
                    "delta_baseline",
                    "distance_to_target",
                    "target",
                    "owner",
                    "measurement_id",
                    "definition_version",
                    "definition_sha256",
                ],
                [
                    [
                        m.metric.id,
                        m.metric.name,
                        m.status,
                        m.point.value if m.point else None,
                        m.metric.unit,
                        m.point.as_of.isoformat() if m.point else None,
                        m.point.delta_previous if m.point else None,
                        m.point.delta_baseline if m.point else None,
                        m.point.distance_to_target if m.point else None,
                        m.metric.target,
                        m.metric.owner,
                        m.point.measurement_id if m.point else None,
                        m.version,
                        m.sha256,
                    ]
                    for m in metrics
                ],
            )
        )
        history = [
            [m.metric.id, p.as_of.isoformat(), p.value, p.status, p.measurement_id]
            for m in metrics
            for p in m.history
        ]
        if history:
            out.append(
                Table(
                    "History", ["metric_id", "as_of", "value", "status", "measurement_id"], history
                )
            )
    if data.controls:
        out.append(
            Table(
                "Controls",
                [
                    "control_id",
                    "name",
                    "owner",
                    "status",
                    "requirements",
                    "metrics",
                    "open_exceptions",
                    "open_findings",
                    "evidence_batches",
                ],
                [
                    [
                        c.control.id,
                        c.control.name,
                        c.control.owner,
                        c.status,
                        ", ".join(c.control.requirements),
                        ", ".join(c.control.metrics),
                        len(c.exceptions),
                        len(c.findings),
                        ", ".join(b.sha256 for b in c.evidence),
                    ]
                    for c in data.controls
                ],
            )
        )
    exceptions = data.exceptions or [e for c in data.controls for e in c.exceptions]
    if exceptions:
        fields = list(type(exceptions[0]).model_fields)
        out.append(
            Table("Exceptions", fields, [[getattr(e, f) for f in fields] for e in exceptions])
        )
    findings = data.findings or [f for c in data.controls for f in c.findings]
    if findings:
        fields = list(type(findings[0]).model_fields)
        out.append(Table("Findings", fields, [[getattr(x, f) for f in fields] for x in findings]))
    out.append(
        Table(
            "Custody",
            [
                "sha256",
                "instance_id",
                "collector",
                "collector_version",
                "query",
                "as_of",
                "collected_at",
                "record_count",
                "pans_masked",
                "fields_dropped",
            ],
            [
                [
                    b.sha256,
                    b.instance_id,
                    b.collector,
                    b.collector_version,
                    b.query,
                    b.as_of.isoformat(),
                    b.collected_at.isoformat(),
                    b.record_count,
                    (b.redaction or {}).get("pans_masked", 0),
                    ", ".join((b.redaction or {}).get("fields_dropped", {}) or {}),
                ]
                for b in sorted(data.batches.values(), key=lambda b: (b.instance_id, b.query))
            ],
        )
    )
    return out
