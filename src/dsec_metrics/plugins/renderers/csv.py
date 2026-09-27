"""``csv`` renderer: each report table as a CSV file under ``evidence/tables/``."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any, ClassVar

from dsec_metrics.plugins.sdk.renderer import Renderer
from dsec_metrics.reports.tables import tables

if TYPE_CHECKING:
    from dsec_metrics.reports.data import ReportData

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def cell(value: Any) -> str:
    """Text for one cell. Values that a spreadsheet would read as a formula get a
    leading apostrophe (OWASP CSV injection guidance); numbers are left alone."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


class CsvRenderer(Renderer):
    """Report tables as CSV (UTF-8, comma separated, header row)."""

    name = "csv"
    version = "1.0.0"
    media_types: ClassVar[dict[str, str]] = {"csv": "text/csv"}

    def render(self, data: ReportData) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for table in tables(data):
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(table.columns)
            for row in table.rows:
                writer.writerow([cell(v) for v in row])
            out[f"evidence/tables/{table.name.lower()}.csv"] = buffer.getvalue().encode("utf-8")
        return out
