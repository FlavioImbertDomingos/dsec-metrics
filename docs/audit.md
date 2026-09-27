# Audit log and auditors

## The audit log

Every user and system action that matters to an audit is written to an append-only table, and each entry carries the hash of the one before it. [ADR-0012](adr/0012-audit-log-and-roles.md) explains the design.

Recorded actions:

| Action | When |
| --- | --- |
| `auth.login`, `auth.failed`, `auth.throttled`, `auth.logout` | Sign-in and sign-out |
| `definition.version` | A new version of any definition is stored |
| `collection.run` | A collection finishes or fails, with records and card numbers masked |
| `report.generate` | A package is built |
| `report.link` | An auditor link is created |
| `report.download` | Any package download, by anyone, with the address and the link used |
| `auditor.grant` | An auditor is given access |

Each entry is also written as a JSON line to the process's standard output, with `"event": "audit"`, for your SIEM.

Check the chain:

```sh
docker compose exec api dsec-metrics audit verify
```

It prints `OK` and the number of entries and the head hash, or the first broken entry and why (missing, previous-hash mismatch, or contents changed), and exits with 1. Admins can run the same check from the Audit log screen.

The table rejects updates and deletes through a database trigger. Someone with database administrator rights can still change it, but not without breaking the chain; keep a copy of the head hash outside the database (your SIEM already has every entry) to make a full rewrite detectable too.

## Roles

| Role | Can |
| --- | --- |
| `admin` | Everything, including the audit log |
| `metric_owner`, `reviewer` | Read everything; build reports and auditor links |
| `viewer`, `service` | Read dashboards, metrics, controls and reports |
| `auditor` | Only the audit room: packages a current grant covers, and their own access log |

In development, local accounts get roles with `dsec-metrics dev create-user NAME --role reviewer`. With OIDC (M5), roles come from identity provider groups.

## Giving an auditor access

```sh
docker compose exec api dsec-metrics users grant-auditor qsa \
  --framework pci-dss-4.0.1 --period-start 2026-01-01 --period-end 2026-12-31 --days 30
```

The auditor sees a package when a current grant shares a framework with it and the package's period lies inside the grant's period. When the grant expires, access ends.

To send a specific package, open Reports, choose Auditor link on the package and enter the auditor's username. The link lasts up to 90 days and never beyond the grant, works only for that auditor after they sign in, and is shown once. Every download is in the audit log and in the audit room's access log.
