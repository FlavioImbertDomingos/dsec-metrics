# Dashboards and the read API

The web app has one dashboard per audience and a path from any number down to the records it was computed from. [ADR-0009](adr/0009-read-api-and-dashboards.md) explains the design.

## Screens

| Screen | Path | What it shows |
| --- | --- | --- |
| Overview | `/` | One card per audience with status counts, then every red indicator with its owner and action |
| Team operations | `/dashboards/team-operations` | Operational indicators, exceptions by age, past-due findings, certificate expiry, audit request timeliness |
| Management | `/dashboards/management` | Program KPIs as trends against baseline and target |
| Risk committee | `/dashboards/risk-committee` | Key risk indicators with status, owner and action for anything red, and status by business unit |
| Metrics | `/metrics` | The catalog with the latest value of each metric |
| Metric detail | `/metrics/{id}` | Current value, threshold bands, history, breakdown by slice, the definition and its versions |
| Measurement | `/measurements/{id}` | One number with its calculation record, definition version and source batches |
| Batch | `/batches/{sha256}` | Provenance, redaction summary and the redacted records, 50 at a time |
| Controls | `/controls`, `/controls/{id}` | Status rolled up from metrics, requirements, evidence sources, exceptions and findings |
| Exceptions | `/exceptions` | The register with age, expiry calendar and root causes |
| Findings | `/findings` | The findings register, filterable by severity |

Dashboards are defined in `content/dashboards/`; see [the definition language](definitions.md#dashboards).

## Following a number

Every value on screen is a link. Selecting one opens the measurement: the value, its status, the definition version and hash it was computed with, the calculation record (record counts before and after filtering, the formula, intermediate numbers), and the SHA-256 of each input batch. Each batch opens to its collector, version, query, parameters, collection time, redaction summary and records. The hash shown covers the records exactly as displayed, after redaction.

## Filters

The filter bar offers each dimension that some metric on the page is broken down by. Filter state is in the URL, so a filtered view can be bookmarked or shared.

A metric is only broken down by the dimensions in its `group_by`. When a filter does not apply to a metric, the widget says so and shows the overall value. Nothing is shown as filtered when it is not.

## Status

Status is always an icon, a word and a colour: a check for green, a triangle for amber, an octagon for red, and a question mark for unknown. A control's status is the worst status of its metrics, and unknown ranks above green, so a control with an unmeasured metric never reads as fine.

## Charts, tables and printing

Charts use a colour-blind-safe palette (Okabe-Ito) and one y-axis. Target and baseline lines are drawn dashed and kept inside the plotted range. Every chart has a "View as table" toggle with the same values as links. Printing a dashboard (the Print button, or the browser's print command) drops navigation and filters, prints tables in place of charts, and keeps each widget on one page.

## Accessibility

The Playwright suite runs axe-core with the WCAG 2.2 AA rules on every screen in light and dark mode and fails the build on any violation. All navigation works from the keyboard, starting with a skip link. Sort buttons announce their state through `aria-sort`.

## Read API

All routes need a signed-in session and are read-only. Unknown ids return 404 without echoing the id; malformed ids and parameters return 422.

| Route | Parameters |
| --- | --- |
| `GET /api/metrics` | `audience`, `type` |
| `GET /api/metrics/{metric_id}` | |
| `GET /api/metrics/{metric_id}/measurements` | `periods` (1 to 36), dimension filters |
| `GET /api/measurements/{measurement_id}` | |
| `GET /api/batches/{sha256}` | `offset`, `limit` (1 to 200) |
| `GET /api/controls` | |
| `GET /api/controls/{control_id}` | |
| `GET /api/exceptions` | `status`, `control_id`, dimension filters |
| `GET /api/findings` | `status`, `severity`, `control_id`, dimension filters |
| `GET /api/dashboards` | |
| `GET /api/dashboards/{dashboard_id}` | dimension filters |

Dimension filters are `business_unit`, `application`, `environment` and `region`. In development mode the OpenAPI schema is served at `/api/docs`.

## Limits

| Setting | Default | Meaning |
| --- | --- | --- |
| `DSEC_RATE_LIMIT_PER_ADDRESS` | 1200 | Requests a minute from one client address |
| `DSEC_RATE_LIMIT_PER_SESSION` | 600 | Requests a minute with one session |
| `DSEC_MAX_REQUEST_BYTES` | 1048576 | Largest request body the API accepts |

Over the limit, the API answers 429 with `Retry-After`. The first rejection in each window is logged as a `rate_limited` security event.

## Performance

On the 12-month sample dataset, each dashboard call stays under 300 ms at the 95th percentile (`tests/integration/test_read_api.py`) and each dashboard renders in under 1.5 seconds in the browser (`web/e2e/dashboards.spec.ts`).
