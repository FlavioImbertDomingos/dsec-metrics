"""``file`` collector: records from CSV or JSON files under one base directory.

Each query maps to one file. JSON files hold a list of objects (or ``{"records": [...]}``);
CSV files have a header row. CSV values are strings except empty cells, which become
``null``, and cells that parse as integers or decimals, which become numbers.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, field_validator

from dsec_metrics.plugins.sdk.base import (
    Collector,
    CollectorConfig,
    CollectorError,
    ConnectionResult,
    RecordBatch,
)

MAX_FILE_BYTES = 50 * 1024 * 1024


class FileConfig(CollectorConfig):
    """Base directory and one file per query."""

    base_dir: Path
    files: dict[str, str] = Field(min_length=1, description="query name -> relative path")
    sensitive_fields: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def _relative(cls, value: dict[str, str]) -> dict[str, str]:
        for name, rel in value.items():
            p = Path(rel)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"file for query {name!r} must be relative to base_dir")
            if p.suffix.lower() not in (".csv", ".json"):
                raise ValueError(f"file for query {name!r} must be .csv or .json")
        return value


def _cell(value: str) -> Any:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        number = float(value)
    except ValueError:
        return value
    return number if number == number and abs(number) != float("inf") else value


class FileCollector(Collector):
    """Reads local CSV and JSON files. Read-only; never writes to the base directory."""

    name = "file"
    version = "1.0.0"
    config_model = FileConfig
    queries: ClassVar[dict[str, str]] = {"*": "One query per entry in the files setting."}
    required_permissions: ClassVar[list[str]] = ["read access to the configured base_dir"]

    config: FileConfig

    @classmethod
    def queries_for(cls, config: dict[str, Any]) -> list[str]:
        files = config.get("files")
        return sorted(files) if isinstance(files, dict) else []

    @property
    def query_names(self) -> list[str]:
        """Queries this instance offers (the keys of ``files``)."""
        return sorted(self.config.files)

    def _path(self, query: str) -> Path:
        rel = self.config.files.get(query)
        if rel is None:
            raise CollectorError(f"file collector has no query named {query!r}")
        base = self.config.base_dir.resolve()
        path = (base / rel).resolve()
        if not path.is_relative_to(base):
            raise CollectorError("file path escapes base_dir")
        return path

    def test_connection(self) -> ConnectionResult:
        missing = [q for q in self.query_names if not self._path(q).is_file()]
        if missing:
            return ConnectionResult(ok=False, detail=f"missing files for: {', '.join(missing)}")
        return ConnectionResult(ok=True, detail=f"{len(self.query_names)} files readable")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        path = self._path(query)
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise CollectorError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CollectorError(f"cannot read {path.name}: {exc.strerror}") from None
        if path.suffix.lower() == ".csv":
            records: list[dict[str, Any]] = [
                {k: _cell(v or "") for k, v in row.items() if k is not None}
                for row in csv.DictReader(text.splitlines())
            ]
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CollectorError(f"{path.name} is not valid JSON: {exc.msg}") from None
            if isinstance(data, dict) and isinstance(data.get("records"), list):
                data = data["records"]
            if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
                raise CollectorError(f"{path.name} must hold a list of objects")
            records = data
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )
