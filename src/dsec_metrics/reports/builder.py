"""Build, store and reproduce evidence packages."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from dsec_metrics import audit
from dsec_metrics.core.canonical import canonical_hash
from dsec_metrics.core.definitions import Metric
from dsec_metrics.core.evaluator import InputBatch, evaluate
from dsec_metrics.db.models import RecordBatchRow, ReportPackage
from dsec_metrics.plugins.renderers.csv import CsvRenderer
from dsec_metrics.plugins.renderers.json import JsonRenderer
from dsec_metrics.plugins.renderers.pdf import HtmlRenderer, PdfRenderer
from dsec_metrics.plugins.renderers.xlsx import XlsxRenderer
from dsec_metrics.plugins.sdk.renderer import Renderer
from dsec_metrics.reports.data import ReportData, ReportRequest, collect
from dsec_metrics.reports.package import (
    BuiltPackage,
    PackageFile,
    build_package,
    json_file,
)
from dsec_metrics.reports.signing import SigningKey
from dsec_metrics.reports.verify import verify_package


def renderers() -> list[Renderer]:
    """PDF when WeasyPrint can run here, otherwise HTML; then XLSX, JSON and CSV."""
    pdf = PdfRenderer()
    first: Renderer = pdf if pdf.available() else HtmlRenderer()
    return [first, XlsxRenderer(), JsonRenderer(), CsvRenderer()]


def _batch_file(batch: RecordBatchRow) -> PackageFile:
    return json_file(
        f"evidence/batches/{batch.sha256}.json",
        {
            "sha256": batch.sha256,
            "instance_id": batch.instance_id,
            "collector": batch.collector,
            "collector_version": batch.collector_version,
            "query": batch.query,
            "params": batch.params,
            "as_of": batch.as_of.isoformat(),
            "collected_at": batch.collected_at.isoformat(),
            "record_count": batch.record_count,
            "redaction": batch.redaction,
            "records": batch.records,
        },
        source=f"{batch.instance_id}/{batch.query}",
        collected_at=batch.collected_at.isoformat(),
        record={"batch_sha256": batch.sha256, "run_id": str(batch.run_id)},
    )


def package_files(data: ReportData) -> tuple[list[PackageFile], bool]:
    """Every file in the package, and whether the PDF was rendered."""
    files: list[PackageFile] = []
    pdf = False
    for renderer in renderers():
        for path, content in renderer.render(data).items():
            ext = path.rsplit(".", 1)[-1]
            files.append(
                PackageFile(
                    path,
                    content,
                    renderer.media_types.get(ext, "application/octet-stream"),
                    f"renderer:{renderer.name} {renderer.version}",
                )
            )
            pdf = pdf or path == "report.pdf"
    for batch in sorted(data.batches.values(), key=lambda b: b.sha256):
        files.append(_batch_file(batch))
    for line in data.all_metric_lines():
        files.append(
            json_file(
                f"evidence/definitions/{line.metric.id}-v{line.version}.json",
                data.definitions.get(line.metric.id, {}),
                source="definitions",
                record={
                    "metric_id": line.metric.id,
                    "version": line.version,
                    "sha256": line.sha256,
                    "measurement_id": line.point.measurement_id if line.point else None,
                },
            )
        )
    return files, pdf


def report_metadata(data: ReportData, pdf: bool) -> dict[str, Any]:
    """The ``report`` block of the manifest."""
    meta: dict[str, Any] = {
        "type": data.request.report_type.value,
        "title": data.title,
        "scope": data.request.scope(),
        "period": {
            "start": data.request.period_start.isoformat(),
            "end": data.request.period_end.isoformat(),
        },
        "prepared_for": data.request.prepared_for,
        "generated_at": data.generated_at.isoformat(),
        "generated_by": data.generated_by,
        "frameworks": data.frameworks,
        "summary": data.summary,
        "pdf_rendered": pdf,
        "measurements": sorted(
            m.point.measurement_id for m in data.all_metric_lines() if m.point is not None
        ),
    }
    if data.reproduction is not None:
        line = data.metrics[0]
        meta["reproduction"] = {
            "metric_id": line.metric.id,
            "measurement_id": data.reproduction.measurement_id,
            "as_of": data.reproduction.as_of.isoformat(),
            "dimensions": data.reproduction.dimensions,
            "value": line.point.value if line.point else None,
            "status": line.status,
            "definition_file": f"evidence/definitions/{line.metric.id}-v{line.version}.json",
            "batch_files": [f"evidence/batches/{h}.json" for h in sorted(line.input_batches)],
        }
    return meta


@dataclass(frozen=True)
class Generated:
    """A stored package."""

    row: ReportPackage
    built: BuiltPackage
    data: ReportData


def generate(
    db: Session,
    request: ReportRequest,
    key: SigningKey,
    actor: str,
    now: datetime | None = None,
) -> Generated:
    """Collect, render, sign, store, and write the audit event, in the caller's transaction."""
    when = (now or datetime.now(UTC)).replace(microsecond=0)
    data = collect(db, request, actor, when, key.fingerprint)
    files, pdf = package_files(data)
    built = build_package(files, report_metadata(data, pdf), key)
    row = ReportPackage(
        report_type=request.report_type.value,
        title=data.title[:256],
        scope=request.scope(),
        period_start=request.period_start,
        period_end=request.period_end,
        frameworks=data.frameworks,
        manifest_sha256=built.manifest_sha256,
        key_fingerprint=built.fingerprint,
        pdf_rendered=pdf,
        generated_by=actor,
        generated_at=when,
        size=len(built.content),
        content=built.content,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor,
        "report.generate",
        f"report:{row.id}",
        {
            "type": row.report_type,
            "title": row.title,
            "period": [row.period_start.isoformat(), row.period_end.isoformat()],
            "manifest_sha256": row.manifest_sha256,
            "size": row.size,
        },
        now=when,
    )
    return Generated(row=row, built=built, data=data)


@dataclass(frozen=True)
class Reproduced:
    """Outcome of recomputing a reproducibility package's number."""

    ok: bool
    expected: float | None
    recomputed: float | None
    expected_status: str
    recomputed_status: str
    problems: list[str]


def reproduce(content: bytes, public_key: bytes | None = None) -> Reproduced:
    """Verify a reproducibility package, then rerun the evaluator on its own evidence."""
    check = verify_package(io.BytesIO(content), public_key=public_key)
    problems = list(check.problems)
    repro = check.report.get("reproduction") if check.ok else None
    if not isinstance(repro, dict):
        problems.append(
            "not a reproducibility package" if check.ok else "package failed verification"
        )
        return Reproduced(False, None, None, "", "", problems)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        metric = Metric.model_validate(json.loads(zf.read(repro["definition_file"])))
        batches = []
        for name in repro["batch_files"]:
            doc = json.loads(zf.read(name))
            if canonical_hash(doc["records"]) != doc["sha256"]:
                problems.append(f"{name}: records do not hash to {doc['sha256']}")
            batches.append(InputBatch(doc["sha256"], doc["records"]))
    as_of = datetime.fromisoformat(repro["as_of"]).date()
    results = evaluate(metric, batches, as_of)
    wanted = repro.get("dimensions") or {}
    match = next((m for m in results if dict(m.dimensions) == wanted), None)
    recomputed = match.value if match else None
    status = match.status.value if match else "missing"
    expected = repro.get("value")
    same = recomputed == expected or (
        recomputed is not None and expected is not None and abs(recomputed - expected) < 1e-9
    )
    if not same:
        problems.append(f"value {recomputed} does not match the reported {expected}")
    if status != repro.get("status"):
        problems.append(f"status {status} does not match the reported {repro.get('status')}")
    return Reproduced(
        not problems, expected, recomputed, str(repro.get("status")), status, problems
    )
