"""Dashboards: the layout from YAML with every widget's data resolved in one response."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Path
from sqlalchemy.orm import Session

from dsec_metrics.api import queries as q
from dsec_metrics.api import responses as r
from dsec_metrics.api.policy import DbDep
from dsec_metrics.api.routes.common import CatalogDep, FiltersDep, ScopeDep, not_found
from dsec_metrics.core.definitions import ID_PATTERN, Dashboard, Metric, Widget

router = APIRouter(tags=["dashboards"])

DashboardId = Annotated[str, Path(pattern=ID_PATTERN)]
SEVERITIES = ("critical", "high", "medium", "low")
LABELS = {
    "stat": "Indicator",
    "trend": "Trend",
    "bar": "Breakdown",
    "table": "Indicators",
    "rag_list": "Status",
    "heatmap": "Status map",
    "exceptions_aging": "Exceptions by age",
    "findings_burndown": "Findings",
}


@router.get("/dashboards")
def list_dashboards(catalog: CatalogDep, scope: ScopeDep) -> list[r.DashboardSummary]:
    """Every dashboard and its audience."""
    del scope
    return [
        r.DashboardSummary(id=d.id, title=d.title, audience=d.audience.value, refresh=d.refresh)
        for d in sorted(catalog.dashboards.values(), key=lambda d: d.id)
    ]


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(
    dashboard_id: DashboardId,
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
    filters: FiltersDep,
) -> r.DashboardOut:
    """A dashboard with every widget's data, read from stored measurements."""
    dashboard = catalog.dashboards.get(dashboard_id)
    if dashboard is None:
        raise not_found("Dashboard")
    return Resolver(db, catalog, dashboard, filters, scope).resolve()


class Resolver:
    """Fetches everything a dashboard needs in a few queries, then builds each widget."""

    def __init__(
        self,
        db: Session,
        catalog: q.Catalog,
        dashboard: Dashboard,
        filters: Mapping[str, str],
        scope: q.Scope,
    ) -> None:
        self.db = db
        self.catalog = catalog
        self.dashboard = dashboard
        self.filters = dict(filters)
        self.scope = scope
        ids = {m for w in dashboard.layout for m in w.metric_ids() if m in catalog.metrics}
        self.metrics: dict[str, Metric] = {m: catalog.metrics[m] for m in sorted(ids)}
        self.latest = q.latest_overall(db, self.metrics)
        self.choices = {
            m: q.choose_slice(metric, self.filters) for m, metric in self.metrics.items()
        }
        periods = max((w.periods for w in dashboard.layout), default=12)
        self.history = q.histories(db, [(m, c.key) for m, c in self.choices.items()], periods)
        needs_slices = {
            m for w in dashboard.layout if w.widget in {"bar", "heatmap"} for m in w.metric_ids()
        }
        self.slices = q.latest_slices(db, needs_slices & set(self.metrics), scope)
        kinds = {w.widget for w in dashboard.layout}
        self.exceptions = (
            q.load_register(db, catalog, "exceptions", scope, self.filters)
            if "exceptions_aging" in kinds
            else None
        )
        self.findings = (
            q.load_register(db, catalog, "findings", scope, self.filters)
            if "findings_burndown" in kinds
            else None
        )

    def resolve(self) -> r.DashboardOut:
        """Build the response."""
        dates = [p.as_of for p in self.latest.values()]
        return r.DashboardOut(
            id=self.dashboard.id,
            title=self.dashboard.title,
            audience=self.dashboard.audience.value,
            refresh=self.dashboard.refresh,
            as_of=max(dates) if dates else None,
            filters=self.filters,
            widgets=[self.widget(w) for w in self.dashboard.layout],
        )

    # Helpers.

    def summary(self, metric_id: str) -> r.MetricSummary:
        return q.metric_summary(self.metrics[metric_id], self.latest.get(metric_id))

    def points(self, metric_id: str) -> list[r.Point]:
        choice = self.choices[metric_id]
        if not self.scope.allows(choice.dimensions):
            return []
        return self.history.get((metric_id, choice.key), [])

    def current(self, metric_id: str) -> r.Point | None:
        points = self.points(metric_id)
        return points[-1] if points else None

    def series(self, metric_id: str, periods: int) -> r.Series:
        metric = self.metrics[metric_id]
        choice = self.choices[metric_id]
        return r.Series(
            metric=self.summary(metric_id),
            points=self.points(metric_id)[-periods:],
            baseline=metric.baseline.value if metric.baseline and not choice.dimensions else None,
            bands=q.bands_for(metric.thresholds, choice.dimensions),
        )

    def filter_note(self, metric_ids: list[str]) -> tuple[bool, str | None]:
        if not self.filters:
            return False, None
        unfiltered = [m for m in metric_ids if self.choices[m].ignored]
        if not unfiltered:
            return True, None
        dims = sorted({d for m in unfiltered for d in self.choices[m].ignored})
        names = ", ".join(unfiltered)
        by = ", ".join(d.replace("_", " ") for d in dims)
        return False, f"{names} not broken down by {by}; showing overall values."

    def slice_cells(self, metric_id: str, dimension: str) -> list[r.Cell]:
        """Latest slices of a metric grouped by exactly ``dimension``."""
        cells = []
        for s in self.slices.get(metric_id, []):
            if set(s.dimensions) != {dimension}:
                continue
            label = s.dimensions[dimension]
            if dimension in self.filters and self.filters[dimension] != label:
                continue
            cells.append(
                r.Cell(
                    row=label,
                    column=metric_id,
                    value=s.point.value,
                    status=s.point.status,
                    measurement_id=s.point.measurement_id,
                )
            )
        return sorted(cells, key=lambda c: c.row)

    # Widgets.

    def widget(self, w: Widget) -> r.Widget:
        ids = [m for m in w.metric_ids() if m in self.metrics]
        title = w.title or (self.metrics[ids[0]].name if len(ids) == 1 else LABELS[w.widget])
        filtered, note = self.filter_note(ids)
        base: dict[str, Any] = {"widget": w.widget, "title": title, "width": w.width}
        if w.widget in {"stat", "table", "rag_list"}:
            return r.Widget(
                **base,
                filtered=filtered,
                note=note,
                metrics=[self.summary(m) for m in ids],
                points={m: self.current(m) for m in ids},
                series=[self.series(m, w.periods) for m in ids] if w.widget == "stat" else [],
            )
        if w.widget == "trend":
            return r.Widget(
                **base,
                filtered=filtered,
                note=note,
                metrics=[self.summary(m) for m in ids],
                points={m: self.current(m) for m in ids},
                series=[self.series(m, w.periods) for m in ids],
            )
        if w.widget in {"bar", "heatmap"}:
            return self.grid(w, ids, base)
        if w.widget == "exceptions_aging":
            data = self.exceptions or q.RegisterData(source=None)
            return r.Widget(
                **base,
                filtered=bool(self.filters),
                metrics=[self.summary(m) for m in ids],
                points={m: self.current(m) for m in ids},
                buckets=q.age_buckets(data.exceptions),
                source=data.source,
            )
        # findings_burndown
        data = self.findings or q.RegisterData(source=None)
        open_by = Counter(f.severity for f in data.findings if q.is_open_finding(f))
        return r.Widget(
            **base,
            filtered=filtered,
            note=note,
            metrics=[self.summary(m) for m in ids],
            points={m: self.current(m) for m in ids},
            series=[self.series(m, w.periods) for m in ids],
            buckets=[r.Bucket(label=s, count=open_by.get(s, 0)) for s in SEVERITIES],
            source=data.source,
        )

    def grid(self, w: Widget, ids: list[str], base: dict[str, Any]) -> r.Widget:
        dimension = w.rows if w.rows and w.rows != "metric" else "business_unit"
        cells: list[r.Cell] = []
        missing = []
        for m in ids:
            found = self.slice_cells(m, dimension)
            if not found:
                missing.append(m)
            cells.extend(found)
        if w.widget == "heatmap" and w.columns == "control":
            cells = self.control_cells(cells)
        note = None
        if missing:
            by = dimension.replace("_", " ")
            note = f"No breakdown by {by} for {', '.join(missing)}."
        rows = sorted({c.row for c in cells})
        columns = list(dict.fromkeys(c.column for c in cells))
        return r.Widget(
            **base,
            filtered=bool(self.filters) and not missing,
            note=note,
            metrics=[self.summary(m) for m in ids],
            cells=cells,
            rows=rows,
            columns=columns,
        )

    def control_cells(self, metric_cells: list[r.Cell]) -> list[r.Cell]:
        """Roll metric cells up to controls: the worst status of the control's metrics."""
        by_metric: dict[tuple[str, str], r.Cell] = {(c.column, c.row): c for c in metric_cells}
        rows = sorted({c.row for c in metric_cells})
        out = []
        for control in sorted(self.catalog.controls.values(), key=lambda c: c.id):
            used = [m for m in control.metrics if any((m, row) in by_metric for row in rows)]
            if not used:
                continue
            for row in rows:
                statuses = [by_metric[(m, row)].status for m in used if (m, row) in by_metric]
                out.append(
                    r.Cell(
                        row=row,
                        column=control.id,
                        value=None,
                        status=q.worst(statuses),  # type: ignore[arg-type]
                        measurement_id=None,
                    )
                )
        return out
