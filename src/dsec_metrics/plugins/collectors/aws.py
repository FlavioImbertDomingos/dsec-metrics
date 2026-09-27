"""``aws`` collector: KMS key rotation, ACM certificate expiry, AWS Config rule compliance
and IAM access key age, for one account and region.

Requests are signed with SigV4 (:mod:`dsec_metrics.plugins.sdk.aws_sigv4`). KMS, ACM and
Config are JSON APIs that use POST for reads; only the read actions listed in
``read_only_posts`` can be sent. IAM is a Query API read with GET, asking for JSON.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar
from urllib.parse import urlencode

from pydantic import Field, SecretStr, field_validator

from dsec_metrics.plugins.sdk.aws_sigv4 import Credentials, sign
from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig

SERVICES = {
    "kms": ("kms", "TrentService"),
    "acm": ("acm", "CertificateManager"),
    "config": ("config", "StarlingDoveService"),
}


IAM_READS = frozenset({"ListUsers", "ListAccessKeys"})


class AwsConfig(HttpCollectorConfig):
    """One account and region. Credentials are secret references."""

    region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]$")
    access_key_id: str = Field(description="Secret reference, for example env://AWS_ACCESS_KEY_ID")
    secret_access_key: str = Field(description="Secret reference")
    session_token: str | None = Field(default=None, description="Secret reference")
    endpoint_url: str | None = Field(
        default=None, description="Override every service endpoint, for example for LocalStack"
    )
    account_label: str = ""
    dimensions: dict[str, str] = Field(default_factory=dict)

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("endpoint_url must be an http(s) URL")
        return value.rstrip("/") if value else value


def _members(value: Any) -> list[dict[str, Any]]:
    """A list from a Query API response in JSON: a plain list, or the ``{"member": ...}``
    form some implementations keep from the XML, with one member not wrapped in a list."""
    if isinstance(value, dict) and "member" in value:
        value = value["member"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def _epoch_date(value: Any) -> date | None:
    if isinstance(value, str) and value.replace(".", "", 1).isdigit():
        value = float(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).date()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


class AwsCollector(HttpCollector):
    """Read-only AWS evidence for key management, certificates, configuration and IAM."""

    name = "aws"
    version = "1.0.0"
    config_model = AwsConfig
    queries: ClassVar[dict[str, str]] = {
        "kms_key_rotation": "Customer-managed KMS keys with state and rotation status",
        "acm_certificates": "ACM certificates with expiry and days remaining",
        "config_rule_compliance": "AWS Config rules with compliance and non-compliant counts",
        "iam_access_key_age": "IAM users' access keys with status and age in days",
    }
    required_permissions: ClassVar[list[str]] = [
        "kms:ListKeys",
        "kms:DescribeKey",
        "kms:GetKeyRotationStatus",
        "acm:ListCertificates",
        "acm:DescribeCertificate",
        "config:DescribeComplianceByConfigRule",
        "iam:ListUsers",
        "iam:ListAccessKeys",
    ]
    read_only_posts: ClassVar[frozenset[str]] = frozenset(
        {
            "TrentService.ListKeys",
            "TrentService.DescribeKey",
            "TrentService.GetKeyRotationStatus",
            "CertificateManager.ListCertificates",
            "CertificateManager.DescribeCertificate",
            "StarlingDoveService.DescribeComplianceByConfigRule",
        }
    )

    config: AwsConfig

    # Plumbing.

    def _credentials(self) -> Credentials:
        def get(ref: str | None) -> str | None:
            if ref is None:
                return None
            value: SecretStr = self.secrets.resolve(ref)
            return value.get_secret_value()

        key_id = get(self.config.access_key_id)
        secret = get(self.config.secret_access_key)
        if not key_id or not secret:
            raise CollectorError("aws: access key is empty")
        return Credentials(key_id, secret, get(self.config.session_token))

    def _endpoint(self, service: str) -> str:
        if self.config.endpoint_url:
            return self.config.endpoint_url + "/"
        if service == "iam":
            return "https://iam.amazonaws.com/"
        return f"https://{service}.{self.config.region}.amazonaws.com/"

    def _json_call(self, service: str, operation: str, payload: dict[str, Any]) -> Any:
        signing_name, prefix = SERVICES[service]
        action = f"{prefix}.{operation}"
        url = self._endpoint(service)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = sign(
            "POST",
            url,
            {"content-type": "application/x-amz-json-1.1", "x-amz-target": action},
            body,
            self._credentials(),
            self.config.region,
            signing_name,
        )
        return self.http.request("POST", url, headers=headers, body=body, action=action).json()

    def _iam(self, action: str, params: dict[str, str]) -> Any:
        # IAM's Query API accepts writes over GET too, so only these actions are sent.
        if action not in IAM_READS:
            raise CollectorError(f"aws: IAM action {action} is not a declared read")
        region = "us-east-1"  # IAM is global and signs in us-east-1
        query = urlencode({"Action": action, "Version": "2010-05-08", **params})
        url = f"{self._endpoint('iam')}?{query}"
        headers = sign(
            "GET", url, {"accept": "application/json"}, b"", self._credentials(), region, "iam"
        )
        return self.http.request("GET", url, headers=headers).json()

    def _paged(
        self, service: str, operation: str, key: str, token_in: str, token_out: str, **payload: Any
    ) -> Iterator[dict[str, Any]]:
        token: str | None = None
        pages = records = 0
        while True:
            body = dict(payload)
            if token:
                body[token_in] = token
            data = self._json_call(service, operation, body)
            items = data.get(key) or []
            pages += 1
            records += len(items)
            self._check_limits(pages, records)
            yield from items
            token = data.get(token_out)
            if not token or data.get("Truncated") is False:
                return

    def _record(self, values: dict[str, Any]) -> dict[str, Any]:
        base = {"account": self.config.account_label, "region": self.config.region}
        return {**base, **self.config.dimensions, **values}

    # Collector interface.

    def test_connection(self) -> ConnectionResult:
        try:
            self._json_call("kms", "ListKeys", {"Limit": 1})
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail="KMS ListKeys succeeded")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        records = list(getattr(self, f"_{query}")(as_of))
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )

    def _kms_key_rotation(self, as_of: date) -> Iterator[dict[str, Any]]:
        for key in self._paged("kms", "ListKeys", "Keys", "Marker", "NextMarker", Limit=100):
            meta = self._json_call("kms", "DescribeKey", {"KeyId": key["KeyId"]}).get(
                "KeyMetadata", {}
            )
            manager = meta.get("KeyManager", "")
            if manager != "CUSTOMER":
                continue
            symmetric = meta.get("KeySpec", "SYMMETRIC_DEFAULT") == "SYMMETRIC_DEFAULT"
            enabled = meta.get("KeyState") == "Enabled"
            rotation: dict[str, Any] = {}
            if symmetric and enabled and meta.get("Origin", "AWS_KMS") == "AWS_KMS":
                rotation = self._json_call("kms", "GetKeyRotationStatus", {"KeyId": key["KeyId"]})
            created = _epoch_date(meta.get("CreationDate"))
            yield self._record(
                {
                    "key_id": key["KeyId"],
                    "key_state": meta.get("KeyState"),
                    "key_spec": meta.get("KeySpec"),
                    "origin": meta.get("Origin"),
                    "rotation_supported": bool(rotation) or (symmetric and enabled),
                    "rotation_enabled": bool(rotation.get("KeyRotationEnabled", False)),
                    "rotation_period_days": rotation.get("RotationPeriodInDays"),
                    "created": created.isoformat() if created else None,
                    "age_days": (as_of - created).days if created else None,
                }
            )

    def _acm_certificates(self, as_of: date) -> Iterator[dict[str, Any]]:
        listing = self._paged(
            "acm",
            "ListCertificates",
            "CertificateSummaryList",
            "NextToken",
            "NextToken",
            MaxItems=100,
        )
        for summary in listing:
            cert = self._json_call(
                "acm", "DescribeCertificate", {"CertificateArn": summary["CertificateArn"]}
            ).get("Certificate", {})
            not_after = _epoch_date(cert.get("NotAfter"))
            yield self._record(
                {
                    "certificate_arn": summary["CertificateArn"],
                    "domain": cert.get("DomainName") or summary.get("DomainName"),
                    "status": cert.get("Status"),
                    "type": cert.get("Type"),
                    "in_use": bool(cert.get("InUseBy")),
                    "not_after": not_after.isoformat() if not_after else None,
                    "days_to_expiry": (not_after - as_of).days if not_after else None,
                }
            )

    def _config_rule_compliance(self, as_of: date) -> Iterator[dict[str, Any]]:
        del as_of
        rules = self._paged(
            "config",
            "DescribeComplianceByConfigRule",
            "ComplianceByConfigRules",
            "NextToken",
            "NextToken",
        )
        for rule in rules:
            compliance = rule.get("Compliance") or {}
            count = compliance.get("ComplianceContributorCount") or {}
            yield self._record(
                {
                    "rule": rule.get("ConfigRuleName"),
                    "compliance": compliance.get("ComplianceType", "INSUFFICIENT_DATA"),
                    "noncompliant_resources": count.get("CappedCount", 0),
                    "count_capped": bool(count.get("CapExceeded", False)),
                }
            )

    def _iam_access_key_age(self, as_of: date) -> Iterator[dict[str, Any]]:
        marker: str | None = None
        pages = records = 0
        while True:
            data = self._iam("ListUsers", {"Marker": marker} if marker else {})
            result = (data.get("ListUsersResponse") or {}).get("ListUsersResult") or {}
            pages += 1
            self._check_limits(pages, records)
            for user in _members(result.get("Users")):
                keys = self._iam("ListAccessKeys", {"UserName": user["UserName"]})
                listing = (keys.get("ListAccessKeysResponse") or {}).get("ListAccessKeysResult")
                for key in _members((listing or {}).get("AccessKeyMetadata")):
                    records += 1
                    self._check_limits(pages, records)
                    created = _epoch_date(key.get("CreateDate"))
                    yield self._record(
                        {
                            "user": user["UserName"],
                            "access_key_id": key.get("AccessKeyId"),
                            "status": key.get("Status"),
                            "created": created.isoformat() if created else None,
                            "age_days": (as_of - created).days if created else None,
                        }
                    )
            if str(result.get("IsTruncated", "false")).lower() != "true":
                return
            marker = result.get("Marker")
