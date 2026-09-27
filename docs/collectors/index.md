# Collectors

A collector reads one kind of source system and returns records. Collector instances are YAML files under `content/collectors/`: the plugin, its settings, secret references and a schedule. Every collector is read-only; the permissions each one needs are listed on its page, and no page asks for more than read access.

| Plugin | Reads | Page |
| --- | --- | --- |
| `file` | CSV and JSON files on the worker's disk | [Plugin SDK](../plugins.md#built-in-plugins) |
| `sample` | Synthetic demo data | [Plugin SDK](../plugins.md#built-in-plugins) |
| `rest` | Any JSON API, described in configuration | [rest](rest.md) |
| `aws` | KMS key rotation, ACM certificates, AWS Config rule compliance, IAM access key age | [aws](aws.md) |
| `vault` | Vault or OpenBao auth methods, audit devices and transit keys | [vault](vault.md) |
| `jira` | Issues from JQL searches | [jira](jira.md) |
| `servicenow` | Rows from Table API reads | [servicenow](servicenow.md) |
| `github` | Branch protection, code scanning and Dependabot alerts | [github](github.md) |

`dsec-metrics plugin list` prints every installed collector with its queries and permissions. `dsec-metrics test-connection <instance>` checks an instance can reach its source.

## Outbound calls

Collectors are the only part of dsec-metrics that calls other systems, and only the worker runs them. A fresh install calls nothing: the operator names every host collectors may reach.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DSEC_COLLECTOR_ALLOWED_HOSTS` | empty | Hosts collectors may call, comma-separated. Exact names, or `*.example.com` for any subdomain (not the bare domain). Empty means no outbound calls. |
| `DSEC_COLLECTOR_ALLOW_HTTP_HOSTS` | empty | Hosts that may be called over plain HTTP. For local test endpoints only; everything else must use HTTPS. |

Every request, including each page of a paginated read, goes through the same check before a connection opens ([ADR-0013](../adr/0013-outbound-http-and-ssrf.md)):

- The scheme is HTTPS, or HTTP for a host in the second list. URLs with credentials in them are refused.
- The host matches the allowlist. Cloud metadata names such as `metadata.google.internal` are refused even if listed.
- The name is resolved once, and every address must be ordinary unicast: not loopback, link-local (which covers the 169.254.169.254 metadata address), multicast, unspecified, reserved, "this network" or shared address space, in IPv4 or IPv6, including IPv4 addresses embedded in IPv6 (mapped, 6to4, Teredo, NAT64). Private ranges are allowed, because internal APIs live there; the allowlist is what limits them.
- The connection goes to the checked address, with the host name used for TLS verification and SNI, so a DNS answer that changes between the check and the connection does not help.
- Redirects are never followed, and "next page" links must stay on the same host.

In Compose, only the worker is attached to the `collectors` network, which has outbound access; the API and the database stay on the internal network. To run with no outbound access at all, leave the allowlist empty and remove that network from the worker.

## What every HTTP collector does

The SDK's HTTP layer ([Plugin SDK](../plugins.md#http-collectors)) gives every HTTP collector the same behaviour:

- GET only. APIs that use POST for reads (the AWS JSON APIs) can send only the named read actions the collector declares; anything else is refused before a request is sent.
- Connect and read timeouts (`timeout_seconds`, default 30), and up to three retries with exponential backoff and jitter on connection errors, 429, 500, 502, 503, 504, and 403 with an exhausted rate limit. `Retry-After` in seconds is honoured, up to five minutes.
- Responses must be JSON and at most 20 MB. `max_pages` (default 100) and `max_records` (default 100,000) stop runaway reads.
- Error messages name the host and path, never the query string, headers or secrets.
- `sensitive_fields` in any instance's config adds fields for redaction to drop, on top of the ones the plugin declares.

Secrets are references such as `env://NAME` or `file:///run/secrets/name`, resolved when the collector runs. The token or key never appears in the YAML, the database or the logs.
