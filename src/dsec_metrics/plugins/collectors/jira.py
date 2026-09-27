"""``jira`` collector: issues from a JQL search, flattened into records."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import Field

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig


class JiraConfig(HttpCollectorConfig):
    """Site, account and token references, and the searches to run."""

    base_url: str = Field(pattern=r"^https://[^/]+$")
    email: str = Field(description="Secret reference to the account email")
    api_token: str = Field(description="Secret reference to an API token")
    searches: dict[str, str] = Field(
        min_length=1, description="query name -> JQL, for example the findings project"
    )
    fields: list[str] = Field(
        default_factory=lambda: ["summary", "status", "priority", "created", "duedate", "labels"]
    )
    dimension_fields: dict[str, str] = Field(
        default_factory=dict, description="dimension -> Jira field whose value fills it"
    )


def _flat(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("name", "value", "key", "displayName"):
            if key in value:
                return value[key]
        return None
    if isinstance(value, list):
        return [_flat(v) for v in value]
    return value


class JiraCollector(HttpCollector):
    """Read-only issue search."""

    name = "jira"
    version = "1.0.0"
    config_model = JiraConfig
    queries: ClassVar[dict[str, str]] = {"*": "One query per entry in the searches setting."}
    required_permissions: ClassVar[list[str]] = ["Browse projects on the searched projects"]

    config: JiraConfig

    @classmethod
    def queries_for(cls, config: dict[str, Any]) -> list[str]:
        searches = config.get("searches")
        return sorted(searches) if isinstance(searches, dict) else []

    def _headers(self) -> dict[str, str]:
        user = self.secrets.resolve(self.config.email).get_secret_value()
        token = self.secrets.resolve(self.config.api_token).get_secret_value()
        basic = base64.b64encode(f"{user}:{token}".encode()).decode("ascii")
        return {"Authorization": f"Basic {basic}"}

    def test_connection(self) -> ConnectionResult:
        try:
            me = self.http.get_json(
                f"{self.config.base_url}/rest/api/3/myself", headers=self._headers()
            )
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail=f"signed in as {me.get('accountType', 'account')}")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        jql = self.config.searches.get(query)
        if jql is None:
            raise CollectorError(f"jira has no search named {query!r}")
        records = []
        pages = self.pages_by_cursor(
            f"{self.config.base_url}/rest/api/3/search/jql",
            "issues",
            cursor_path="nextPageToken",
            cursor_param="nextPageToken",
            params={"jql": jql, "fields": ",".join(self.config.fields), "maxResults": 100},
            headers=self._headers(),
        )
        for page in pages:
            for issue in page:
                fields = issue.get("fields") or {}
                record = {"key": issue.get("key")}
                record.update({name: _flat(fields.get(name)) for name in self.config.fields})
                for dim, field in self.config.dimension_fields.items():
                    record[dim] = _flat(fields.get(field))
                created = record.get("created")
                if isinstance(created, str):
                    try:
                        record["age_days"] = (
                            as_of - datetime.fromisoformat(created[:10]).date()
                        ).days
                    except ValueError:
                        record["age_days"] = None
                records.append(record)
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )
