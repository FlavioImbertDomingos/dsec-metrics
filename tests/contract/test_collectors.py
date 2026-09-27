"""Contract tests for the built-in HTTP collectors, replaying recorded responses."""

from __future__ import annotations

import base64
from datetime import date
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from dsec_metrics.plugins.collectors.aws import AwsCollector
from dsec_metrics.plugins.collectors.rest import RestCollector
from dsec_metrics.plugins.sdk.base import CollectorError
from dsec_metrics.plugins.sdk.http import HttpCollector
from dsec_metrics.plugins.sdk.registry import collector_class, default_secret_resolver
from dsec_metrics.plugins.sdk.secrets import SecretError, SecretProvider, SecretResolver
from dsec_metrics.plugins.sdk.testing import (
    FixtureTransport,
    check_collector_class,
    collect_all,
    fixture_policy,
)
from dsec_metrics.plugins.secrets.env import EnvSecretProvider
from tests.contract.cases import CASES, PAN, Case

AS_OF = date(2026, 9, 30)


def make(
    case: Case, monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[HttpCollector, FixtureTransport]:
    for name, value in case.env.items():
        monkeypatch.setenv(name, value)
    collector = collector_class(case.plugin).from_mapping(
        {**case.config, **overrides}, default_secret_resolver()
    )
    assert isinstance(collector, HttpCollector)
    transport = FixtureTransport(case.routes)
    collector.use_transport(transport, fixture_policy(*case.hosts))
    return collector, transport


def records(case: Case, query: str, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    collector, _ = make(case, monkeypatch)
    return [r for batch in collect_all(collector, query, AS_OF) for r in batch.records]


@pytest.mark.parametrize("plugin", sorted(CASES))
def test_every_collector_declares_its_contract(plugin: str) -> None:
    cls = collector_class(plugin)
    check_collector_class(cls)
    assert issubclass(cls, HttpCollector)
    assert cls.required_permissions
    assert cls.queries_for(CASES[plugin].config) == sorted(CASES[plugin].queries)


@pytest.mark.parametrize(
    ("plugin", "query"),
    [(plugin, query) for plugin, case in sorted(CASES.items()) for query in case.queries],
)
def test_every_query_reads_only_and_sends_credentials_from_references(
    plugin: str, query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = CASES[plugin]
    collector, transport = make(case, monkeypatch)
    batches = collect_all(collector, query, AS_OF)
    assert batches
    assert all(b.records for b in batches) or query == "audit_devices"
    methods = {r.method for r in transport.requests}
    assert methods <= {"GET", "POST"}
    for request in transport.requests:
        if request.method == "POST":
            assert request.action in collector.read_only_posts
        assert request.headers.get("User-Agent", "").startswith("dsec-metrics/")
    secret_values = set(case.env.values())
    sent = " ".join(" ".join(r.headers.values()) for r in transport.requests)
    decoded = " ".join(
        base64.b64decode(v.split(" ", 1)[1]).decode()
        for r in transport.requests
        for k, v in r.headers.items()
        if k == "Authorization" and v.startswith("Basic ")
    )
    assert any(value in sent or value in decoded for value in secret_values) or plugin == "aws"
    for request in transport.requests:
        assert not any(value in request.url for value in secret_values)


@pytest.mark.parametrize("plugin", sorted(CASES))
def test_test_connection(plugin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES[plugin]
    routes: dict[str, Any] = dict(case.routes)
    if plugin == "aws":
        routes["POST / TrentService.ListKeys"] = {"Keys": []}
    collector, _ = make(case, monkeypatch)
    collector.use_transport(FixtureTransport(routes), fixture_policy(*case.hosts))
    assert collector.test_connection().ok
    collector.use_transport(FixtureTransport({}), fixture_policy(*case.hosts))
    with pytest.raises(AssertionError, match="no recorded response"):
        collector.test_connection()
    collector.use_transport(FixtureTransport({}), fixture_policy("other.example.test"))
    result = collector.test_connection()
    assert not result.ok
    assert "allowlist" in result.detail
    assert not any(value in result.detail for value in case.env.values())


@pytest.mark.parametrize("plugin", sorted(CASES))
def test_card_numbers_reach_redaction_through_every_collector(
    plugin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixtures put a test card number in a copied field; the pipeline test checks
    the platform masks it. Here we check the collector passes it through, so that test
    is not vacuous."""
    case = CASES[plugin]
    assert PAN in str(records(case, case.pan_query, monkeypatch))


def test_aws_records(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["aws"]
    keys = records(case, "kms_key_rotation", monkeypatch)
    assert [k["key_id"] for k in keys] == ["k-1", "k-3", "k-4"]
    first = keys[0]
    assert first["rotation_enabled"] is True
    assert first["rotation_period_days"] == 365
    assert first["age_days"] == (AS_OF - date(2024, 1, 15)).days
    assert (first["account"], first["region"], first["environment"]) == (
        "example-prod",
        "eu-west-1",
        "prod",
    )
    assert keys[1]["rotation_supported"] is False
    assert keys[2]["rotation_enabled"] is False

    certs = records(case, "acm_certificates", monkeypatch)
    assert [(c["domain"], c["days_to_expiry"], c["in_use"]) for c in certs] == [
        ("portal.example.test", 15, True),
        ("old.example.test", -29, False),
    ]

    rules = records(case, "config_rule_compliance", monkeypatch)
    assert [(r["compliance"], r["noncompliant_resources"]) for r in rules] == [
        ("COMPLIANT", 0),
        ("NON_COMPLIANT", 3),
        ("INSUFFICIENT_DATA", 0),
    ]

    access = records(case, "iam_access_key_age", monkeypatch)
    assert [(a["status"], a["age_days"]) for a in access] == [
        ("Active", (AS_OF - date(2025, 1, 1)).days),
        ("Inactive", (AS_OF - date(2023, 6, 30)).days),
    ]


def test_aws_signs_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    collector, transport = make(CASES["aws"], monkeypatch)
    collect_all(collector, "kms_key_rotation", AS_OF)
    collect_all(collector, "iam_access_key_age", AS_OF)
    for request in transport.requests:
        auth = request.headers["Authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLEKEY000000/")
        assert "example-secret-key" not in auth
        if request.method == "POST":
            assert request.headers["x-amz-target"] == request.action
            assert "/eu-west-1/kms/aws4_request" in auth
        else:
            assert "/us-east-1/iam/aws4_request" in auth
    assert sum(1 for r in transport.requests if r.action == "TrentService.ListKeys") == 2


def test_aws_endpoint_override_and_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_AWS_SESSION", "example-session")
    case = CASES["aws"]
    collector, transport = make(
        case,
        monkeypatch,
        endpoint_url="https://aws.example.test/",
        session_token="env://TEST_AWS_SESSION",
    )
    collector.use_transport(transport, fixture_policy("aws.example.test"))
    collect_all(collector, "config_rule_compliance", AS_OF)
    assert all(r.url == "https://aws.example.test/" for r in transport.requests)
    assert transport.requests[0].headers["x-amz-security-token"] == "example-session"


def test_aws_config_validation_and_empty_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        AwsCollector.config_model.model_validate({**CASES["aws"].config, "region": "eu west"})
    with pytest.raises(ValidationError):
        AwsCollector.config_model.model_validate({**CASES["aws"].config, "endpoint_url": "ftp://x"})
    monkeypatch.delenv("TEST_MISSING", raising=False)
    collector, _ = make(CASES["aws"], monkeypatch, secret_access_key="env://TEST_MISSING")
    with pytest.raises(SecretError, match="not set"):
        collect_all(collector, "config_rule_compliance", AS_OF)

    class Blank(SecretProvider):
        scheme = "blank"

        def resolve(self, reference: str) -> SecretStr:
            del reference
            return SecretStr("")

    config = {**CASES["aws"].config, "access_key_id": "blank://x"}
    resolver = SecretResolver({"blank": Blank(), "env": EnvSecretProvider()})
    empty = AwsCollector.from_mapping(config, resolver)
    assert isinstance(empty, AwsCollector)
    empty.use_transport(FixtureTransport({}), fixture_policy(*CASES["aws"].hosts))
    with pytest.raises(CollectorError, match="access key is empty"):
        collect_all(empty, "config_rule_compliance", AS_OF)


def test_vault_records(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["vault"]
    auth = records(case, "auth_methods", monkeypatch)
    assert [(a["mount"], a["type"], a["max_lease_ttl"]) for a in auth] == [
        ("oidc/", "oidc", 28800),
        ("token/", "token", 0),
    ]
    audit = records(case, "audit_devices", monkeypatch)
    assert audit == [
        {
            "environment": "prod",
            "mount": "file/",
            "type": "file",
            "local": False,
            "hmac_accessor": True,
            "log_raw": False,
        }
    ]
    keys = {k["key"]: k for k in records(case, "transit_key_versions", monkeypatch)}
    assert keys["payments-dek"]["latest_version"] == 3
    assert keys["payments-dek"]["latest_version_age_days"] == (AS_OF - date(2024, 7, 1)).days
    assert keys["tokenization"]["latest_version_age_days"] == (AS_OF - date(2026, 3, 31)).days
    assert keys["tokenization"]["deletion_allowed"] is True


def test_vault_sends_token_and_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    collector, transport = make(CASES["vault"], monkeypatch)
    collect_all(collector, "auth_methods", AS_OF)
    headers = transport.requests[0].headers
    assert headers["X-Vault-Token"] == "hvs.example-token"
    assert headers["X-Vault-Namespace"] == "security"


def test_jira_records(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = records(CASES["jira"], "findings", monkeypatch)
    assert [i["key"] for i in issues] == ["SEC-101", "SEC-102", "SEC-103"]
    first = issues[0]
    assert first["status"] == "In Progress"
    assert first["labels"] == ["finding", "pci"]
    assert first["business_unit"] == "cards"
    assert first["age_days"] == (AS_OF - date(2026, 8, 1)).days
    assert issues[2]["age_days"] is None
    assert issues[2]["business_unit"] is None


def test_jira_unknown_search(monkeypatch: pytest.MonkeyPatch) -> None:
    collector, _ = make(CASES["jira"], monkeypatch)
    with pytest.raises(CollectorError, match="no search named"):
        collect_all(collector, "nope", AS_OF)


def test_servicenow_records(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = records(CASES["servicenow"], "grc_issues", monkeypatch)
    assert [r["number"] for r in rows] == ["ISS0001", "ISS0002", "ISS0003"]
    assert rows[0]["business_unit"] == "cards"
    assert "u_business_unit" not in rows[0]
    collector, _ = make(CASES["servicenow"], monkeypatch)
    with pytest.raises(CollectorError, match="no table query"):
        collect_all(collector, "nope", AS_OF)


def test_github_records(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["github"]
    protection = records(case, "branch_protection", monkeypatch)
    assert protection[0] == {
        "repository": "example-org/payments-api",
        "business_unit": "payments",
        "branch": "main",
        "protected": True,
        "required_approvals": 2,
        "dismiss_stale_reviews": True,
        "code_owner_reviews": True,
        "required_checks": 2,
        "enforce_admins": True,
        "allow_force_pushes": False,
        "signed_commits": True,
    }
    assert protection[1]["protected"] is False
    assert protection[1]["branch"] == "trunk"
    alerts = records(case, "code_scanning_alerts", monkeypatch)
    assert [(a["number"], a["severity"], a["age_days"]) for a in alerts] == [
        (7, "high", 29),
        (9, "warning", 5),
        (12, "medium", 92),
    ]
    dependabot = records(case, "dependabot_alerts", monkeypatch)
    assert dependabot[0]["rule"] == "GHSA-xxxx-yyyy-zzzz"
    assert dependabot[0]["severity"] == "critical"


def test_github_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["github"]
    routes: dict[str, Any] = dict(case.routes)
    routes["GET /repos/example-org/docs/branches/trunk/protection"] = (403, {}, {})
    collector, _ = make(case, monkeypatch)
    collector.use_transport(FixtureTransport(routes), fixture_policy(*case.hosts))
    with pytest.raises(CollectorError, match="HTTP 403"):
        collect_all(collector, "branch_protection", AS_OF)
    collector, _ = make(case, monkeypatch, repositories=["not-a-repo"])
    with pytest.raises(CollectorError, match="owner/name"):
        collect_all(collector, "dependabot_alerts", AS_OF)


def test_rest_records(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["rest"]
    collector, transport = make(case, monkeypatch)
    rows = [r for b in collect_all(collector, "assets", AS_OF) for r in b.records]
    assert rows[0] == {
        "environment": "prod",
        "id": "a-1",
        "tier": 1,
        "owner.team": "payments",
        "encrypted": True,
        "notes": f"card {PAN}",
    }
    assert len(rows) == 3
    headers = transport.requests[0].headers
    assert headers["X-Api-Key"] == "example-api-key"
    assert headers["X-Client"] == "dsec-metrics"


@pytest.mark.parametrize(
    ("query", "routes", "expected"),
    [
        ({"path": "/one", "records_path": "items"}, {"GET /api/one": {"items": [{"a": 1}]}}, 1),
        (
            {"path": "/l", "pagination": "link"},
            {
                "GET /api/l": ([{"a": 1}], {"link": '</api/l?p=2>; rel="next"'}),
                "GET /api/l?p=2": [{"a": 2}],
            },
            2,
        ),
        (
            {"path": "/o", "pagination": "offset", "records_path": "r", "page_size": 1},
            {
                "GET /api/o?offset=0&limit=1": {"r": [{"a": 1}]},
                "GET /api/o?offset=1&limit=1": {"r": []},
            },
            1,
        ),
    ],
)
def test_rest_pagination_styles(
    query: dict[str, Any],
    routes: dict[str, Any],
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = CASES["rest"]
    collector, _ = make(case, monkeypatch, queries={"q": query}, auth=None)
    collector.use_transport(FixtureTransport(routes), fixture_policy(*case.hosts))
    assert len(records_of(collector, "q")) == expected


def records_of(collector: HttpCollector, query: str) -> list[dict[str, Any]]:
    return [r for b in collect_all(collector, query, AS_OF) for r in b.records]


def test_rest_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["rest"]
    collector, _ = make(case, monkeypatch, queries={"q": {"path": "/x", "records_path": "a"}})
    collector.use_transport(
        FixtureTransport({"GET /api/x": {"a": {"b": 1}}}), fixture_policy(*case.hosts)
    )
    with pytest.raises(CollectorError, match="list of objects"):
        records_of(collector, "q")
    with pytest.raises(CollectorError, match="no query named"):
        records_of(collector, "missing")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"base_url": "ftp://x"}, "base_url"),
        ({"base_url": "https://x.test/a?b=1"}, "base_url"),
        ({"headers": {"Authorization": "Bearer abc"}}, "carries credentials"),
        ({"queries": {"q": {"path": "/a/../admin"}}}, "segments"),
        ({"queries": {"q": {"path": "relative"}}}, "pattern"),
        ({"queries": {}}, "at least 1"),
        ({"timeout_seconds": 0}, "greater than 0"),
        ({"unknown": 1}, "Extra inputs"),
    ],
)
def test_rest_config_validation(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RestCollector.config_model.model_validate({**CASES["rest"].config, **change})


def test_aws_sends_only_declared_iam_reads_and_limits_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector, transport = make(CASES["aws"], monkeypatch)
    assert isinstance(collector, AwsCollector)
    with pytest.raises(CollectorError, match="not a declared read"):
        collector._iam("DeleteUser", {"UserName": "x"})
    assert transport.requests == []
    limited, _ = make(CASES["aws"], monkeypatch, max_records=1)
    with pytest.raises(CollectorError, match="more than 1 records"):
        collect_all(limited, "iam_access_key_age", AS_OF)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"headers": {"Host": "admin.internal"}}, "cannot be set"),
        ({"headers": {"X-Forwarded-Host": "admin.internal"}}, "cannot be set"),
        ({"auth": {"header": "Host", "secret": "env://X"}}, "cannot be set"),
    ],
)
def test_rest_refuses_routing_headers(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RestCollector.config_model.model_validate({**CASES["rest"].config, **change})


def test_dot_segments_from_responses_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["vault"]
    routes: dict[str, Any] = {
        **case.routes,
        "GET /v1/transit/keys?list=true": {"data": {"keys": [".."]}},
    }
    collector, _ = make(case, monkeypatch)
    collector.use_transport(FixtureTransport(routes), fixture_policy(*case.hosts))
    with pytest.raises(CollectorError, match="dot segment"):
        collect_all(collector, "transit_key_versions", AS_OF)
