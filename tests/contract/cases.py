"""Recorded responses and configurations for the built-in HTTP collectors.

The fixtures under ``fixtures/`` are synthetic: example.test hosts, AWS's documentation
account ID, made-up keys and issues. Some carry the test card number 4111111111111111 in
a field the collector copies, so the pipeline test can check it is masked before storage.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dsec_metrics.plugins.sdk.http import HttpRequest
from dsec_metrics.plugins.sdk.testing import FixtureRoute

FIXTURES = Path(__file__).parent / "fixtures"
PAN = "4111111111111111"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def by_body(fixture: str, field_name: str) -> Callable[[HttpRequest], Any]:
    """Answer a JSON API call from a fixture keyed by one field of the request body."""
    table = load(fixture)

    def reply(request: HttpRequest) -> Any:
        return table[json.loads(request.body or b"{}")[field_name]]

    return reply


def paged(first: str, second: str, token_field: str) -> Callable[[HttpRequest], Any]:
    """First page without a token, second page when the request carries one."""

    def reply(request: HttpRequest) -> Any:
        body = json.loads(request.body or b"{}")
        return load(second if body.get(token_field) else first)

    return reply


@dataclass(frozen=True)
class Case:
    plugin: str
    config: dict[str, Any]
    env: dict[str, str]
    hosts: tuple[str, ...]
    routes: Mapping[str, FixtureRoute]
    queries: tuple[str, ...]
    pan_query: str
    extra: dict[str, Any] = field(default_factory=dict)


def _iam(action: str, **params: str) -> str:
    return "GET /?" + urlencode({"Action": action, "Version": "2010-05-08", **params})


_keys = load("aws/iam-list-access-keys.json")

AWS = Case(
    plugin="aws",
    config={
        "region": "eu-west-1",
        "access_key_id": "env://TEST_AWS_KEY_ID",
        "secret_access_key": "env://TEST_AWS_SECRET",
        "account_label": "example-prod",
        "dimensions": {"environment": "prod"},
    },
    env={"TEST_AWS_KEY_ID": "AKIDEXAMPLEKEY000000", "TEST_AWS_SECRET": "example-secret-key"},
    hosts=(
        "kms.eu-west-1.amazonaws.com",
        "acm.eu-west-1.amazonaws.com",
        "config.eu-west-1.amazonaws.com",
        "iam.amazonaws.com",
    ),
    routes={
        "POST / TrentService.ListKeys": paged(
            "aws/kms-list-keys-1.json", "aws/kms-list-keys-2.json", "Marker"
        ),
        "POST / TrentService.DescribeKey": by_body("aws/kms-describe-key.json", "KeyId"),
        "POST / TrentService.GetKeyRotationStatus": {
            "KeyRotationEnabled": True,
            "RotationPeriodInDays": 365,
        },
        "POST / CertificateManager.ListCertificates": load("aws/acm-list-certificates.json"),
        "POST / CertificateManager.DescribeCertificate": by_body(
            "aws/acm-describe-certificate.json", "CertificateArn"
        ),
        "POST / StarlingDoveService.DescribeComplianceByConfigRule": paged(
            "aws/config-compliance-1.json", "aws/config-compliance-2.json", "NextToken"
        ),
        _iam("ListUsers"): load("aws/iam-list-users.json"),
        **{_iam("ListAccessKeys", UserName=user): body for user, body in _keys.items()},
    },
    queries=(
        "kms_key_rotation",
        "acm_certificates",
        "config_rule_compliance",
        "iam_access_key_age",
    ),
    pan_query="iam_access_key_age",
)

VAULT = Case(
    plugin="vault",
    config={
        "address": "https://vault.example.test:8200",
        "token": "env://TEST_VAULT_TOKEN",
        "namespace": "security",
        "dimensions": {"environment": "prod"},
    },
    env={"TEST_VAULT_TOKEN": "hvs.example-token"},
    hosts=("vault.example.test",),
    routes={
        "GET /v1/sys/auth": FIXTURES / "vault/sys-auth.json",
        "GET /v1/sys/audit": FIXTURES / "vault/sys-audit.json",
        "GET /v1/sys/health?standbyok=true&perfstandbyok=true": FIXTURES / "vault/sys-health.json",
        "GET /v1/transit/keys?list=true": FIXTURES / "vault/transit-keys.json",
        "GET /v1/transit/keys/payments-dek": FIXTURES / "vault/transit-key-payments-dek.json",
        "GET /v1/transit/keys/tokenization": FIXTURES / "vault/transit-key-tokenization.json",
        f"GET /v1/transit/keys/legacy-{PAN}": FIXTURES / "vault/transit-key-legacy.json",
    },
    queries=("auth_methods", "audit_devices", "transit_key_versions"),
    pan_query="transit_key_versions",
)

JIRA_FIELDS = "summary,status,priority,created,duedate,labels"
JIRA_JQL = "project = SEC AND labels = finding"

JIRA = Case(
    plugin="jira",
    config={
        "base_url": "https://example.atlassian.test",
        "email": "env://TEST_JIRA_EMAIL",
        "api_token": "env://TEST_JIRA_TOKEN",
        "searches": {"findings": JIRA_JQL},
        "dimension_fields": {"business_unit": "customfield_10050"},
    },
    env={"TEST_JIRA_EMAIL": "reader@example.test", "TEST_JIRA_TOKEN": "example-jira-token"},
    hosts=("example.atlassian.test",),
    routes={
        "GET /rest/api/3/search/jql?"
        + urlencode({"jql": JIRA_JQL, "fields": JIRA_FIELDS, "maxResults": 100}): FIXTURES
        / "jira/search-1.json",
        "GET /rest/api/3/search/jql?"
        + urlencode(
            {"jql": JIRA_JQL, "fields": JIRA_FIELDS, "maxResults": 100, "nextPageToken": "tok-2"}
        ): FIXTURES / "jira/search-2.json",
        "GET /rest/api/3/myself": FIXTURES / "jira/myself.json",
    },
    queries=("findings",),
    pan_query="findings",
)

SN_PARAMS = {
    "sysparm_query": "active=true^ORDERBYnumber",
    "sysparm_fields": "number,opened_at,priority,short_description,state,u_business_unit",
    "sysparm_display_value": "true",
    "sysparm_exclude_reference_link": "true",
}

SERVICENOW = Case(
    plugin="servicenow",
    config={
        "instance_url": "https://example.service-now.test",
        "username": "env://TEST_SN_USER",
        "password": "env://TEST_SN_PASSWORD",
        "page_size": 2,
        "tables": {
            "grc_issues": {
                "table": "sn_grc_issue",
                "query": "active=true^ORDERBYnumber",
                "fields": ["number", "state", "priority", "opened_at", "short_description"],
                "dimension_fields": {"business_unit": "u_business_unit"},
            }
        },
    },
    env={"TEST_SN_USER": "dsec-reader", "TEST_SN_PASSWORD": "example-password"},
    hosts=("example.service-now.test",),
    routes={
        "GET /api/now/table/sn_grc_issue?"
        + urlencode({**SN_PARAMS, "sysparm_offset": 0, "sysparm_limit": 2}): FIXTURES
        / "servicenow/issues-1.json",
        "GET /api/now/table/sn_grc_issue?"
        + urlencode({**SN_PARAMS, "sysparm_offset": 2, "sysparm_limit": 2}): FIXTURES
        / "servicenow/issues-2.json",
        "GET /api/now/table/sn_grc_issue?sysparm_limit=1": {"result": []},
    },
    queries=("grc_issues",),
    pan_query="grc_issues",
)

GH_API = "https://api.github.test"

GITHUB = Case(
    plugin="github",
    config={
        "api_url": GH_API,
        "token": "env://TEST_GH_TOKEN",
        "repositories": ["example-org/payments-api", "example-org/docs"],
        "dimensions": {"example-org/payments-api": {"business_unit": "payments"}},
    },
    env={"TEST_GH_TOKEN": "github_pat_example"},
    hosts=("api.github.test",),
    routes={
        "GET /repos/example-org/payments-api": FIXTURES / "github/repo-payments.json",
        "GET /repos/example-org/docs": FIXTURES / "github/repo-docs.json",
        "GET /repos/example-org/payments-api/branches/main/protection": FIXTURES
        / "github/protection-payments.json",
        "GET /repos/example-org/docs/branches/trunk/protection": (
            404,
            {"message": "Branch not protected"},
            {},
        ),
        "GET /repos/example-org/payments-api/code-scanning/alerts?state=open&per_page=100": (
            FIXTURES / "github/code-scanning-1.json",
            {
                "Link": f"<{GH_API}/repos/example-org/payments-api/code-scanning/alerts"
                '?state=open&per_page=100&page=2>; rel="next"'
            },
        ),
        "GET /repos/example-org/payments-api/code-scanning/alerts?state=open&per_page=100&page=2": (
            FIXTURES / "github/code-scanning-2.json"
        ),
        "GET /repos/example-org/docs/code-scanning/alerts?state=open&per_page=100": [],
        "GET /repos/example-org/payments-api/dependabot/alerts?state=open&per_page=100": (
            FIXTURES / "github/dependabot.json"
        ),
        "GET /repos/example-org/docs/dependabot/alerts?state=open&per_page=100": [],
    },
    queries=("branch_protection", "code_scanning_alerts", "dependabot_alerts"),
    pan_query="code_scanning_alerts",
)

REST = Case(
    plugin="rest",
    config={
        "base_url": "https://inventory.example.test/api",
        "auth": {"header": "X-Api-Key", "scheme": "", "secret": "env://TEST_REST_KEY"},
        "headers": {"X-Client": "dsec-metrics"},
        "queries": {
            "assets": {
                "path": "/v2/assets",
                "params": {"active": True},
                "records_path": "data.assets",
                "pagination": "cursor",
                "cursor_path": "meta.next",
                "cursor_param": "after",
                "fields": ["id", "tier", "owner.team", "encrypted", "notes"],
            }
        },
        "dimensions": {"environment": "prod"},
    },
    env={"TEST_REST_KEY": "example-api-key"},
    hosts=("inventory.example.test",),
    routes={
        "GET /api/v2/assets?active=true": FIXTURES / "rest/assets-1.json",
        "GET /api/v2/assets?active=true&after=c-2": FIXTURES / "rest/assets-2.json",
    },
    queries=("assets",),
    pan_query="assets",
)

CASES = {case.plugin: case for case in (AWS, VAULT, JIRA, SERVICENOW, GITHUB, REST)}
