"""Plugin SDK: base classes, config models, the registry and test helpers.

A collector is a class that subclasses :class:`Collector` and is published under the
``dsec_metrics.collectors`` entry point group. See ``docs/plugins.md``.
"""

from dsec_metrics.plugins.sdk.base import (
    Collector,
    CollectorConfig,
    CollectorError,
    ConnectionResult,
    RecordBatch,
)
from dsec_metrics.plugins.sdk.secrets import SecretError, SecretProvider, SecretResolver

__all__ = [
    "Collector",
    "CollectorConfig",
    "CollectorError",
    "ConnectionResult",
    "RecordBatch",
    "SecretError",
    "SecretProvider",
    "SecretResolver",
]
