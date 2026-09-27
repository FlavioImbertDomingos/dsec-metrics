"""Independent verification of an evidence package. Needs no database and no network.

Checks, in order: the archive is readable and has exactly one manifest and signature;
the signature is valid for the manifest bytes, with the pinned key when one is given;
every listed file is present with the listed size and SHA-256; and nothing unlisted is
in the archive. Every problem is reported, not just the first.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from dsec_metrics.reports.package import FORMAT, MANIFEST, RESERVED, SIGNATURE, safe_path
from dsec_metrics.reports.signing import SigningKeyError, fingerprint, load_public, verify_signature

MAX_TOTAL_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 64 * 1024**2


@dataclass
class VerifyResult:
    """Outcome. ``ok`` only when there are no problems."""

    problems: list[str] = field(default_factory=list)
    fingerprint: str | None = None
    pinned: bool = False
    files_checked: int = 0
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_package(
    source: Path | IO[bytes],
    public_key: bytes | None = None,
    expected_fingerprint: str | None = None,
) -> VerifyResult:
    """Verify a package. ``public_key`` (PEM or raw) or ``expected_fingerprint`` pins the
    signer; without either, the key embedded in the manifest is used and reported."""
    result = VerifyResult()
    try:
        zf = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        result.problems.append(f"not a readable ZIP archive: {exc}")
        return result
    with zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        duplicates = [n for n, c in Counter(names).items() if c > 1]
        for name in duplicates:
            result.problems.append(f"{name}: appears more than once in the archive")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            result.problems.append("archive expands to more than 2 GiB; refusing to read it")
            return result
        by_name = {i.filename: i for i in infos}
        for required in (MANIFEST, SIGNATURE):
            if required not in by_name:
                result.problems.append(f"{required}: missing")
        if result.problems:
            return result
        if by_name[MANIFEST].file_size > MAX_MANIFEST_BYTES:
            result.problems.append(f"{MANIFEST}: too large")
            return result
        manifest_bytes = zf.read(MANIFEST)
        signature = _signature(zf.read(SIGNATURE), result)
        manifest = _manifest(manifest_bytes, result)
        if manifest is None:
            return result
        result.report = manifest.get("report") or {}
        _check_signature(
            manifest, manifest_bytes, signature, public_key, expected_fingerprint, result
        )
        listed = _check_files(zf, by_name, manifest, result)
        for name in sorted(set(by_name) - listed - RESERVED):
            result.problems.append(f"{name}: in the archive but not in the manifest")
    return result


def _signature(raw: bytes, result: VerifyResult) -> bytes | None:
    try:
        signature = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        result.problems.append(f"{SIGNATURE}: not base64")
        return None
    if len(signature) != 64:
        result.problems.append(f"{SIGNATURE}: not a 64-byte Ed25519 signature")
        return None
    return signature


def _manifest(raw: bytes, result: VerifyResult) -> dict[str, Any] | None:
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        result.problems.append(f"{MANIFEST}: not valid JSON")
        return None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        result.problems.append(f"{MANIFEST}: unknown format")
        return None
    if not isinstance(manifest.get("files"), list):
        result.problems.append(f"{MANIFEST}: no file list")
        return None
    return manifest


def _check_signature(
    manifest: dict[str, Any],
    manifest_bytes: bytes,
    signature: bytes | None,
    public_key: bytes | None,
    expected_fingerprint: str | None,
    result: VerifyResult,
) -> None:
    signing = manifest.get("signing") or {}
    claimed = str(signing.get("public_key_fingerprint", ""))
    key: Ed25519PublicKey | None = None
    try:
        if public_key is not None:
            key = load_public(public_key)
            result.pinned = True
        else:
            key = load_public(base64.b64decode(str(signing.get("public_key", "")), validate=True))
    except (SigningKeyError, binascii.Error, ValueError):
        result.problems.append("signing key: cannot be read")
        return
    result.fingerprint = fingerprint(key)
    if claimed != result.fingerprint:
        result.problems.append(
            f"signing key: the manifest names key {claimed or 'none'}, "
            f"but the key used has fingerprint {result.fingerprint}"
        )
    if expected_fingerprint is not None:
        result.pinned = True
        if expected_fingerprint.lower() != result.fingerprint:
            result.problems.append(
                f"signing key: fingerprint {result.fingerprint} is not the expected "
                f"{expected_fingerprint.lower()}"
            )
    if signature is not None and not verify_signature(key, signature, manifest_bytes):
        result.problems.append(f"{SIGNATURE}: signature does not match {MANIFEST}")


def _check_files(
    zf: zipfile.ZipFile,
    by_name: dict[str, zipfile.ZipInfo],
    manifest: dict[str, Any],
    result: VerifyResult,
) -> set[str]:
    listed: set[str] = set()
    for entry in manifest["files"]:
        path = str(entry.get("path", "")) if isinstance(entry, dict) else ""
        if not safe_path(path) or path in RESERVED:
            result.problems.append(f"{path or '(no path)'}: unsafe or reserved path in manifest")
            continue
        if path in listed:
            result.problems.append(f"{path}: listed more than once")
            continue
        listed.add(path)
        info = by_name.get(path)
        if info is None:
            result.problems.append(f"{path}: listed in the manifest but missing")
            continue
        if info.file_size != entry.get("size"):
            result.problems.append(
                f"{path}: size {info.file_size}, manifest says {entry.get('size')}"
            )
            continue
        digest = hashlib.sha256()
        try:
            with zf.open(info) as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
        except (zipfile.BadZipFile, zlib.error, OSError):
            result.problems.append(f"{path}: corrupted in the archive")
            continue
        if digest.hexdigest() != entry.get("sha256"):
            result.problems.append(f"{path}: SHA-256 does not match the manifest")
            continue
        result.files_checked += 1
    return listed
