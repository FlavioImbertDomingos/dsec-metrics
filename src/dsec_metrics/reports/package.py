"""Evidence package: a ZIP of report files, a manifest of their hashes, and a detached
Ed25519 signature over the manifest.

Layout::

    report.pdf            (report.html when PDF rendering is unavailable)
    report.xlsx
    report.json
    evidence/...          record batches, definitions, register exports
    manifest.json         every file above with SHA-256, size, source and record
    manifest.sig          Ed25519 signature over the exact bytes of manifest.json

Entries are written in a fixed order with fixed timestamps, so rebuilding from the same
inputs gives byte-identical files.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dsec_metrics.__about__ import PRODUCT_NAME, __version__
from dsec_metrics.reports.signing import SigningKey

FORMAT = "dsec-metrics-package/1"
MANIFEST = "manifest.json"
SIGNATURE = "manifest.sig"
RESERVED = frozenset({MANIFEST, SIGNATURE})
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PackageFile:
    """One file in the package and where its contents came from."""

    path: str
    data: bytes
    media_type: str
    source: str
    collected_at: str | None = None
    record: Mapping[str, Any] = field(default_factory=dict)

    def entry(self) -> dict[str, Any]:
        """The manifest entry for this file."""
        return {
            "path": self.path,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size": len(self.data),
            "media_type": self.media_type,
            "source": self.source,
            "collected_at": self.collected_at,
            "record": dict(self.record),
        }


def safe_path(path: str) -> bool:
    """Relative, forward-slash paths with no empty, dot or dot-dot parts."""
    if not path or path.startswith("/") or "\\" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


@dataclass(frozen=True)
class BuiltPackage:
    """The ZIP bytes and what was signed."""

    content: bytes
    manifest: bytes
    manifest_sha256: str
    signature: bytes
    fingerprint: str


def build_manifest(
    files: Sequence[PackageFile], report: Mapping[str, Any], key: SigningKey
) -> bytes:
    """Serialize the manifest. Keys are sorted; the bytes are what gets signed."""
    names = [f.path for f in files]
    if len(set(names)) != len(names):
        raise ValueError("duplicate file path in package")
    for name in names:
        if not safe_path(name) or name in RESERVED:
            raise ValueError(f"invalid package path {name!r}")
    raw_public = key.public.public_bytes_raw()
    manifest = {
        "format": FORMAT,
        "generator": {"name": PRODUCT_NAME, "version": __version__},
        "report": dict(report),
        "signing": {
            "algorithm": "Ed25519",
            "public_key": base64.b64encode(raw_public).decode("ascii"),
            "public_key_fingerprint": key.fingerprint,
        },
        "files": [f.entry() for f in sorted(files, key=lambda f: f.path)],
    }
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def build_package(
    files: Sequence[PackageFile], report: Mapping[str, Any], key: SigningKey
) -> BuiltPackage:
    """Write the ZIP with its manifest and signature."""
    manifest = build_manifest(files, report, key)
    signature = key.sign(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for f in sorted(files, key=lambda f: f.path):
            _write(zf, f.path, f.data)
        _write(zf, MANIFEST, manifest)
        _write(zf, SIGNATURE, base64.b64encode(signature) + b"\n")
    return BuiltPackage(
        content=buffer.getvalue(),
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        signature=signature,
        fingerprint=key.fingerprint,
    )


def json_file(path: str, value: Any, source: str, **kwargs: Any) -> PackageFile:
    """A JSON file with stable formatting."""
    data = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=_default)
    return PackageFile(path, data.encode("utf-8") + b"\n", "application/json", source, **kwargs)


def _default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
