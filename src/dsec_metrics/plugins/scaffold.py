"""``dsec-metrics plugin new collector NAME``: a ready-to-install collector package.

The package has an entry point in ``dsec_metrics.collectors``, a config model, an HTTP
collector with one paginated query, recorded fixtures and a contract test that replays
them. Installing the package is all it takes for the platform to find the collector.
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

PYPROJECT = Template("""[project]
name = "dsec-metrics-$dist"
version = "0.1.0"
description = "dsec-metrics collector for $title"
readme = "README.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["dsec-metrics"]

[project.entry-points."dsec_metrics.collectors"]
$name = "$package.collector:$cls"

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/$package"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["B", "E", "F", "I", "S", "UP"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105"]

[tool.ruff.lint.isort]
known-first-party = ["$package"]

[tool.mypy]
strict = true
""")

README = Template("""# dsec-metrics-$dist

A read-only dsec-metrics collector for $title.

## Minimum permissions

List the exact read-only scopes here and in `required_permissions`. The collector never
writes to its source.

## Configuration

A collector instance in `content/collectors/`:

```yaml
id: $name
plugin: $name
config:
  base_url: https://api.example.test
  token: env://${env}_TOKEN
schedule: "0 3 * * *"
```

Add the API host to `DSEC_COLLECTOR_ALLOWED_HOSTS`; every other host is refused.

## Development

```sh
pip install -e .
pytest
```

Tests replay recorded responses from `tests/fixtures/`; they never call the live API.
Record new fixtures from a test account, and remove anything real before committing.
""")

COLLECTOR = Template('''"""$title collector for dsec-metrics. Read-only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig
from pydantic import Field


class ${cls}Config(HttpCollectorConfig):
    """Where the API is and which secret holds the token."""

    base_url: str = Field(pattern=r"^https://[^/]+$$")
    token: str = Field(description="Secret reference, for example env://${env}_TOKEN")
    dimensions: dict[str, str] = Field(default_factory=dict)


class $cls(HttpCollector):
    """Reads items from $title."""

    name = "$name"
    version = "0.1.0"
    config_model = ${cls}Config
    queries: ClassVar[dict[str, str]] = {"items": "Every item, one record each"}
    required_permissions: ClassVar[list[str]] = ["items:read"]
    # Fields that may hold personal or authentication data; redaction drops them.
    sensitive_fields: ClassVar[tuple[str, ...]] = ("owner_email",)

    config: ${cls}Config

    def _headers(self) -> dict[str, str]:
        token = self.secrets.resolve(self.config.token).get_secret_value()
        return {"Authorization": f"Bearer {token}"}

    def test_connection(self) -> ConnectionResult:
        url = f"{self.config.base_url}/items"
        try:
            self.http.get_json(url, params={"per_page": 1}, headers=self._headers())
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail="items readable")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        records = []
        pages = self.pages_by_link(
            f"{self.config.base_url}/items",
            "items",
            params={"per_page": 100},
            headers=self._headers(),
        )
        for page in pages:
            for item in page:
                records.append({**self.config.dimensions, **item})
        now = datetime.now(UTC)
        yield RecordBatch(query=query, params=params, records=records, collected_at=now)
''')

FIXTURE_1 = """{
  "items": [
    {"id": 1, "name": "first", "status": "open", "owner_email": "someone@example.test"},
    {"id": 2, "name": "second", "status": "closed", "owner_email": "someone@example.test"}
  ]
}
"""

FIXTURE_2 = """{
  "items": [
    {"id": 3, "name": "third", "status": "open", "owner_email": "someone@example.test"}
  ]
}
"""

TEST = Template('''"""Contract test: replay recorded responses, check the records and the rules."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from dsec_metrics.core.redaction import redact_records
from dsec_metrics.plugins.sdk.registry import collector_class, default_secret_resolver
from dsec_metrics.plugins.sdk.testing import (
    FixtureTransport,
    check_collector_class,
    collect_all,
    fixture_policy,
)

from $package.collector import $cls

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.example.test"


def make(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[$cls, FixtureTransport]:
    monkeypatch.setenv("${env}_TOKEN", "test-token")
    config = {"base_url": BASE, "token": "env://${env}_TOKEN"}
    collector = $cls.from_mapping(
        config, default_secret_resolver()
    )
    assert isinstance(collector, $cls)
    next_page = {"link": f'<{BASE}/items?page=2>; rel="next"'}
    transport = FixtureTransport(
        {
            "GET /items?per_page=100": (FIXTURES / "items-page-1.json", next_page),
            "GET /items?page=2": FIXTURES / "items-page-2.json",
        }
    )
    collector.use_transport(transport, fixture_policy("api.example.test"))
    return collector, transport


def test_declares_what_the_platform_needs() -> None:
    check_collector_class($cls)
    assert collector_class("$name") is $cls


def test_reads_every_page_with_get_only(monkeypatch: pytest.MonkeyPatch) -> None:
    collector, transport = make(monkeypatch)
    batches = collect_all(collector, "items", date(2026, 9, 30))
    records = [r for b in batches for r in b.records]
    assert [r["id"] for r in records] == [1, 2, 3]
    assert {r.method for r in transport.requests} == {"GET"}
    cleaned, summary = redact_records(records, $cls.sensitive_fields)
    assert all("owner_email" not in r for r in cleaned)
    assert summary.fields_dropped == {"owner_email": 3}
''')


class ScaffoldError(ValueError):
    """The name is invalid or the target already exists."""


def new_collector(name: str, directory: Path) -> Path:
    """Write the package and return its root."""
    if not NAME.match(name):
        raise ScaffoldError(
            "name must start with a letter and use lower case letters, digits and "
            "underscores, 2 to 31 characters"
        )
    dist = name.replace("_", "-")
    package = f"dsec_metrics_{name}"
    cls = "".join(part.capitalize() for part in name.split("_")) + "Collector"
    title = name.replace("_", " ").title()
    values = {
        "name": name,
        "dist": dist,
        "package": package,
        "cls": cls,
        "title": title,
        "env": name.upper(),
    }
    root = directory / f"dsec-metrics-{dist}"
    if root.exists():
        raise ScaffoldError(f"{root} already exists")
    files: dict[str, str] = {
        "pyproject.toml": PYPROJECT.substitute(values),
        "README.md": README.substitute(values),
        f"src/{package}/__init__.py": f'"""{title} collector for dsec-metrics."""\n',
        f"src/{package}/py.typed": "",
        f"src/{package}/collector.py": COLLECTOR.substitute(values),
        "tests/__init__.py": "",
        "tests/fixtures/items-page-1.json": FIXTURE_1,
        "tests/fixtures/items-page-2.json": FIXTURE_2,
        "tests/test_collector.py": TEST.substitute(values),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root
