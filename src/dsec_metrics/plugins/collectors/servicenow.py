"""``servicenow`` collector: rows from the Table API with an encoded query."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig


class TableQuery(BaseModel):
    """One table read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    query: str = Field(default="", max_length=4000, description="sysparm_query")
    fields: list[str] = Field(min_length=1)
    dimension_fields: dict[str, str] = Field(default_factory=dict)


class ServiceNowConfig(HttpCollectorConfig):
    """Instance URL, account references and the table reads to run."""

    instance_url: str = Field(pattern=r"^https://[^/]+$")
    username: str = Field(description="Secret reference")
    password: str = Field(description="Secret reference")
    tables: dict[str, TableQuery] = Field(min_length=1)
    page_size: int = Field(default=500, ge=1, le=10_000)


class ServiceNowCollector(HttpCollector):
    """Read-only Table API reads."""

    name = "servicenow"
    version = "1.0.0"
    config_model = ServiceNowConfig
    queries: ClassVar[dict[str, str]] = {"*": "One query per entry in the tables setting."}
    required_permissions: ClassVar[list[str]] = [
        "Role with read ACLs on each configured table (for example snc_read_only plus table ACLs)",
        "Web service access on the account",
    ]

    config: ServiceNowConfig

    @classmethod
    def queries_for(cls, config: dict[str, Any]) -> list[str]:
        tables = config.get("tables")
        return sorted(tables) if isinstance(tables, dict) else []

    def _headers(self) -> dict[str, str]:
        user = self.secrets.resolve(self.config.username).get_secret_value()
        password = self.secrets.resolve(self.config.password).get_secret_value()
        basic = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        return {"Authorization": f"Basic {basic}"}

    def test_connection(self) -> ConnectionResult:
        name, spec = next(iter(self.config.tables.items()))
        try:
            self.http.get_json(
                f"{self.config.instance_url}/api/now/table/{spec.table}",
                params={"sysparm_limit": 1},
                headers=self._headers(),
            )
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail=f"read one row for {name}")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        del as_of
        spec = self.config.tables.get(query)
        if spec is None:
            raise CollectorError(f"servicenow has no table query named {query!r}")
        fields = sorted({*spec.fields, *spec.dimension_fields.values()})
        records = []
        pages = self.pages_by_offset(
            f"{self.config.instance_url}/api/now/table/{spec.table}",
            "result",
            offset_param="sysparm_offset",
            limit_param="sysparm_limit",
            page_size=self.config.page_size,
            params={
                "sysparm_query": spec.query,
                "sysparm_fields": ",".join(fields),
                "sysparm_display_value": "true",
                "sysparm_exclude_reference_link": "true",
            },
            headers=self._headers(),
        )
        for page in pages:
            for row in page:
                record = {name: row.get(name) for name in spec.fields}
                for dim, source in spec.dimension_fields.items():
                    record[dim] = row.get(source)
                records.append(record)
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )
