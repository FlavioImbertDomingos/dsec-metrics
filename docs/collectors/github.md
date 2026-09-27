# github collector

Reads repository security settings and alerts from GitHub or GitHub Enterprise Server.

| Query | Records |
| --- | --- |
| `branch_protection` | Per repository: default branch, whether it is protected, required approvals, stale review dismissal, code owner reviews, number of required checks, whether admins are included, whether force pushes are allowed, and whether signed commits are required. |
| `code_scanning_alerts` | Open code scanning alerts: number, rule, severity (security severity where present), creation date and age in days. |
| `dependabot_alerts` | Open Dependabot alerts: number, advisory ID, severity, creation date and age in days. |

## Minimum permissions

A fine-grained personal access token or GitHub App installation limited to the listed repositories, with these repository permissions, all read-only:

- Metadata: read
- Administration: read (branch protection)
- Code scanning alerts: read
- Dependabot alerts: read

## Configuration

```yaml
id: github-payments
plugin: github
config:
  api_url: https://api.github.com          # https://github.example.com/api/v3 for Enterprise Server
  token: file:///run/secrets/github_token
  repositories: [example-org/payments-api, example-org/card-vault]
  dimensions:
    example-org/payments-api: {business_unit: payments, application: payments-api}
schedule: "0 5 * * *"
```

A repository whose default branch has no protection is reported with `protected: false`, not as an error.
