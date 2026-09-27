# 0012: Hash-chained audit log, roles and auditor access

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief requires an append-only audit log where each entry carries the previous entry's hash, a command that finds the first broken link, events on stdout for the SIEM, and an auditor role that is read-only, time-boxed, scoped to frameworks and periods, with every download logged. Full RBAC and OIDC are M5, but the auditor role is needed now.

## Decision

Audit log:

- `audit_events` holds a sequence number, time, actor, action, target, details, `prev_hash` and `hash`. The hash is SHA-256 over canonical JSON of all the other fields, so editing, deleting, inserting or reordering any entry breaks the chain at that point.
- Appends take a transaction-level advisory lock, so API and worker processes produce one linear chain. The sequence is assigned under the lock, not by the database, so gaps mean deletion.
- A trigger rejects UPDATE, DELETE and TRUNCATE. The application has no code path that needs them.
- Recorded events: sign-in, failed sign-in, throttling and sign-out; each new definition version; each collection run with its record count and masked card numbers; report generation; link creation; every download; auditor grants. Each is also a JSON line on stdout.
- `dsec-metrics audit verify` and `GET /api/audit/verify` (admin only) recompute the chain and name the first broken entry and why.

Roles:

- Users carry roles from the brief's list. Policies in the one policy module: `authenticated`, `staff` (every role but auditor), `author` (admin, metric owner, reviewer) and `admin`. Dashboards and data routes need staff; building reports and links needs author; the audit log needs admin.
- An auditor grant names a user, frameworks, a period and an expiry. An auditor sees a package only when a current grant shares a framework with it and its period lies inside the grant's. Everything else returns 404 (packages) or 403 (staff routes).
- Links are 256-bit tokens, stored as hashes, for one auditor and one package, expiring no later than the grant. The auditor must still sign in; someone else signed in cannot use the link.
- The authorization test walks every route and checks allowed (right role), denied (no session: 401) and forbidden (wrong role: 403) cases.

## Consequences

- Someone with direct database access and the rights to disable triggers can still rewrite history, but cannot do it without breaking the chain, unless they recompute every later hash. Exporting the chain head regularly (for example into the SIEM, which already receives every entry) closes that gap; M5's hardening guide covers it.
- Local accounts with roles are development-only, as before. M5 maps identity provider groups to the same roles.
- The trigger is enforced for the application's database user. A separate owner role for the table is an M5 hardening step.
