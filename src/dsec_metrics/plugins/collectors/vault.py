"""``vault`` collector: auth methods, audit devices and transit key versions from a
HashiCorp Vault (or OpenBao) server, with a read-only token."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import Field

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig, path_segment


class VaultConfig(HttpCollectorConfig):
    """Server address, namespace and a token reference."""

    address: str = Field(pattern=r"^https?://[^/]+$")
    token: str = Field(description="Secret reference to a token with the policy in the docs")
    namespace: str | None = None
    transit_mount: str = Field(default="transit", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dimensions: dict[str, str] = Field(default_factory=dict)


def _age_days(created: Any, as_of: date) -> int | None:
    if isinstance(created, str):
        try:
            return (as_of - datetime.fromisoformat(created.replace("Z", "+00:00")).date()).days
        except ValueError:
            return None
    if isinstance(created, (int, float)):
        return (as_of - datetime.fromtimestamp(created, tz=UTC).date()).days
    return None


class VaultCollector(HttpCollector):
    """Read-only Vault evidence for secrets and key management controls."""

    name = "vault"
    version = "1.0.0"
    config_model = VaultConfig
    queries: ClassVar[dict[str, str]] = {
        "auth_methods": "Enabled auth methods with type, local flag and token TTLs",
        "audit_devices": "Enabled audit devices; none means Vault is not writing an audit log",
        "transit_key_versions": "Transit keys with latest and minimum decryption version, and age",
    }
    required_permissions: ClassVar[list[str]] = [
        'path "sys/auth" { capabilities = ["read"] }',
        'path "sys/audit" { capabilities = ["read", "sudo"] }',
        'path "<transit>/keys" { capabilities = ["list"] }',
        'path "<transit>/keys/*" { capabilities = ["read"] }',
    ]

    config: VaultConfig

    def _headers(self) -> dict[str, str]:
        headers = {"X-Vault-Token": self.secrets.resolve(self.config.token).get_secret_value()}
        if self.config.namespace:
            headers["X-Vault-Namespace"] = self.config.namespace
        return headers

    def _get(self, path: str, **params: Any) -> Any:
        return self.http.get_json(
            f"{self.config.address}/v1/{path}", params=params or None, headers=self._headers()
        )

    def test_connection(self) -> ConnectionResult:
        try:
            health = self.http.get_json(
                f"{self.config.address}/v1/sys/health",
                params={"standbyok": "true", "perfstandbyok": "true"},
            )
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(
            ok=bool(health.get("initialized")), detail=f"version {health.get('version')}"
        )

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        records = [{**self.config.dimensions, **r} for r in getattr(self, f"_{query}")(as_of)]
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )

    def _mounts(self, path: str) -> dict[str, Any]:
        data = self._get(path)
        mounts = data.get("data", data)
        return {k: v for k, v in mounts.items() if isinstance(v, dict)}

    def _auth_methods(self, as_of: date) -> Iterator[dict[str, Any]]:
        del as_of
        for mount, info in sorted(self._mounts("sys/auth").items()):
            config = info.get("config") or {}
            yield {
                "mount": mount,
                "type": info.get("type"),
                "local": bool(info.get("local", False)),
                "default_lease_ttl": config.get("default_lease_ttl"),
                "max_lease_ttl": config.get("max_lease_ttl"),
            }

    def _audit_devices(self, as_of: date) -> Iterator[dict[str, Any]]:
        del as_of
        for mount, info in sorted(self._mounts("sys/audit").items()):
            options = info.get("options") or {}
            yield {
                "mount": mount,
                "type": info.get("type"),
                "local": bool(info.get("local", False)),
                "hmac_accessor": options.get("hmac_accessor", "true") != "false",
                "log_raw": options.get("log_raw", "false") == "true",
            }

    def _transit_key_versions(self, as_of: date) -> Iterator[dict[str, Any]]:
        mount = self.config.transit_mount
        listing = self._get(f"{mount}/keys", list="true")
        for name in sorted((listing.get("data") or {}).get("keys") or []):
            key = (self._get(f"{mount}/keys/{path_segment(name)}").get("data")) or {}
            versions = key.get("keys") or {}
            latest = key.get("latest_version") or (max(map(int, versions)) if versions else None)
            created = versions.get(str(latest)) if isinstance(versions, dict) else None
            if isinstance(created, dict):
                created = created.get("creation_time")
            yield {
                "key": name,
                "type": key.get("type"),
                "latest_version": latest,
                "min_decryption_version": key.get("min_decryption_version"),
                "auto_rotate_period": key.get("auto_rotate_period"),
                "exportable": bool(key.get("exportable", False)),
                "deletion_allowed": bool(key.get("deletion_allowed", False)),
                "latest_version_age_days": _age_days(created, as_of),
            }
