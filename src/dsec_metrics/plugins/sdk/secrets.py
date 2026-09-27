"""Secret references (``scheme://...``) and their resolution through provider plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

from pydantic import SecretStr


class SecretError(RuntimeError):
    """A secret reference could not be resolved. Never includes the secret value."""


class SecretProvider(ABC):
    """Resolves references for one scheme, for example ``env`` or ``vault``."""

    scheme: ClassVar[str]

    @abstractmethod
    def resolve(self, reference: str) -> SecretStr:
        """Return the secret for the part of the reference after ``scheme://``."""


class SecretResolver:
    """Dispatches ``scheme://rest`` references to the provider for ``scheme``."""

    def __init__(self, providers: Mapping[str, SecretProvider]) -> None:
        self._providers = dict(providers)

    @property
    def schemes(self) -> list[str]:
        """Schemes this resolver can handle."""
        return sorted(self._providers)

    def resolve(self, reference: str) -> SecretStr:
        """Resolve a reference. Plain values are refused: config must hold references."""
        scheme, sep, rest = reference.partition("://")
        if not sep or not rest:
            raise SecretError("secret must be a reference like env://NAME, not a value")
        provider = self._providers.get(scheme)
        if provider is None:
            raise SecretError(f"no secret provider for scheme {scheme!r}")
        value = provider.resolve(rest)
        if any(ord(c) < 32 or ord(c) == 127 for c in value.get_secret_value()):
            raise SecretError(f"secret {scheme}://{rest} contains control characters")
        return value
