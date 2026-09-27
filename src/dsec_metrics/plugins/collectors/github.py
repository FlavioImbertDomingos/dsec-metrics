"""``github`` collector: branch protection, code scanning alerts and Dependabot alerts
for a list of repositories, with a read-only fine-grained token."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import Field

from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpCollector, HttpCollectorConfig, path_segment


class GithubConfig(HttpCollectorConfig):
    """API address (GitHub Enterprise Server has its own), token reference, repositories."""

    api_url: str = Field(default="https://api.github.com", pattern=r"^https://[^/]+(/api/v3)?$")
    token: str = Field(description="Secret reference to a fine-grained, read-only token")
    repositories: list[str] = Field(min_length=1, description="owner/name")
    dimensions: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="owner/name -> dimensions such as business_unit"
    )


def _days(since: str | None, as_of: date) -> int | None:
    if not since:
        return None
    try:
        return (as_of - datetime.fromisoformat(since.replace("Z", "+00:00")).date()).days
    except ValueError:
        return None


class GithubCollector(HttpCollector):
    """Read-only repository security evidence."""

    name = "github"
    version = "1.0.0"
    config_model = GithubConfig
    queries: ClassVar[dict[str, str]] = {
        "branch_protection": "Default branch protection: reviews, checks, admins, force pushes",
        "code_scanning_alerts": "Open code scanning alerts with severity and age",
        "dependabot_alerts": "Open Dependabot alerts with severity and age",
    }
    required_permissions: ClassVar[list[str]] = [
        "Metadata: read",
        "Administration: read (branch protection)",
        "Code scanning alerts: read",
        "Dependabot alerts: read",
    ]

    config: GithubConfig

    def _headers(self) -> dict[str, str]:
        token = self.secrets.resolve(self.config.token).get_secret_value()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self, repo: str) -> str:
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise CollectorError(f"github: repository must be owner/name, not {repo!r}")
        return f"{self.config.api_url}/repos/{repo}"

    def test_connection(self) -> ConnectionResult:
        try:
            self.http.get_json(self._repo(self.config.repositories[0]), headers=self._headers())
        except CollectorError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        return ConnectionResult(ok=True, detail="repository readable")

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        records = []
        for repo in self.config.repositories:
            for record in getattr(self, f"_{query}")(repo, as_of):
                records.append(
                    {"repository": repo, **self.config.dimensions.get(repo, {}), **record}
                )
        yield RecordBatch(
            query=query, params=params, records=records, collected_at=datetime.now(UTC)
        )

    def _branch_protection(self, repo: str, as_of: date) -> Iterator[dict[str, Any]]:
        del as_of
        meta = self.http.get_json(self._repo(repo), headers=self._headers())
        branch = meta.get("default_branch", "main")
        try:
            rules = self.http.get_json(
                f"{self._repo(repo)}/branches/{path_segment(branch)}/protection",
                headers=self._headers(),
            )
        except CollectorError as exc:
            if "HTTP 404" not in str(exc):
                raise
            rules = None
        reviews = (rules or {}).get("required_pull_request_reviews") or {}
        checks = (rules or {}).get("required_status_checks") or {}
        yield {
            "branch": branch,
            "protected": rules is not None,
            "required_approvals": reviews.get("required_approving_review_count", 0),
            "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews", False)),
            "code_owner_reviews": bool(reviews.get("require_code_owner_reviews", False)),
            "required_checks": len(checks.get("checks") or checks.get("contexts") or []),
            "enforce_admins": bool(
                ((rules or {}).get("enforce_admins") or {}).get("enabled", False)
            ),
            "allow_force_pushes": bool(
                ((rules or {}).get("allow_force_pushes") or {}).get("enabled", False)
            ),
            "signed_commits": bool(
                ((rules or {}).get("required_signatures") or {}).get("enabled", False)
            ),
        }

    def _alerts(self, url: str, as_of: date, kind: str) -> Iterator[dict[str, Any]]:
        for page in self.pages_by_link(
            url, params={"state": "open", "per_page": 100}, headers=self._headers()
        ):
            for alert in page:
                if kind == "code":
                    rule = alert.get("rule") or {}
                    severity = rule.get("security_severity_level") or rule.get("severity")
                    name = rule.get("id")
                else:
                    advisory = alert.get("security_advisory") or {}
                    severity = advisory.get("severity")
                    name = advisory.get("ghsa_id")
                yield {
                    "number": alert.get("number"),
                    "rule": name,
                    "severity": severity,
                    "state": alert.get("state"),
                    "created": (alert.get("created_at") or "")[:10] or None,
                    "age_days": _days(alert.get("created_at"), as_of),
                }

    def _code_scanning_alerts(self, repo: str, as_of: date) -> Iterator[dict[str, Any]]:
        return self._alerts(f"{self._repo(repo)}/code-scanning/alerts", as_of, "code")

    def _dependabot_alerts(self, repo: str, as_of: date) -> Iterator[dict[str, Any]]:
        return self._alerts(f"{self._repo(repo)}/dependabot/alerts", as_of, "dependabot")
