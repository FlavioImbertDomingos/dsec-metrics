from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest

from dsec_metrics.reports.package import (
    MANIFEST,
    SIGNATURE,
    PackageFile,
    build_package,
    json_file,
    safe_path,
)
from dsec_metrics.reports.signing import (
    SigningKey,
    SigningKeyError,
    generate,
    load_private,
    load_public,
    public_pem,
)
from dsec_metrics.reports.verify import verify_package


@pytest.fixture(scope="module")
def key() -> SigningKey:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return SigningKey(Ed25519PrivateKey.generate())


def files() -> list[PackageFile]:
    return [
        PackageFile("report.html", b"<h1>Report</h1>", "text/html", "renderer:html"),
        json_file(
            "evidence/batches/abc.json",
            {"records": [{"a": 1}]},
            "sample/secrets_inventory",
            collected_at="2026-09-30T02:05:00+00:00",
            record={"batch_sha256": "abc"},
        ),
    ]


REPORT = {
    "type": "control",
    "title": "Test",
    "period": {"start": "2026-07-01", "end": "2026-09-30"},
}


def rezip(
    content: bytes, change: dict[str, bytes | None], add: dict[str, bytes] | None = None
) -> bytes:
    """Copy a package, replacing (or dropping, with None) some entries."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            if info.filename in change:
                data = change[info.filename]
                if data is not None:
                    dst.writestr(info.filename, data)
            else:
                dst.writestr(info, src.read(info))
        for name, data in (add or {}).items():
            dst.writestr(name, data)
    return out.getvalue()


def check(content: bytes, **kwargs: object) -> list[str]:
    return verify_package(io.BytesIO(content), **kwargs).problems  # type: ignore[arg-type]


def test_a_built_package_verifies_and_is_reproducible(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    result = verify_package(io.BytesIO(built.content))
    assert result.ok, result.problems
    assert result.files_checked == 2
    assert result.fingerprint == key.fingerprint
    assert result.pinned is False
    assert result.report["title"] == "Test"
    again = build_package(files(), REPORT, key)
    assert again.content == built.content
    manifest = json.loads(built.manifest)
    assert [f["path"] for f in manifest["files"]] == ["evidence/batches/abc.json", "report.html"]
    assert manifest["files"][0]["record"] == {"batch_sha256": "abc"}


def test_pinning_by_key_and_fingerprint(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    pem = public_pem(key.public).encode()
    assert verify_package(io.BytesIO(built.content), public_key=pem).pinned
    assert check(built.content, public_key=pem) == []
    assert check(built.content, expected_fingerprint=key.fingerprint.upper()) == []
    other_private, other_public = generate()
    problems = check(built.content, public_key=other_public)
    assert any("signature does not match" in p for p in problems)
    assert any("manifest names key" in p for p in problems)
    assert any("not the expected" in p for p in check(built.content, expected_fingerprint="0" * 64))
    assert other_private.startswith(b"-----BEGIN PRIVATE KEY-----")


def test_changing_one_byte_of_a_file_fails(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    changed = rezip(built.content, {"report.html": b"<h1>Report</h2>"})
    assert check(changed) == ["report.html: SHA-256 does not match the manifest"]


def test_changing_one_byte_of_the_archive_fails(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    raw = bytearray(built.content)
    # Flip a byte inside the first entry's compressed data (after its 30-byte header
    # and file name).
    with zipfile.ZipFile(io.BytesIO(built.content)) as zf:
        first = zf.infolist()[0]
    offset = first.header_offset + 30 + len(first.filename.encode()) + 2
    raw[offset] ^= 0x01
    problems = check(bytes(raw))
    assert problems
    assert any(first.filename in p for p in problems)


def test_changing_the_manifest_breaks_the_signature(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    manifest = json.loads(built.manifest)
    manifest["report"]["title"] = "Other"
    changed = rezip(built.content, {MANIFEST: json.dumps(manifest).encode()})
    assert check(changed) == [f"{SIGNATURE}: signature does not match {MANIFEST}"]


def test_changing_the_signature_fails(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    sig = bytearray(built.signature)
    sig[0] ^= 0xFF
    changed = rezip(built.content, {SIGNATURE: base64.b64encode(bytes(sig))})
    assert check(changed) == [f"{SIGNATURE}: signature does not match {MANIFEST}"]
    assert f"{SIGNATURE}: not base64" in check(rezip(built.content, {SIGNATURE: b"!!"}))
    short = base64.b64encode(b"x" * 10)
    assert f"{SIGNATURE}: not a 64-byte Ed25519 signature" in check(
        rezip(built.content, {SIGNATURE: short})
    )


def test_missing_extra_and_duplicate_files_fail(key: SigningKey) -> None:
    built = build_package(files(), REPORT, key)
    assert check(rezip(built.content, {"report.html": None})) == [
        "report.html: listed in the manifest but missing"
    ]
    assert check(rezip(built.content, {}, add={"evidence/extra.txt": b"x"})) == [
        "evidence/extra.txt: in the archive but not in the manifest"
    ]
    with pytest.warns(UserWarning, match="Duplicate name"):
        dup = rezip(built.content, {}, add={"report.html": b"<h1>Report</h1>"})
    assert any("more than once" in p for p in check(dup))
    assert check(rezip(built.content, {MANIFEST: None})) == [f"{MANIFEST}: missing"]


def test_malformed_inputs(key: SigningKey) -> None:
    assert check(b"not a zip")[0].startswith("not a readable ZIP archive")
    built = build_package(files(), REPORT, key)
    assert check(rezip(built.content, {MANIFEST: b"{"})) == [f"{MANIFEST}: not valid JSON"]
    assert check(rezip(built.content, {MANIFEST: b'{"format": "x"}'})) == [
        f"{MANIFEST}: unknown format"
    ]
    bad_path = json.loads(built.manifest)
    bad_path["files"].append({"path": "../escape", "sha256": "x", "size": 1})
    problems = check(rezip(built.content, {MANIFEST: json.dumps(bad_path).encode()}))
    assert "../escape: unsafe or reserved path in manifest" in problems


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("report.pdf", True),
        ("evidence/a/b.json", True),
        ("", False),
        ("/abs", False),
        ("a/../b", False),
        ("a//b", False),
        ("a\\b", False),
        ("./a", False),
    ],
)
def test_safe_paths(path: str, ok: bool) -> None:
    assert safe_path(path) is ok


def test_builder_rejects_bad_paths(key: SigningKey) -> None:
    with pytest.raises(ValueError, match="invalid package path"):
        build_package([PackageFile("../x", b"", "text/plain", "t")], REPORT, key)
    with pytest.raises(ValueError, match="duplicate"):
        build_package(files() + files()[:1], REPORT, key)
    with pytest.raises(ValueError, match="invalid package path"):
        build_package([PackageFile(MANIFEST, b"", "text/plain", "t")], REPORT, key)


def test_key_files(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    private, public = generate()
    (root / "k.pem").write_bytes(private)
    loaded = load_private(root / "k.pem")
    assert public_pem(loaded.public).encode() == public
    assert load_public(public)
    with pytest.raises(SigningKeyError):
        load_private(root / "missing.pem")
    (root / "bad.pem").write_bytes(b"nope")
    with pytest.raises(SigningKeyError):
        load_private(root / "bad.pem")
    with pytest.raises(SigningKeyError):
        load_public(b"nope")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

    ec = generate_private_key(SECP256R1())
    (root / "ec.pem").write_bytes(
        ec.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(SigningKeyError, match="not an Ed25519"):
        load_private(root / "ec.pem")
    ec_pub = ec.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with pytest.raises(SigningKeyError, match="not an Ed25519"):
        load_public(ec_pub)
    assert len(load_public(loaded.public.public_bytes_raw()).public_bytes_raw()) == 32
