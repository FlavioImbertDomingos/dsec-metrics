# 0007: Worker scheduler without APScheduler

- Status: accepted, pending maintainer confirmation because the brief names APScheduler
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief says "APScheduler in the worker, Postgres job store", and review chose APScheduler 4 (4.0.0a6, a pre-release). The M1 build used its SQLAlchemy data store with the JSON serializer, because the default serializer is pickle and the brief forbids pickle.

`pip-audit` then failed on PYSEC-2026-282 (CVE-2026-31072, GHSA-9cfw-f3f9-7mm7). APScheduler's JSON and CBOR serializers import modules and instantiate classes named in the stored data, and call `__setstate__` on them. Every released version is affected and there is no fixed release. In our deployment, anyone who can write to the job store tables could run code in the worker, which holds collector credentials. APScheduler 3 stores jobs with pickle, which is worse.

The brief forbids weakening a CI gate to get a build through, and the finding is real, so a suppression is not appropriate.

## Decision

Replace APScheduler with a small scheduler that stores no executable references.

- `dsec_metrics.core.cron` parses five-field cron expressions in UTC: numbers, `*`, ranges, steps and lists. Names, `L`, `W`, `#` and `?` are rejected. When both day fields are restricted, either one matching is enough, as in classic cron. Expressions that never fire, such as `0 0 30 2 *`, are rejected. Hypothesis checks `next_after` against an independent minute-by-minute oracle.
- A `schedules` table holds one row per recurring job: `id`, `job` (a key into the fixed `JOBS` dict in `worker/jobs.py`), `args` (a flat JSON object of strings), `cron`, `next_run_at` and the last run's times, status and error.
- On start, the worker syncs the table with `content/collectors/`: new or changed schedules get a fresh `next_run_at`, unchanged ones keep theirs, removed ones are deleted.
- A background thread polls every `DSEC_SCHEDULER_POLL_SECONDS` (default 30). It claims the most overdue row with `SELECT ... FOR UPDATE SKIP LOCKED`, moves `next_run_at` past now in the same transaction, commits, runs the job and records the outcome. Two worker replicas never run the same fire time, and fire times missed while the worker was down run once, not once per missed slot.
- A row with an unknown job name, a broken expression or non-string arguments is marked failed and not run. Job errors are recorded by exception type only, so collector error text cannot leak into the table.

## Consequences

- APScheduler, sniffio, attrs, tenacity and tzlocal leave the lock file, and no stored data is ever turned into objects.
- We own about 150 lines of scheduling code and its tests. Features we do not have: jitter, per-job time zones, one-off jobs and concurrency limits. Collection runs are daily or slower, so polling every 30 seconds is enough.
- A job that runs longer than its interval is not started twice by one worker, because one thread runs jobs one after another. With several replicas, the next fire time can start on another replica while a slow run continues. Collection runs are idempotent at the measurement level, so the cost is a duplicate collection, not wrong numbers.
- Revisit if upstream ships a serializer that only accepts plain data, or if the scheduler needs features listed above.
