"""``file:///run/secrets/name``: a secret from a file, such as a Docker secret."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from dsec_metrics.plugins.sdk.secrets import SecretError, SecretProvider


class FileSecretProvider(SecretProvider):
    """Reads a whole file, stripping one trailing line ending. Absolute paths only."""

    scheme = "file"

    def resolve(self, reference: str) -> SecretStr:
        path = Path(reference if reference.startswith("/") else f"/{reference}")
        try:
            value = path.read_text(encoding="utf-8").removesuffix("\n").removesuffix("\r")
        except OSError as exc:
            raise SecretError(f"cannot read secret file {path}: {exc.strerror}") from None
        if not value:
            raise SecretError(f"secret file {path} is empty")
        return SecretStr(value)
