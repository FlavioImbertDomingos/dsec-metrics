"""Controls, and the exceptions and findings registers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from dsec_metrics.api import queries as q
from dsec_metrics.api import responses as r
from dsec_metrics.api.policy import DbDep
from dsec_metrics.api.routes.common import CatalogDep, FiltersDep, ScopeDep, not_found
from dsec_metrics.core.definitions import Control

router = APIRouter(tags=["controls"])

ControlId = Annotated[str, Path(pattern=r"^[A-Z]{2,4}-[A-Z]{2,4}-[0-9]{2,3}$")]
ControlFilter = Annotated[str | None, Query(pattern=r"^[A-Z]{2,4}-[A-Z]{2,4}-[0-9]{2,3}$")]
StatusFilter = Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")]


def _summary(
    control: Control,
    latest: dict[str, r.Point],
    exceptions: list[r.ExceptionItem],
    findings: list[r.FindingItem],
) -> r.ControlSummary:
    statuses = [latest[m].status if m in latest else "unknown" for m in control.metrics]
    return r.ControlSummary(
        id=control.id,
        name=control.name,
        owner=control.owner,
        status=q.worst(statuses),  # type: ignore[arg-type]
        metric_ids=list(control.metrics),
        requirement_count=len(control.requirements),
        open_exceptions=sum(
            1 for e in exceptions if e.control_id == control.id and q.is_open_exception(e)
        ),
        open_findings=sum(
            1 for f in findings if f.control_id == control.id and q.is_open_finding(f)
        ),
    )


@router.get("/controls")
def list_controls(db: DbDep, catalog: CatalogDep, scope: ScopeDep) -> list[r.ControlSummary]:
    """Every control with the worst status of its metrics and its open items."""
    latest = q.latest_overall(db, catalog.metrics)
    exceptions = q.load_register(db, catalog, "exceptions", scope).exceptions
    findings = q.load_register(db, catalog, "findings", scope).findings
    return [
        _summary(c, latest, exceptions, findings)
        for c in sorted(catalog.controls.values(), key=lambda c: c.id)
    ]


@router.get("/controls/{control_id}")
def get_control(
    control_id: ControlId, db: DbDep, catalog: CatalogDep, scope: ScopeDep
) -> r.ControlDetail:
    """A control with its requirements, metrics, evidence, exceptions and findings."""
    control = catalog.controls.get(control_id)
    if control is None:
        raise not_found("Control")
    latest = q.latest_overall(db, control.metrics)
    exceptions = q.load_register(db, catalog, "exceptions", scope, {"control_id": control_id})
    findings = q.load_register(db, catalog, "findings", scope, {"control_id": control_id})
    batches = q.latest_source_batches(
        db, [(e.collector, e.query) for e in control.evidence], with_records=False
    )
    summary = _summary(control, latest, exceptions.exceptions, findings.findings)
    return r.ControlDetail(
        **summary.model_dump(),
        description=control.description,
        requirements=[catalog.requirement(ref) for ref in control.requirements],
        metrics=[
            q.metric_summary(catalog.metrics[m], latest.get(m))
            for m in control.metrics
            if m in catalog.metrics
        ],
        evidence=[
            r.EvidenceOut(
                collector=e.collector,
                query=e.query,
                retain_days=e.retain_days,
                latest=q.batch_ref(found[0])
                if (found := batches[(e.collector, e.query)])
                else None,
            )
            for e in control.evidence
        ],
        exceptions=exceptions.exceptions,
        findings=findings.findings,
    )


@router.get("/exceptions")
def list_exceptions(
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
    filters: FiltersDep,
    status: StatusFilter = None,
    control_id: ControlFilter = None,
) -> r.ExceptionRegister:
    """The exceptions register, with age and days to expiry counted to its as-of date."""
    wanted = dict(filters)
    if status:
        wanted["status"] = status
    if control_id:
        wanted["control_id"] = control_id
    data = q.load_register(db, catalog, "exceptions", scope, wanted)
    return r.ExceptionRegister(source=data.source, items=data.exceptions, skipped=data.skipped)


@router.get("/findings")
def list_findings(
    db: DbDep,
    catalog: CatalogDep,
    scope: ScopeDep,
    filters: FiltersDep,
    status: StatusFilter = None,
    severity: Annotated[str | None, Query(pattern=r"^[a-z]{1,16}$")] = None,
    control_id: ControlFilter = None,
) -> r.FindingRegister:
    """The findings register."""
    wanted = dict(filters)
    for key, value in (("status", status), ("severity", severity), ("control_id", control_id)):
        if value:
            wanted[key] = value
    data = q.load_register(db, catalog, "findings", scope, wanted)
    return r.FindingRegister(source=data.source, items=data.findings, skipped=data.skipped)
