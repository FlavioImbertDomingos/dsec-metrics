"""Ed25519 keys for signing package manifests.

The private key is a PKCS#8 PEM file, normally a Docker secret. The fingerprint is the
SHA-256 of the raw 32-byte public key, in hex; it is printed in every report so an
auditor can compare it with the key they were given.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MAX_KEY_BYTES = 16 * 1024


class SigningKeyError(ValueError):
    """A key file is missing, unreadable or not an Ed25519 key."""


def fingerprint(public: Ed25519PublicKey) -> str:
    """SHA-256 of the raw public key bytes, in hex."""
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def public_pem(public: Ed25519PublicKey) -> str:
    """The public key as SubjectPublicKeyInfo PEM."""
    return public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


@dataclass(frozen=True)
class SigningKey:
    """A loaded private key and its public half."""

    private: Ed25519PrivateKey

    @property
    def public(self) -> Ed25519PublicKey:
        return self.private.public_key()

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public)

    def sign(self, data: bytes) -> bytes:
        """Detached Ed25519 signature (64 bytes)."""
        return self.private.sign(data)


def generate() -> tuple[bytes, bytes]:
    """A new key pair as (private PKCS#8 PEM, public PEM)."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return private_pem, public_pem(private.public_key()).encode("ascii")


def load_private(path: Path) -> SigningKey:
    """Read a PKCS#8 PEM Ed25519 private key."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SigningKeyError(f"cannot read signing key {path}: {exc.strerror}") from None
    if len(data) > MAX_KEY_BYTES:
        raise SigningKeyError("signing key file is too large")
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError):
        raise SigningKeyError("signing key is not a PEM private key without a passphrase") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("signing key is not an Ed25519 key")
    return SigningKey(key)


def load_public(data: bytes) -> Ed25519PublicKey:
    """Parse a PEM public key, or a 32-byte raw key."""
    if len(data) == 32:
        return Ed25519PublicKey.from_public_bytes(data)
    try:
        key = serialization.load_pem_public_key(data)
    except (ValueError, TypeError):
        raise SigningKeyError("not a PEM public key") from None
    if not isinstance(key, Ed25519PublicKey):
        raise SigningKeyError("public key is not an Ed25519 key")
    return key


def verify_signature(public: Ed25519PublicKey, signature: bytes, data: bytes) -> bool:
    """True when ``signature`` is a valid Ed25519 signature of ``data``."""
    try:
        public.verify(signature, data)
    except InvalidSignature:
        return False
    return True
