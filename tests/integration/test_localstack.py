"""Acceptance for M4: the ``aws`` collector against LocalStack, over the real network path.

The collector connects through the SDK's socket transport, the outbound policy and SigV4,
exactly as in production; only the endpoint is LocalStack's. The test's own setup calls
(creating keys, users and certificates) are made directly, since the collector cannot
write.

LocalStack's AWS Config does not implement DescribeComplianceByConfigRule, so that query
is checked to fail cleanly here and is covered by its contract test on fixtures.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import time
from base64 import b64encode
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.core.container import DockerContainer

from dsec_metrics.core.definitions import CollectorInstance
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import RecordBatchRow
from dsec_metrics.pipeline import run_collection
from dsec_metrics.plugins.collectors.aws import AwsCollector, AwsConfig
from dsec_metrics.plugins.sdk import http as sdk_http
from dsec_metrics.plugins.sdk.aws_sigv4 import Credentials, sign
from dsec_metrics.plugins.sdk.base import CollectorError
from dsec_metrics.plugins.sdk.http import HttpClient
from dsec_metrics.plugins.sdk.registry import default_secret_resolver
from dsec_metrics.plugins.sdk.ssrf import OutboundPolicy

pytestmark = pytest.mark.integration

# 4.4.0 predates LocalStack's account token requirement. Pinned by digest.
IMAGE = (
    "localstack/localstack:4.4.0"
    "@sha256:b52c16663c70b7234f217cb993a339b46686e30a1a5d9279cb5feeb2202f837c"
)
HOST = "localstack.test"
REGION = "eu-west-1"
CREDENTIALS = Credentials("test", "test")


class LocalStack:
    def __init__(self, address: str) -> None:
        self.address = address
        self.url = f"http://{HOST}:4566/"

    def _send(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Any:
        conn = http.client.HTTPConnection(self.address, 4566, timeout=30)
        try:
            conn.request(method, url.removeprefix(f"http://{HOST}:4566"), body, headers)
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        assert response.status == 200, data[:500]
        return json.loads(data) if data else {}

    def call(self, service: str, target: str, payload: dict[str, Any]) -> Any:
        """A JSON API call (setup only: these may write)."""
        body = json.dumps(payload).encode()
        headers = sign(
            "POST",
            self.url,
            {"content-type": "application/x-amz-json-1.1", "x-amz-target": target},
            body,
            CREDENTIALS,
            REGION,
            service,
        )
        return self._send("POST", self.url, {**headers, "Host": f"{HOST}:4566"}, body)

    def iam(self, action: str, **params: str) -> Any:
        url = self.url + "?" + urlencode({"Action": action, "Version": "2010-05-08", **params})
        headers = sign(
            "GET", url, {"accept": "application/json"}, b"", CREDENTIALS, "us-east-1", "iam"
        )
        return self._send("GET", url, {**headers, "Host": f"{HOST}:4566"}, b"")


def _wait_ready(address: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection(address, 4566, timeout=5)
            conn.request("GET", "/_localstack/health")
            health = json.loads(conn.getresponse().read())
            conn.close()
            services = health.get("services", {})
            if all(services.get(s) in {"available", "running"} for s in ("kms", "acm", "iam")):
                return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise AssertionError("LocalStack did not become ready")


@pytest.fixture(scope="module")
def localstack() -> Iterator[LocalStack]:
    container = DockerContainer(IMAGE).with_env("SERVICES", "kms,acm,iam,config")
    container.with_env("LOCALSTACK_TELEMETRY_DISABLED", "1")  # no outbound calls from CI
    container.with_env("DISABLE_EVENTS", "1")
    with container:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        networks = wrapped.attrs["NetworkSettings"]["Networks"]
        address = next(n["IPAddress"] for n in networks.values() if n.get("IPAddress"))
        _wait_ready(address, time.monotonic() + 120)
        yield LocalStack(address)


def _certificate(days: int) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "portal.example.test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("portal.example.test")]), False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


@pytest.fixture(scope="module")
def seeded(localstack: LocalStack) -> dict[str, Any]:
    rotated = localstack.call("kms", "TrentService.CreateKey", {"Description": "rotated"})
    plain = localstack.call("kms", "TrentService.CreateKey", {"Description": "not rotated"})
    signing = localstack.call(
        "kms", "TrentService.CreateKey", {"KeySpec": "ECC_NIST_P256", "KeyUsage": "SIGN_VERIFY"}
    )
    rotated_id = rotated["KeyMetadata"]["KeyId"]
    localstack.call("kms", "TrentService.EnableKeyRotation", {"KeyId": rotated_id})
    cert, key = _certificate(days=20)
    imported = localstack.call(
        "acm",
        "CertificateManager.ImportCertificate",
        {"Certificate": b64encode(cert).decode(), "PrivateKey": b64encode(key).decode()},
    )
    localstack.iam("CreateUser", UserName="svc-reporting")
    localstack.iam("CreateAccessKey", UserName="svc-reporting")
    localstack.iam("CreateUser", UserName="svc-no-keys")
    return {
        "rotated": rotated_id,
        "plain": plain["KeyMetadata"]["KeyId"],
        "signing": signing["KeyMetadata"]["KeyId"],
        "certificate": imported["CertificateArn"],
    }


def policy(localstack: LocalStack) -> OutboundPolicy:
    """The operator's settings for this test: one name, plain HTTP allowed for it, resolved
    to the container's address (a private range, which the policy allows)."""
    return OutboundPolicy(
        allowed_hosts=(HOST,),
        allow_http_hosts=(HOST,),
        resolver=lambda _host, _port: [localstack.address],
    )


def config() -> dict[str, Any]:
    return {
        "region": REGION,
        "access_key_id": "env://LOCALSTACK_KEY_ID",
        "secret_access_key": "env://LOCALSTACK_SECRET",
        "endpoint_url": f"http://{HOST}:4566",
        "account_label": "localstack",
    }


@pytest.fixture
def collector(localstack: LocalStack, monkeypatch: pytest.MonkeyPatch) -> AwsCollector:
    monkeypatch.setenv("LOCALSTACK_KEY_ID", "test")
    monkeypatch.setenv("LOCALSTACK_SECRET", "test")
    client = HttpClient(
        policy(localstack), read_only_posts=AwsCollector.read_only_posts, retries=1, backoff=0.1
    )
    return AwsCollector(AwsConfig.model_validate(config()), default_secret_resolver(), http=client)


def _records(collector: AwsCollector, query: str) -> list[dict[str, Any]]:
    today = dt.datetime.now(dt.UTC).date()
    return [r for b in collector.collect(query, {}, today) for r in b.records]


def test_connection(collector: AwsCollector) -> None:
    result = collector.test_connection()
    assert result.ok, result.detail


def test_kms_key_rotation(collector: AwsCollector, seeded: dict[str, Any]) -> None:
    keys = {k["key_id"]: k for k in _records(collector, "kms_key_rotation")}
    assert keys[seeded["rotated"]]["rotation_enabled"] is True
    assert keys[seeded["plain"]]["rotation_enabled"] is False
    assert keys[seeded["plain"]]["rotation_supported"] is True
    assert keys[seeded["signing"]]["rotation_supported"] is False
    assert keys[seeded["rotated"]]["age_days"] == 0
    assert keys[seeded["rotated"]]["account"] == "localstack"


def test_acm_certificates(collector: AwsCollector, seeded: dict[str, Any]) -> None:
    certs = {c["certificate_arn"]: c for c in _records(collector, "acm_certificates")}
    cert = certs[seeded["certificate"]]
    assert cert["domain"] == "portal.example.test"
    assert cert["days_to_expiry"] in {19, 20}


def test_iam_access_key_age(collector: AwsCollector, seeded: dict[str, Any]) -> None:
    del seeded
    keys = _records(collector, "iam_access_key_age")
    mine = [k for k in keys if k["user"] == "svc-reporting"]
    assert len(mine) == 1
    assert mine[0]["status"] == "Active"
    assert mine[0]["age_days"] == 0
    assert not [k for k in keys if k["user"] == "svc-no-keys"]


def test_config_rule_compliance_is_not_implemented_by_localstack(collector: AwsCollector) -> None:
    with pytest.raises(CollectorError, match="HTTP 501"):
        _records(collector, "config_rule_compliance")


def test_blocked_without_the_operator_allowing_plain_http(
    localstack: LocalStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALSTACK_KEY_ID", "test")
    monkeypatch.setenv("LOCALSTACK_SECRET", "test")
    strict = OutboundPolicy(allowed_hosts=(HOST,), resolver=lambda _h, _p: [localstack.address])
    client = HttpClient(strict, read_only_posts=AwsCollector.read_only_posts, retries=0)
    collector = AwsCollector(
        AwsConfig.model_validate(config()), default_secret_resolver(), http=client
    )
    result = collector.test_connection()
    assert not result.ok
    assert "plain HTTP" in result.detail


def test_through_the_pipeline(
    localstack: LocalStack,
    seeded: dict[str, Any],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_KEY_ID", "test")
    monkeypatch.setenv("LOCALSTACK_SECRET", "test")
    monkeypatch.setattr(sdk_http, "default_policy", lambda: policy(localstack))
    instance = CollectorInstance(id="aws-localstack", plugin="aws", config=config())
    today = dt.datetime.now(dt.UTC).date()
    with transaction(session_factory) as db:
        result = run_collection(
            db, instance, "kms_key_rotation", today, default_secret_resolver(), actor="test"
        )
    assert result.status == "succeeded", result.error
    with session_factory() as db:
        row = db.scalars(
            select(RecordBatchRow).where(RecordBatchRow.instance_id == "aws-localstack")
        ).one()
        assert row.collector == "aws"
        assert seeded["rotated"] in {r["key_id"] for r in row.records}
        assert len(row.sha256) == 64
