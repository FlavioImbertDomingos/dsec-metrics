# 0013: Outbound HTTP for collectors and SSRF protection

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

M4 adds collectors that call other systems: AWS, Vault, Jira, ServiceNow, GitHub, and any JSON API through `rest`. The `rest` collector takes a base URL from configuration, so anyone who can change content can point the worker at an address of their choice. Without controls, that is server-side request forgery: the worker could be made to read a cloud metadata service, a loopback admin port, or an internal system nobody meant to expose.

The brief requires an admin-managed host allowlist, blocked link-local, loopback and metadata addresses, and no outbound calls the operator has not configured. It also requires timeouts, retries, pagination and rate-limit handling in the SDK rather than in each plugin, and collectors that cannot write.

The brief names no HTTP client library for runtime use.

## Decision

One HTTP client in the SDK (`plugins/sdk/http.py`), used by every HTTP collector, built on the standard library (`http.client`, `ssl`, `socket`).

Outbound policy (`plugins/sdk/ssrf.py`), applied to every request including each page:

- Allowlist from `DSEC_COLLECTOR_ALLOWED_HOSTS`: exact names or `*.suffix`. Empty allows nothing, so a fresh install makes no outbound calls.
- HTTPS only, except hosts in `DSEC_COLLECTOR_ALLOW_HTTP_HOSTS`. No credentials in URLs.
- Metadata names refused by name. The host is resolved once; every address must pass: no loopback, link-local, multicast, unspecified, reserved, `0.0.0.0/8`, `100.64.0.0/10`, IPv6 site-local, or known metadata addresses, and the same checks on IPv4 addresses embedded in IPv6 (mapped, 6to4, Teredo, NAT64). Private ranges pass, because internal APIs live there; the allowlist limits which names reach them.
- The connection goes to the checked address. TLS is verified against the host name, which is also sent as SNI and in the `Host` header. This closes the DNS-rebinding gap between checking and connecting.
- Redirects are not followed. Pagination links must stay on the host of the first request.

Read-only by construction: the client sends GET, and POST only for read actions a collector declares by name (AWS JSON APIs use POST for reads). Any other method raises before a request is sent.

Reliability: timeouts, retries with exponential backoff and jitter on connection errors, 429, 500, 502, 503, 504 and 403 with `x-ratelimit-remaining: 0`, `Retry-After` in seconds up to five minutes, a 20 MB response limit, JSON only, and page and record limits per instance.

Transports are injectable. Contract tests replay recorded responses through `FixtureTransport`; CI never calls live services.

In Compose, only the worker joins a network with outbound access (`collectors`); the API and database stay on the internal network.

## Alternatives considered

- httpx with a custom transport. Capable, but it is a new runtime dependency the brief does not name, and pinning connections to checked addresses means working around its connection pool and resolver.
- An egress proxy (for example Smokescreen) as the only control. Good defence in depth, and operators can still add one, but the application must enforce the rule itself so an install without a proxy is safe.
- Resolving again at connect time and comparing. Leaves a window and doubles DNS traffic; connecting to the checked address is simpler and exact.

## Consequences

- A collector cannot reach anything the operator has not named, and cannot reach metadata or loopback addresses even if named.
- Operators must list every API host. The collector pages list the hosts each one needs.
- HTTP/1.1 only, one connection per request. Collector volumes are small (a few thousand requests a day at most), so connection reuse is not needed.
- Proxies are not supported yet. An operator who needs one can run the worker on a network that routes through a transparent proxy; explicit proxy support can come later as a setting.
