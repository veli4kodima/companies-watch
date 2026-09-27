# companies-watch

[![CI](https://github.com/veli4kodima/companies-watch/actions/workflows/ci.yml/badge.svg)](https://github.com/veli4kodima/companies-watch/actions/workflows/ci.yml)

A small, production-shaped data pipeline that watches a list of UK companies through the
[Companies House API](https://developer.company-information.service.gov.uk/), stores their
current state in PostgreSQL and records **what changed and when**.

It runs unattended on a VPS: an hourly cron job, external heartbeat monitoring, and a nightly
encrypted backup that is verified end to end and can be restored into a clean database with a
row-count check.

The point is not the data source. The point is the boring parts that make a pipeline survive in
production: a self-balancing queue, idempotent writes, retries that respect rate limits,
automatic pausing of broken entities, a run log that detects silently dead runs, and backups that
have actually been restored.

---

## Architecture

```mermaid
flowchart LR
    cron["cron, hourly at :07"] --> wrap["bin/cron-run.sh"]
    wrap -->|"ping /start and /exit-code"| hc["healthchecks.io"]
    wrap --> run["companies-watch run"]

    run -->|"claim due batch: skip locked + lease"| wl[("watchlist")]
    run -->|"GET /company/:number, retries, 429"| api["Companies House API"]
    run -->|"upsert + field diff"| co[("companies")]
    run --> cc[("company_changes")]
    run -->|"heartbeat + counters"| rl[("refresh_log")]

    nightly["cron, daily at 03:17"] --> bk["bin/backup.sh"]
    bk -->|"pg_dump, age, upload, verify"| b2[("Backblaze B2")]
    bk -->|"ping /start and /exit-code"| hc
```

| Table | Role |
|---|---|
| `watchlist` | State of **our process**: when each company is due, failure count, pause, gone flag |
| `companies` | Latest snapshot of **the source**: key columns plus the raw JSON response |
| `company_changes` | One row per changed field: old value, new value, when it was detected |
| `refresh_log` | One row per run: status, heartbeat, counters, error text |

`watchlist` and `companies` are deliberately not linked by a foreign key: a number enters the
queue before it has ever been fetched successfully, and it may never be.

## How it works

**Self-balancing queue.** The queue does not store an order, it stores `next_check_at`. A run
takes the earliest due companies, a success moves a company 24 hours ahead, a failure one hour
ahead. Bulk imports spread `next_check_at` randomly over a day, so the hourly load stays flat
(301 companies ≈ 12–13 per run).

**Safe parallel runs.** A batch is claimed with `FOR UPDATE SKIP LOCKED` and leased by moving
`next_check_at` forward in the same transaction. Two overlapping runs take different companies;
if a process dies, its companies return to the queue when the lease expires. No `flock` needed.

**Short transactions.** The claim commits before the first HTTP request, and each company is
written in its own transaction together with the run counters. A slow API never holds a
transaction open.

**Change detection.** Tracked fields (`company_name`, `company_status`,
`registered_office_address`, `sic_codes`, `date_of_cessation`) are compared against the stored
snapshot. Each difference becomes one row in `company_changes`. An unchanged `etag` skips the
comparison entirely, so re-running the same window writes nothing.

**Failures are classified.**

- Timeouts, connection errors and 5xx: retried with exponential backoff (1 / 2 / 4 s plus jitter).
- 429: waits exactly as long as `Retry-After` says (seconds or HTTP date); gives up if the server
  asks for more than 5 minutes and leaves the company for the next run.
- Other 4xx: not retried.
- 404: not a failure. The company is marked `gone`, kept, and no longer polled.
- Five consecutive failures: the company is paused automatically with a reason.

**Run log with heartbeat.** Every run updates `heartbeat_at` after each company. A run whose
heartbeat is older than 15 minutes is considered dead; the next run marks it `abandoned`. A dead
run is detected by a stale heartbeat, not by a guess about how long a run should take.

## Operations

| What | How |
|---|---|
| Host | Ubuntu 24.04 VPS, PostgreSQL 16 in Docker bound to `127.0.0.1`, app runs natively via `uv` |
| Schedule | `7 * * * *` → `bin/cron-run.sh` (run), `17 3 * * *` → `bin/backup.sh` (backup) |
| Logs | stderr → `systemd-cat` → journald |
| Monitoring | Two healthchecks.io checks. The shell wrapper pings `/start` and then `/<exit code>`, so a run that never starts, hangs or fails raises an alert. Heartbeats come from shell, not Python: if Python cannot start, the check still goes red |
| Backup | `pg_dump -Fc` → integrity check with `pg_restore --list` → encrypted with [age](https://age-encryption.org) → uploaded to Backblaze B2 → **downloaded back** and compared by size and SHA-256. A row-count manifest is stored next to it. Retention: 30 days via bucket lifecycle rules, so the server cannot delete old backups |
| Restore | `bin/restore.sh <identity-file> [backup-name\|latest]` verifies the checksum, decrypts, restores into a throwaway `postgres:16` container and compares row counts with the manifest. The drill has been run against production backups |
| Secrets | `.env` with mode 600, owned by an unprivileged service user that is not in the `docker` group. The server holds only the age **public** key; backups cannot be decrypted there |

### Exit codes

Designed for monitoring: every code means one thing.

| Code | Meaning |
|---|---|
| 0 | Success (including "nothing due") |
| 1 | Every company taken in this run failed |
| 2 | Usage error: missing configuration, invalid company number, bad arguments |
| 3 | Database unavailable |
| 4 | Database error (schema, query) |
| 5 | API error outside a run (`fetch`, `discover`) |
| 130 | Interrupted |

### Status

`companies-watch status` prints the state of the system in plain words, including runs that are
still marked `running` and whether their heartbeat is stale:

```text
Last run      #95 completed, started 18m 19s ago, took 0s
              taken 13, ok 13, failed 0, gone 0, changed 0
Last success  18m 19s ago
Queue         301 watched, 17 due, next check now
              paused 0, gone 0
Changes 24h   0 fields in 0 companies
```

Logs go to stderr and only `status` writes to stdout, so `companies-watch status > report.txt`
produces a clean file.

## Edge cases

| Case | Behaviour | Covered by |
|---|---|---|
| 429 Too Many Requests | Wait for `Retry-After`, continue with the same company | `test_retry.py` |
| `Retry-After` too long | Give up on this company, it returns next run | `test_retry.py` |
| Timeout or 5xx | Backoff and retry, then count as a failure | `test_retry.py` |
| Same company twice in one input | One row | `test_store.py`, `test_import.py` |
| Company renamed, same number | Same entity, name change recorded | `test_changes.py` |
| Company disappears (404) | Marked `gone`, not deleted, not a failure | `test_store.py` |
| Company keeps failing | Paused after 5 failures, `watch resume` clears it | `test_store.py` |
| Same window processed twice | No duplicate changes | `test_store.py` |
| Two runs at the same time | Disjoint batches | `test_store.py` (two real connections) |
| Process killed mid-run | Lease returns companies; run marked `abandoned` | `test_status.py` + manual drill |
| Run never happened | healthchecks.io alert | operations |
| Corrupted or truncated backup | Checksum and size mismatch against the downloaded copy | `bin/backup.sh` |
| Backup that cannot be restored | Restore drill with row-count comparison | `bin/restore.sh` |
| Garbage company number (`../../etc`, empty) | Rejected before any request | `test_client.py` |

Tests run against a real PostgreSQL (created and migrated per session), not mocks. Tests that
need the database are skipped, not failed, when it is not available.

## Design decisions

- **Plain SQL with psycopg 3, no ORM.** Queue semantics (`SKIP LOCKED`, partial indexes,
  `ON CONFLICT`, `RETURNING`) are the core of the system and are easier to reason about as SQL.
- **Own migration runner** instead of Alembic: numbered `.sql` files, each in its own
  transaction (DDL is transactional in PostgreSQL), protected by `pg_advisory_lock`. No
  down-migrations; mistakes are fixed forward.
- **`autocommit=True` plus explicit transactions**, so a nested transaction block is a real
  transaction and not an accidental savepoint.
- **Partial index** on the queue condition (`paused_at is null and gone_at is null`) so it does
  not grow with paused and gone companies.
- **Named CHECK constraints** everywhere (run status vs `finished_at`, counters consistency,
  pause and gone mutually exclusive) so a violation says which rule was broken.
- **Hourly cron, daily cadence.** Daily cadence is enforced by the queue; the hourly cron picks up
  whatever is due, including 1-hour retries. A daily cron at a fixed time would silently turn
  "every day" into "every other day" as due times drift by seconds.
- **Commands separated from CLI parsing.** `commands.py` knows nothing about `argparse`;
  `cli.py` maps exceptions to exit codes.

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, a free
[Companies House API key](https://developer.company-information.service.gov.uk/).

```bash
git clone https://github.com/veli4kodima/companies-watch.git
cd companies-watch
cp .env.example .env            # set CH_API_KEY and DATABASE_URL
docker compose up -d            # PostgreSQL 16 on 127.0.0.1:5432
uv sync
uv run companies-watch migrate
uv run companies-watch watch add 00000006
uv run companies-watch run
uv run companies-watch status
```

Local `DATABASE_URL`: `postgresql://app:app@127.0.0.1:5432/companies_watch`.

### Commands

| Command | What it does |
|---|---|
| `migrate` | Apply pending SQL migrations |
| `fetch <number> [--dry-run]` | Fetch one company now and store it |
| `watch add <number>` | Add one company, due immediately |
| `watch import <file\|->` | Bulk add numbers from a file or stdin; duplicates and garbage are skipped |
| `watch resume <number>` | Clear pause or gone flag |
| `discover [--status] [--sic ...] [--from] [--to] [--size]` | Companies House advanced search; prints numbers to stdout |
| `run [--limit N]` | Process due companies |
| `status` | Human-readable system state |

`discover` and `watch import` compose:

```bash
companies-watch discover --sic 62012 --status active --from 2025-09-26 --size 250 > seeds.txt
companies-watch watch import seeds.txt
```

### Development

```bash
uv run ruff format
uv run ruff check
uv run mypy          # strict
uv run pytest -v
```

CI runs the same four steps on every push, with PostgreSQL as a service container.

## Project layout

```text
src/companies_watch/
    cli.py          argument parsing, exit codes
    commands.py     command implementations
    client.py       Companies House HTTP client, number normalisation
    retry.py        backoff, 429 / Retry-After handling
    store.py        queue and persistence (SQL)
    changes.py      field-level diff
    runlog.py       refresh_log: heartbeat, counters, abandoned runs
    status.py       status queries and rendering
    migrate.py      migration runner
    config.py       settings from environment
    logs.py         logging setup
migrations/         0001–0005, plain SQL
bin/                cron-run.sh, backup.sh, restore.sh, row-counts.sql
tests/
```

## Known limitations

- A response with an unexpected shape (for example, a missing `company_name`) currently fails the
  whole run instead of that one company.
- The backup row-count manifest is taken right after `pg_dump`, not in the same snapshot. A run
  writing in between would make counts differ. Backups run at 03:17 while runs start at :07 and
  take seconds, so this is accepted, not guaranteed.
- `refresh_log` grows by one row per run (about 9,000 rows a year) and has no retention policy yet.
- Timestamps are omitted from log lines when stderr is not a terminal (journald adds its own), so
  redirecting stderr to a file loses them.
- A lookback window is not needed for this source: companies are polled by number, not selected
  by date. It becomes relevant once filing history is added.