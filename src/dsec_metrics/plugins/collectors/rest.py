"""``rest`` collector: any JSON API, described in configuration.

Each query names a path under ``base_url``, fixed parameters, where the records are in
the response, and how pages work. Authentication is a header whose value comes from a
secret reference. Everything goes through the outbound policy and the read-only client.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig, dig


class RestQuery(BaseModel):
    """One endpoint and how to read it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(pattern=r"^/[A-Za-z0-9/_.~%-]*$")
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    records_path: str = Field(default="", pattern=r"^[A-Za-z0-9_.-]*$")
    pagination: Literal["none", "link", "offset", "cursor"] = "none"
    page_size: int = Field(default=100, ge=1, le=10_000)
    offset_param: str = "offset"
    limit_param: str = "limit"
    total_path: str | None = None
    cursor_path: str = "next"
    cursor_param: str = "cursor"
    fields: list[str] = Field(default_factory=list, description="keep only these (dotted paths)")

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("path must not contain . or .. segments")
        return value

    @property
    def query_params(self) -> dict[str, str | int]:
        """Parameters as sent: booleans as ``true`` and ``false``."""
        return {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in self.params.items()}


class RestAuth(BaseModel):
    """A header carrying a secret, such as ``Authorization: Bearer <token>``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: str = Field(default="Authorization", pattern=r"^[A-Za-z0-9-]{1,64}$")
    scheme: str = Field(default="Bearer", max_length=32)
    secret: str = Field(description="Secret reference")


class RestConfig(HttpCollectorConfig):
    """Base URL, optional authentication, queries, and dimensions added to every record."""

    base_url: str
    auth: RestAuth | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    queries: dict[str, RestQuery] = Field(min_length=1)
    dimensions: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _base(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")) or "?" in value or "#" in value:
            raise ValueError("base_url must be an http(s) URL without query or fragment")
        return value.rstrip("/")

    @field_validator("headers")
    @classmethod
    def _no_secret_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if name.lower() in {"authorization", "cookie", "x-api-key", "proxy-authorization"}:
                raise ValueError(
                    f"header {name} carries credentials; use auth with a secret reference"
                )
        return value


class RestCollector(HttpCollector):
    """Config-driven, read-only JSON API reader."""

    name = "rest"
    version = "1.0.0"
    config_model = RestConfig
    queries: ClassVar[dict[str, str]] = {"*": "One query per entry in the queries setting."}
    required_permissions: ClassVar[list[str]] = ["Read-only access to the configured endpoints"]

    config: RestConfig

    @classmethod
    def queries_for(cls, config: dict[str, Any]) -> list[str]:
        queries = config.get("queries")
        return sorted(queries) if isinstance(queries, dict) else []

    def _headers(self) -> dict[str, str]:
        headers = dict(self.config.headers)
        if self.config.auth is not None:
            value = self.secrets.resolve(self.config.auth.secret).get_secret_value()
            scheme = self.config.auth.scheme
            headers[self.config.auth.header] = f"{scheme} {value}" if scheme else value
        return headers

    def test_connection(self) -> ConnectionResult:
        name = next(iter(self.config.queries))
        try:
            list(self._pages(self.config.queries[name]))[:1]
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail=f"query {name} readable")

    def _pages(self, q: RestQuery) -> Iterator[list[dict[str, Any]]]:
        url = self.config.base_url + q.path
        headers = self._headers()
        if q.pagination == "link":
            yield from self.pages_by_link(
                url, q.records_path, params=q.query_params, headers=headers
            )
        elif q.pagination == "offset":
            yield from self.pages_by_offset(
                url,
                q.records_path,
                offset_param=q.offset_param,
                limit_param=q.limit_param,
                page_size=q.page_size,
                params=q.query_params,
                total_path=q.total_path,
                headers=headers,
            )
        elif q.pagination == "cursor":
            yield from self.pages_by_cursor(
                url,
                q.records_path,
                cursor_path=q.cursor_path,
                cursor_param=q.cursor_param,
                params=q.query_params,
                headers=headers,
            )
        else:
            data = self.http.get_json(url, params=q.query_params or None, headers=headers)
            value = dig(data, q.records_path)
            if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
                raise CollectorError("rest: records_path does not point at a list of objects")
            yield value

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        del as_of
        spec = self.config.queries.get(query)
        if spec is None:
            raise CollectorError(f"rest has no query named {query!r}")
        records = []
        for page in self._pages(spec):
            for item in page:
                record = {f: dig(item, f) for f in spec.fields} if spec.fields else dict(item)
                records.append({**self.config.dimensions, **record})
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )
