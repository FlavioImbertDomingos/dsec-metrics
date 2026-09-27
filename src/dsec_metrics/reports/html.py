"""HTML for the report, from a Jinja2 template with autoescaping. The PDF renderer turns
this into PDF; when it cannot, the package carries the HTML instead."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from dsec_metrics.__about__ import PRODUCT_NAME, __version__
from dsec_metrics.reports.data import TITLES, ReportData

TEMPLATES = Path(__file__).parent / "templates"


def _value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return {"percent": f"{text}%", "days": f"{text} days"}.get(unit, text)


def _delta(value: float | None) -> str:
    if value is None:
        return ""
    if value == 0:
        return "no change"
    text = f"{abs(value):,.2f}".rstrip("0").rstrip(".")
    return ("+" if value > 0 else "\N{MINUS SIGN}") + text


def _date(value: date | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%d %b %Y")


def _datetime(value: datetime | None) -> str:
    return value.strftime("%d %b %Y %H:%M UTC") if value else "—"


def environment() -> Environment:
    """The template environment. Autoescaping is on for every template."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        value=_value,
        delta=_delta,
        date=_date,
        datetime=_datetime,
        status=lambda s: str(s).capitalize(),
        human=lambda s: str(s).replace("_", " ").capitalize(),
    )
    return env


def render_html(data: ReportData) -> str:
    """The full report as one HTML document."""
    batches = sorted(data.batches.values(), key=lambda b: (b.instance_id, b.query, b.as_of))
    context: dict[str, Any] = {
        "data": data,
        "batches": batches,
        "type_title": TITLES[data.request.report_type],
        "product": PRODUCT_NAME,
        "version": __version__,
    }
    return environment().get_template("report.html.j2").render(context)
