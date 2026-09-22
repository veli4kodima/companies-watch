import argparse
from datetime import timedelta

import httpx
import psycopg

from companies_watch.client import (
    CompanyNotFound,
    get_company,
    make_client,
    normalize_number,
)
from companies_watch.config import get_settings
from companies_watch.runlog import (
    RunStats,
    abandon_stale,
    finish_run,
    start_run,
    update_run,
)
from companies_watch.store import (
    add_to_watchlist,
    claim_due,
    mark_failure,
    mark_gone,
    mark_success,
    resume_watch,
    save_company,
)

WATCH_INTERVAL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(hours=1)
LEASE = timedelta(minutes=30)
MAX_FAILS = 5
STALE_AFTER = timedelta(minutes=15)


def cmd_fetch(number: str, dry_run: bool) -> None:
    settings = get_settings()

    with make_client(settings.ch_api_key.get_secret_value()) as client:
        company = get_company(client, normalize_number(number))

    if dry_run:
        print(f"dry-run {company['company_number']} {company['company_name']}")
        return

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn, conn.transaction():
        changed = save_company(conn, company)

    if changed:
        print(f"changed: {', '.join(changed)}")

    print(f"saved {company['company_number']} {company['company_name']}")


def cmd_watch_add(number: str) -> None:
    settings = get_settings()
    normalized = normalize_number(number)

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn, conn.transaction():
        added = add_to_watchlist(conn, normalized)

    print(f"{'added' if added else 'already present'} {normalized}")

def cmd_watch_resume(number: str) -> None:
    settings = get_settings()
    normalized = normalize_number(number)

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn, conn.transaction():
        resumed = resume_watch(conn, normalized)

    print(f"{'resumed' if resumed else 'not paused'} {normalized}")


def cmd_run(limit: int) -> None:
    settings = get_settings()

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn:
        abandoned = abandon_stale(conn, STALE_AFTER)
        if abandoned:
            print(f"marked {abandoned} stale run(s) as abandoned")

        run_id = start_run(conn)
        stats = RunStats()

        try:
            with conn.transaction():
                numbers = claim_due(conn, limit, LEASE)
                stats.taken = len(numbers)
                update_run(conn, run_id, stats)

            if not numbers:
                print("nothing due")
            else:
                with make_client(settings.ch_api_key.get_secret_value()) as client:
                    for number in numbers:
                        try:
                            company = get_company(client, number)
                        except CompanyNotFound:
                            with conn.transaction():
                                mark_gone(conn, number)
                                stats.gone += 1
                                update_run(conn, run_id, stats)
                            print(f"gone {number}")
                            continue
                        except httpx.HTTPError as exc:
                            with conn.transaction():
                                paused = mark_failure(
                                    conn, number, RETRY_INTERVAL, MAX_FAILS
                                )
                                stats.failed += 1
                                update_run(conn, run_id, stats)
                            print(
                                f"failed {number}: {exc!r}"
                                f"{' -> paused' if paused else ''}"
                            )
                            continue

                        with conn.transaction():
                            changed = save_company(conn, company)
                            mark_success(conn, number, WATCH_INTERVAL)
                            stats.ok += 1
                            if changed:
                                stats.changed += 1
                            update_run(conn, run_id, stats)
                        if changed:
                            print(f"changed {number}: {', '.join(changed)}")
        except BaseException as exc:
            finish_run(conn, run_id, stats, "error", repr(exc))
            raise

        finish_run(conn, run_id, stats, "completed")
        print(
            f"run #{run_id} finished: {stats.ok} ok, {stats.failed} failed, "
            f"{stats.gone} gone, {stats.changed} changed, {stats.taken} claimed"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="companies-watch")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch one company and store it")
    fetch.add_argument("number", help="company number, e.g. 00000006")
    fetch.add_argument("--dry-run", action="store_true", help="do not write to database")

    watch = sub.add_parser("watch", help="manage the watchlist")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)
    watch_add = watch_sub.add_parser("add", help="add a company to the watchlist")
    watch_add.add_argument("number")
    watch_resume = watch_sub.add_parser("resume", help="unpause a company")
    watch_resume.add_argument("number")

    run = sub.add_parser("run", help="process due companies")
    run.add_argument("--limit", type=int, default=50)

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args.number, args.dry_run)
    elif args.command == "watch" and args.watch_command == "add":
        cmd_watch_add(args.number)
    elif args.command == "watch" and args.watch_command == "resume":
        cmd_watch_resume(args.number)
    elif args.command == "run":
        cmd_run(args.limit)