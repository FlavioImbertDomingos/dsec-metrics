"""Collector base classes, as specified in the brief."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dsec_metrics.plugins.sdk.secrets import SecretResolver


class CollectorError(RuntimeError):
    """A collector could not complete. The message is safe to log."""


class CollectorConfig(BaseModel):
    """Plugin-specific settings. Secrets are references, never values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordBatch(BaseModel):
    """Raw records from one query, before redaction."""

    model_config = ConfigDict(frozen=True)

    query: str
    params: dict[str, Any] = Field(default_factory=dict)
    records: list[dict[str, Any]]
    collected_at: datetime


class ConnectionResult(BaseModel):
    """Outcome of ``test_connection``. ``detail`` must not contain secrets."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    detail: str = ""


class Collector(ABC):
    """Base class for every collector.

    Rules every collector follows: read-only credentials only; secrets come from a
    :class:`SecretResolver`; output goes through the redaction pipeline before storage
    (the platform does this, not the plugin); contract tests run against fixtures.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    config_model: ClassVar[type[CollectorConfig]]
    queries: ClassVar[dict[str, str]]  # query name -> description
    required_permissions: ClassVar[list[str]]  # documented read-only scopes
    sensitive_fields: ClassVar[tuple[str, ...]] = ()  # dropped by redaction

    def __init__(self, config: CollectorConfig, secrets: SecretResolver) -> None:
        if not isinstance(config, self.config_model):
            raise TypeError(f"{self.name} expects {self.config_model.__name__}")
        self.config = config
        self.secrets = secrets

    @classmethod
    def from_mapping(cls, config: dict[str, Any], secrets: SecretResolver) -> Collector:
        """Validate a raw config mapping and build the collector."""
        return cls(cls.config_model.model_validate(config), secrets)

    @classmethod
    def queries_for(cls, config: dict[str, Any]) -> list[str]:
        """Query names an instance with this raw config offers. Collectors whose queries
        come from their config (``queries = {"*": ...}``) override this."""
        del config
        return sorted(cls.queries)

    @abstractmethod
    def test_connection(self) -> ConnectionResult:
        """Check that the source is reachable with the configured, read-only access."""

    @abstractmethod
    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        """Yield record batches for ``query`` as of ``as_of``."""

    def _check_query(self, query: str) -> None:
        if query not in self.queries:
            raise CollectorError(f"{self.name} has no query named {query!r}")
