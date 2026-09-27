"""``json`` renderer: the report data as one JSON document, for other tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from dsec_metrics.plugins.sdk.renderer import Renderer
from dsec_metrics.reports.tables import tables

if TYPE_CHECKING:
    from dsec_metrics.reports.data import ReportData


class JsonRenderer(Renderer):
    """Report metadata and tables as JSON. Batch records are in evidence/, not here."""

    name = "json"
    version = "1.0.0"
    media_types: ClassVar[dict[str, str]] = {"json": "application/json"}

    def render(self, data: ReportData) -> dict[str, bytes]:
        doc: dict[str, Any] = {
            "title": data.title,
            "type": data.request.report_type.value,
            "scope": data.request.scope(),
            "period": {
                "start": data.request.period_start.isoformat(),
                "end": data.request.period_end.isoformat(),
            },
            "prepared_for": data.request.prepared_for,
            "generated_at": data.generated_at.isoformat(),
            "generated_by": data.generated_by,
            "signing_key_fingerprint": data.key_fingerprint,
            "frameworks": data.frameworks,
            "summary": data.summary,
            "method": data.method,
            "tables": {
                t.name.lower(): [dict(zip(t.columns, row, strict=True)) for row in t.rows]
                for t in tables(data)
            },
        }
        if data.reproduction is not None:
            doc["reproduction"] = {
                "measurement_id": data.reproduction.measurement_id,
                "as_of": data.reproduction.as_of.isoformat(),
                "dimensions": data.reproduction.dimensions,
                "calculation": data.reproduction.calculation,
            }
        text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        return {"report.json": text.encode("utf-8") + b"\n"}
