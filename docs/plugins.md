# Plugin SDK

Collectors, notifiers, report renderers and secret providers are plugins, discovered through Python entry points. A team adds a data source by installing a package; the core does not change.

| Entry point group | Base class | Built in |
| --- | --- | --- |
| `dsec_metrics.collectors` | `dsec_metrics.plugins.sdk.base.Collector` | `file`, `sample`, `rest`, `aws`, `vault`, `jira`, `servicenow`, `github` |
| `dsec_metrics.secret_providers` | `dsec_metrics.plugins.sdk.secrets.SecretProvider` | `env`, `file` |
| `dsec_metrics.notifiers` | from M6 | |
| `dsec_metrics.renderers` | `dsec_metrics.plugins.sdk.renderer.Renderer` | `pdf`, `html`, `xlsx`, `csv`, `json` (evidence packages use this fixed set, loaded by name) |

## Writing a collector

```python
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from dsec_metrics.plugins.sdk.base import (
    Collector,
    CollectorConfig,
    CollectorError,
    ConnectionResult,
    RecordBatch,
)


class InventoryConfig(CollectorConfig):
    base_url: str
    token: str  # a reference such as env://INVENTORY_TOKEN, never the token itself


class InventoryCollector(Collector):
    name = "inventory"
    version = "0.1.0"
    config_model = InventoryConfig
    queries: ClassVar[dict[str, str]] = {"assets": "Every asset with its owner and tier."}
    required_permissions: ClassVar[list[str]] = ["assets:read"]
    sensitive_fields: ClassVar[tuple[str, ...]] = ("owner_phone",)

    config: InventoryConfig

    def test_connection(self) -> ConnectionResult: ...

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        token = self.secrets.resolve(self.config.token)
        ...
        yield RecordBatch(query=query, params=params, records=rows, collected_at=datetime.now(UTC))
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."dsec_metrics.collectors"]
inventory = "my_package.collector:InventoryCollector"
```

Then reference it from a collector instance in `content/collectors/` and run `dsec-metrics validate`.

### Rules

- Read-only access only. List the exact permissions in `required_permissions` and in your README. A collector never writes to its source.
- Secrets arrive as references and are resolved through `self.secrets`. A plain value where a reference is expected is refused.
- Yield records as plain JSON data: strings, numbers, booleans, null, lists and objects. Use the dimension names `business_unit`, `application`, `environment` and `region` where they apply, so metrics can group by them.
- List every field that can hold personal or authentication data in `sensitive_fields`. The platform drops those fields and masks card numbers before anything is stored ([ADR-0008](adr/0008-redaction-pipeline.md)). Redaction is not your plugin's job, and it cannot be skipped.
- Raise `CollectorError` with a message that is safe to log. Never include secrets or record contents in it.
- Contract tests run against recorded fixtures. CI never calls live services.

### Test helpers

`dsec_metrics.plugins.sdk.testing` has two helpers for contract tests:

- `check_collector_class(cls)` checks that the class declares its name, version, config model, described queries and permissions.
- `collect_all(collector, query, as_of, **params)` runs a query and checks every batch is labelled with the query and is JSON-serializable.

- `FixtureTransport(routes)` replays recorded HTTP responses (see below), and `fixture_policy(*hosts)` is an outbound policy that allows those hosts without touching DNS.

## Starting a new collector

```sh
dsec-metrics plugin new collector asset_inventory --directory ~/src
cd ~/src/dsec-metrics-asset-inventory
pip install -e .
pytest
```

The scaffold writes a package that works as it is: `pyproject.toml` with the entry point, a config model, an HTTP collector with one paginated query, two recorded fixture pages, a contract test, and ruff and mypy settings. Installing it is all the platform needs; `dsec-metrics plugin list` shows it, and a collector instance in `content/collectors/` can use it. Replace the sample query with yours, record fixtures from a test account, and remove anything real from them before committing.

## HTTP collectors

Subclass `HttpCollector` and `HttpCollectorConfig` from `dsec_metrics.plugins.sdk.http` for any HTTP source. The base class gives you `self.http`, a client that:

- sends GET only, and POST only for the read actions listed in the class's `read_only_posts` (for APIs such as AWS's that use POST for reads);
- checks every URL against the operator's outbound policy before connecting, and connects to the checked address ([Collectors](collectors/index.md#outbound-calls), [ADR-0013](adr/0013-outbound-http-and-ssrf.md));
- applies timeouts, retries with backoff and jitter on connection errors, 429, gateway errors and exhausted rate limits, honours `Retry-After`, refuses redirects, and limits response size;
- raises `CollectorError` with the host and path only, never the query string or headers.

Pagination helpers on the base class follow `Link: rel="next"` headers (`pages_by_link`), offset and limit parameters (`pages_by_offset`) and cursors (`pages_by_cursor`). Each yields one list of records per page and enforces the instance's `max_pages` and `max_records`. `dig(data, "a.b")` follows a dotted path into parsed JSON.

`HttpCollectorConfig` adds `timeout_seconds`, `max_pages`, `max_records` and `sensitive_fields` to your config model, so operators can set them on any HTTP collector.

If your collector's queries come from its configuration (like `rest`, whose queries are named in YAML), declare `queries = {"*": "..."}` and override the `queries_for(config)` class method to return the names, so `dsec-metrics validate` can check references to them.

### Contract tests

CI never calls live services. Record responses once from a test account, save them under `tests/fixtures/`, and replay them:

```python
from dsec_metrics.plugins.sdk.testing import FixtureTransport, collect_all, fixture_policy

transport = FixtureTransport(
    {
        "GET /items?per_page=100": (
            FIXTURES / "page-1.json",
            {"link": '<https://api.example.test/items?page=2>; rel="next"'},
        ),
        "GET /items?page=2": FIXTURES / "page-2.json",
        "POST / Service.ListThings": lambda request: {...},  # a read action; answer by request
    }
)
collector.use_transport(transport, fixture_policy("api.example.test"))
batches = collect_all(collector, "items", date(2026, 9, 30))
assert {r.method for r in transport.requests} == {"GET"}
```

Keys are `"METHOD /path?query"` with query order ignored, plus the action for declared POST reads. A value is a fixture path, bytes, JSON data, `(body, headers)`, `(status, body, headers)`, or a function of the request. A request with no recorded response fails the test.

### Review checklist

Before publishing a collector, check that:

- it sends no write requests, and `required_permissions` and the README list read-only scopes only;
- every credential is a secret reference, and no message or record contains a secret;
- fields that can hold personal or authentication data are in `sensitive_fields`;
- records use the dimension names `business_unit`, `application`, `environment` and `region` where they apply;
- fixtures are synthetic or scrubbed: no real hostnames, names, keys or card data;
- contract tests cover every query, including paging and an error response.

## Writing a secret provider

```python
from pydantic import SecretStr
from dsec_metrics.plugins.sdk.secrets import SecretError, SecretProvider


class VaultKvProvider(SecretProvider):
    scheme = "vault"

    def resolve(self, reference: str) -> SecretStr: ...  # reference is everything after "vault://"
```

Raise `SecretError` when a reference cannot be resolved, and never put the value in the message.

## Built-in plugins

`file` reads CSV and JSON files under one `base_dir`, one file per query, set in `config.files`. Paths must be relative and stay inside `base_dir` after symlinks are resolved. CSV cells that look like numbers become numbers and empty cells become null. Files over 50 MB are refused. Required permission: read access to `base_dir`.

`sample` generates deterministic synthetic data for 12 months, three business units and 40 controls from a seed. It needs no credentials and makes no network calls. Its data includes well-known test card numbers so the redaction path is exercised on every demo run.

`env://NAME` reads an upper-case environment variable. `file:///absolute/path` reads a file, such as a Docker secret under `/run/secrets`.
