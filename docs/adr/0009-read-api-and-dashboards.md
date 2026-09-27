# 0009: Read API, dashboard aggregation and rate limits

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

M2 adds the screens each audience uses and the API behind them. The brief sets three constraints: every number is traceable to its definition, measurement and source batch; dashboard calls stay under 300 ms at p95 on the sample data; and every route has rate and size limits. Business-unit scoping arrives with RBAC in M5, and the read path should not need rework then.

## Decision

Reading:

- The API reads definitions from the `definitions` table (the versions the evaluator used), not from files on disk. The worker syncs definitions at startup, the demo command on each run.
- Dashboards are built from stored measurements only. One request resolves every widget: one query for the latest overall values, one for histories of the slices in use, one for the latest slices, and the registers when a widget needs them. No raw batch is read on the dashboard path except the exceptions register for the aging widget.
- Every number in a response carries its measurement id. The UI links each one to `/measurements/{id}`, which links to the metric definition and to each source batch, which shows its redacted records page by page.
- A dimension filter uses the stored slice that matches it exactly. If a metric is not grouped by the filtered dimension, the response says so (`ignored_filters`, or a widget `note`) and shows the overall value. The UI never shows a number that looks filtered but is not.
- Every query takes a `Scope`. It allows everything until M5, which then changes one function.
- Exceptions and findings come from collector data like everything else. A `register` definition names the source query; the API reads its latest batch and validates each record against the documented fields. The GRC tool remains the system of record.

Limits:

- A middleware counts every request in fixed one-minute windows in an unlogged Postgres table: against the client address (default 1200 a minute) and, when a session cookie is present, against a SHA-256 of the cookie (default 600 a minute). Over the limit returns 429 with `Retry-After`. Being middleware, the limit covers unknown paths too, and a test checks that every route returns 429 once the limit is spent.
- Bodies over 1 MB get 413 and bodies without a length get 411, in the API as well as at the proxy.
- If the counter table cannot be reached, requests go through and a warning is logged. Every route except the health checks needs the database anyway.

Front end:

- A small in-house router over the History API. Filter state lives in the query string, so any view can be shared as a link.
- ECharts draws on canvas with canvas tooltips, so it never writes inline style attributes that the Content Security Policy would block. Each chart is one labelled image with a "View as table" toggle; the table is the printed form.
- Heatmaps are HTML tables of status badges rather than charts, so each cell has an icon, a label and a link.

## Consequences

- The dashboard p95 on the 12-month sample is measured in `tests/integration/test_read_api.py`; the Playwright suite checks a render under 1.5 seconds.
- Rate limiting costs one upsert per request. If that shows up in production profiles, a per-process token bucket can sit in front of it.
- Two browser tabs sharing a session share its budget. Users behind one address (a jump host, a proxy that hides client addresses) share the address budget; raise `DSEC_RATE_LIMIT_PER_ADDRESS` in that case.
- Register records that do not fit the documented fields are counted and skipped, and the count is shown on the register page.
