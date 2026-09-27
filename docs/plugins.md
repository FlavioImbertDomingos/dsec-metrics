# Plugin SDK

Collectors, notifiers, report renderers and secret providers are plugins, discovered through Python entry points. A team adds a data source by installing a package; the core does not change.

| Entry point group | Base class | Built in |
| --- | --- | --- |
| `dsec_metrics.collectors` | `dsec_metrics.plugins.sdk.base.Collector` | `file`, `sample` |
| `dsec_metrics.secret_providers` | `dsec_metrics.plugins.sdk.secrets.SecretProvider` | `env`, `file` |
| `dsec_metrics.notifiers` | from M6 | |
| `dsec_metrics.renderers` | from M3 | |

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

Timeouts, retries with backoff, pagination and rate-limit handling for HTTP sources arrive in the SDK with the `rest` collector in M4.

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
