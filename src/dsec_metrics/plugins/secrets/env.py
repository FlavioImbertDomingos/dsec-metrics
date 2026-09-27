"""``env://NAME``: a secret from an environment variable."""

from __future__ import annotations

import os
import re

from pydantic import SecretStr

from dsec_metrics.plugins.sdk.secrets import SecretError, SecretProvider

_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


class EnvSecretProvider(SecretProvider):
    """Reads an environment variable. Intended for development and CI."""

    scheme = "env"

    def resolve(self, reference: str) -> SecretStr:
        if not _NAME.match(reference):
            raise SecretError("env:// references must be upper-case variable names")
        value = os.environ.get(reference)
        if not value:
            raise SecretError(f"environment variable {reference} is not set")
        return SecretStr(value)
