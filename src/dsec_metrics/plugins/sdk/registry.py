"""Plugin discovery through Python entry points."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import cast

from dsec_metrics.plugins.sdk.base import Collector
from dsec_metrics.plugins.sdk.secrets import SecretProvider, SecretResolver

COLLECTORS = "dsec_metrics.collectors"
NOTIFIERS = "dsec_metrics.notifiers"
RENDERERS = "dsec_metrics.renderers"
SECRET_PROVIDERS = "dsec_metrics.secret_providers"  # noqa: S105 (a group name)


class PluginError(LookupError):
    """A plugin is missing or does not implement the expected interface."""


def _entry_points(group: str) -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in entry_points(group=group)}


def plugin_names(group: str) -> list[str]:
    """Installed plugin names in a group."""
    return sorted(_entry_points(group))


def load(group: str, name: str, base: type) -> type:
    """Load one plugin class and check it subclasses ``base``."""
    ep = _entry_points(group).get(name)
    if ep is None:
        raise PluginError(f"no plugin named {name!r} in {group}")
    obj = ep.load()
    if not isinstance(obj, type) or not issubclass(obj, base):
        raise PluginError(f"plugin {name!r} in {group} is not a {base.__name__}")
    return obj


def collector_class(name: str) -> type[Collector]:
    """The collector plugin class registered under ``name``."""
    return cast(type[Collector], load(COLLECTORS, name, Collector))


def default_secret_resolver() -> SecretResolver:
    """A resolver with every installed secret provider."""
    providers: dict[str, SecretProvider] = {}
    for name in plugin_names(SECRET_PROVIDERS):
        cls = cast(type[SecretProvider], load(SECRET_PROVIDERS, name, SecretProvider))
        providers[cls.scheme] = cls()
    return SecretResolver(providers)
