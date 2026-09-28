# Proposal: Microsoft Purview collector

Status: proposed, for review together with the M5 plan. Nothing here is built yet. Purview is not in the brief's collector list, so this is a scope addition that needs Flavio's approval.
Date: 2026-09-27

## Goal

Measure data security controls that a Microsoft 365 tenant enforces through Microsoft Purview (data loss prevention, insider risk management, sensitivity labels, audit and eDiscovery), read-only, through Microsoft Graph, with the same traceability as every other collector.

Proposed acceptance: contract tests pass on recorded Graph responses for every query; the token exchange is tested for both credential types; an audit log query is created at most once per instance, query and period, and a rerun reuses it; no user principal name, file name or object ID from Purview reaches the database unless an operator opts in.

## What Purview offers to read

| Area | Graph resource (v1.0) | Least-privileged application permission | Notes |
| --- | --- | --- | --- |
| DLP alerts | `GET /security/alerts_v2?$filter=serviceSource eq 'microsoftDataLossPrevention'` | `SecurityAlert.Read.All` | Filter supports severity, status, classification, determination, createdDateTime |
| Insider risk alerts | same, `serviceSource eq 'microsoftInsiderRiskManagement'` | `SecurityAlert.Read.All` | Microsoft notes usernames are not pseudonymized through the APIs |
| Unified audit log | `POST /security/auditLog/queries`, then `GET .../queries/{id}` and `GET .../queries/{id}/records` | `AuditLogsQuery.Read.All`, or narrower service-specific ones | Record types include `complianceDLPExchange`, `complianceDLPSharePoint`, `complianceDLPEndpoint`, `sensitivityLabelAction`, `mipLabel` |
| Sensitivity labels | `GET /security/dataSecurityAndGovernance/sensitivityLabels` | `SensitivityLabel.Read` | Global cloud only |
| eDiscovery cases | `GET /security/cases/ediscoveryCases` | `eDiscovery.Read.All` | Status, created and closed dates |

Data Security Investigations (DSI) has no documented API or export. Its AI categories and findings stay in the Purview portal. The collector measures what feeds DSI (alerts and cases), not DSI itself. If DSI gains an API, it becomes a new query.

## Queries

| Query | Records | Feeds |
| --- | --- | --- |
| `dlp_alerts` | One per DLP alert created or updated in the lookback window: severity, status, classification, determination, policy name, detection source, created and resolved dates, age in days, days to resolve, evidence count | New KRI "high-severity DLP alerts open more than 7 days"; new KPI "median days to resolve DLP alerts" |
| `insider_risk_alerts` | Same fields as `dlp_alerts`, no user fields | New KRI "insider risk alerts open more than 14 days" |
| `dlp_rule_matches` | One per DLP rule match from the audit log: workload (Exchange, SharePoint, OneDrive, endpoint), policy, rule, sensitive information types matched, action taken, date | KRI-07 "card data found outside approved stores", using matches on credit card information types |
| `label_changes` | One per sensitivity label action from the audit log: action (applied, changed, removed), old and new label priority, whether it was a downgrade, workload, date | New KRI "sensitivity label downgrades and removals per month" |
| `sensitivity_labels` | The label taxonomy: name, priority, enabled, applicable workloads, parent | Evidence for classification controls (no metric) |
| `ediscovery_cases` | Status, created and closed dates, age in days | New KPI "open eDiscovery cases older than 90 days" |

New metric definitions are proposed, not added to the default pack, since the default pack must work with synthetic data. They would ship in `content/examples/purview/` with a matching collector instance, and the `sample` collector gains synthetic versions of the queries so the dashboards can show them on first run.

Dimensions. Alerts and audit records carry no business unit. Each instance maps policy names to dimensions (`dimension_map: {"PCI - Cards BU": {business_unit: cards}}`), and anything unmapped gets `business_unit: unmapped`, so gaps show on the dashboard instead of disappearing.

## Design

### Authentication: a token exchange in the SDK

Graph needs an Entra ID access token from the client credentials grant: `POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` with `client_id`, `scope=https://graph.microsoft.com/.default` and `grant_type=client_credentials`. The SDK client refuses POST unless it is a declared read action, and a token request is neither a read nor a write to source data.

Proposal: a `TokenExchange` component in `plugins/sdk/auth.py`, separate from the read client:

- It sends exactly one kind of request: a POST of a form or JSON body to one token URL fixed by the plugin (the host is still checked against the operator's allowlist and the address policy).
- The response must be JSON with an access token and a lifetime. The token is cached in memory until 60 seconds before it expires, never stored or logged.
- A token response is the only POST response the collector ever reads; everything else still goes through the GET-only client.
- The same component serves BigID (`POST /api/v1/refresh-access-token`) and any later OAuth source, so this is SDK work, not Purview-only work.

Credential types, both as secret references:

1. Client secret. Simple, and no signing on our side. Microsoft describes it as the lower-assurance option.
2. Certificate. The collector signs a short-lived client assertion (a JWT with `aud`, `iss`, `sub`, `jti`, `nbf`, `iat`, `exp` of at most 10 minutes, and the certificate's `x5t#S256` thumbprint). Microsoft's certificate-credential page documents PS256 (RSA-PSS with SHA-256) for the signature.

Workload identity federation (a token from another identity provider, such as a Kubernetes service account) can follow in the Helm work, since it needs no key on our side.

### Paging

Graph pages with an absolute `@odata.nextLink` in the response body. A new SDK helper, `pages_by_next_url`, follows it with the same origin check as `pages_by_link` (scheme, host and port must match the first request). It is generic, for any API that returns next-page URLs in the body.

### Audit log queries

An audit query is a job: create it, wait until its status is `succeeded`, then page its records. Creating it is a POST that leaves a query object in the tenant's audit search history. It changes no source data, but it is visible to Purview admins.

Proposal:

- The query's display name is deterministic: `dsec-metrics <instance> <query> <period start>..<period end>`.
- Before creating, the collector lists existing queries (a GET) and reuses a succeeded or running one with that name. Reruns and retries never create duplicates.
- The create call is a declared read action, `auditLog.createQuery`, allowed only for `POST /security/auditLog/queries` on the Graph host, with a body built from the query definition. No other Graph POST is possible.
- The collector polls with backoff for up to `audit_wait_minutes` (default 10). If the query is still running, the run ends with a new `pending` status instead of `failed`, and the scheduler retries it after `audit_retry_minutes` (default 15). This needs a small scheduler change (a `CollectorPending` result).
- Periods are the metric's period (usually one month), which keeps each query small.

### Privacy

- Default `sensitive_fields` for every query: user principal names, user and object IDs, display names, email addresses, file names and paths, IP addresses, device names and alert evidence details. Records keep counts, severities, policy and rule names, and dates.
- An instance can opt in to keep a field with `keep_fields`, which is logged in the audit log when the instance is synced.
- Insider risk alerts never keep user fields, even with `keep_fields`. Microsoft pseudonymizes them in the portal but not in the API, and a dashboard is the wrong place to reverse that.

### Clouds

`cloud: global | usgov | usgov-dod` selects the token and Graph hosts (`login.microsoftonline.com` and `graph.microsoft.com` for global; the US government clouds use their own hosts, listed on the collector page). `sensitivity_labels` is global only; `alerts_v2` is not available in the China cloud, which is not supported.

## Permissions to document

A dedicated app registration with admin consent for application permissions only:

- `SecurityAlert.Read.All` (note: it covers alerts from every Defender and Purview source, and the collector filters to Purview server-side)
- `AuditLogsQuery.Read.All`, or the service-specific `AuditLogsQuery-Exchange.Read.All`, `AuditLogsQuery-SharePoint.Read.All`, `AuditLogsQuery-OneDrive.Read.All` and `AuditLogsQuery-Endpoint.Read.All` for exactly the workloads in scope
- `SensitivityLabel.Read`
- `eDiscovery.Read.All`

Each query lists the permission it needs, so an operator can grant only what the configured queries use. `test-connection` gets a token and calls one GET per configured query, reporting which permission is missing.

## Decisions for review

1. Token exchange as a narrow SDK exception to "GET and declared read actions only". Recorded in a new ADR (0015). Alternative: a separate auth sidecar, which adds a container and moves the same POST elsewhere.
2. Audit log queries create an object in the tenant. They are reused by name, never deleted, and documented as the one visible side effect of this collector (ADR-0016). Alternative: leave the audit log out and use only alerts, which loses KRI-07 and label downgrades.
3. RSA-PSS for certificate credentials. The brief's algorithm list is SHA-256, AES-256-GCM, Ed25519 and ECDSA P-256. Entra ID's documented algorithm for client assertions is PS256, so certificate credentials need an exception scoped to "algorithms a peer requires for authentication". Without it, only client secrets are supported.
4. Signing the client assertion with the `cryptography` library (already a dependency) instead of MSAL, which the brief does not name and which would bring its own HTTP stack past the outbound policy. Same reasoning as ADR-0014.
5. A `pending` run status and a scheduler retry for long audit queries, instead of blocking a worker for as long as the audit search takes.
6. Example metrics in `content/examples/purview/` rather than the default pack.

## Tests

- Contract tests on synthetic Graph fixtures (tenant and object IDs all zeros or `example.test`) for every query, including `@odata.nextLink` paging, 429 with `Retry-After`, and a 403 for a missing permission.
- Token exchange: client secret and certificate paths; the assertion is verified with the public key and its claims and lifetime checked; token caching and refresh before expiry; the secret never appears in errors.
- Audit query lifecycle: create, poll, succeed, page records; reuse of an existing query; still running ends as `pending`; failed query ends as `failed`; only the declared POST is possible.
- Privacy: fixtures carry user principal names, file paths and a test card number, and the pipeline test checks none reaches the database.
- No live tenant in CI. The collector page documents a manual smoke test against a Microsoft 365 developer tenant.

## Files

`src/dsec_metrics/plugins/sdk/auth.py`, `src/dsec_metrics/plugins/sdk/jwt.py` (client assertions), `src/dsec_metrics/plugins/sdk/http.py` (`pages_by_next_url`), `src/dsec_metrics/plugins/collectors/purview.py`, `src/dsec_metrics/worker/scheduler.py` (`pending`), a migration for the run status, `tests/contract/fixtures/purview/`, `tests/contract/test_purview.py`, `content/examples/purview/`, `docs/collectors/purview.md`, ADR-0015 (token exchange), ADR-0016 (audit queries), threat model update.

## Risks

- Graph permissions are broad. `SecurityAlert.Read.All` also exposes Defender alerts, and `AuditLogsQuery.Read.All` exposes the whole unified audit log. The service-specific audit permissions narrow the second; nothing narrows the first.
- Audit search latency varies from minutes to hours. The pending status keeps the worker free, but monthly metrics can land late.
- Licensing. Some record types and retention periods depend on the tenant's Purview licensing. The collector reports empty results as empty, and the docs say which licences each query needs once confirmed against a test tenant.
- Microsoft changes these APIs often. Only v1.0 endpoints are used; beta endpoints are excluded.
- Without a live tenant in CI, fixture drift is the main correctness risk. Fixtures record the API version and the date captured.

## Open questions for Flavio

- Approve the scope addition, and whether it lands with M5, before M6, or with M6's `azure` collector.
- Decisions 1 to 3 above, in particular the RSA-PSS exception.
- Whether a Microsoft 365 developer tenant is available for a manual smoke test before release.
