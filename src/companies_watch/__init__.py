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
from companies_watch.store import (
    add_to_watchlist,
    claim_due,
    mark_failure,
    mark_success,
    upsert_company,
)

WATCH_INTERVAL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(hours=1)
LEASE = timedelta(minutes=30)


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
        upsert_company(conn, company)

    print(f"saved {company['company_number']} {company['company_name']}")


def cmd_watch_add(number: str) -> None:
    settings = get_settings()
    normalized = normalize_number(number)

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn, conn.transaction():
        added = add_to_watchlist(conn, normalized)

    print(f"{'added' if added else 'already present'} {normalized}")


def cmd_run(limit: int) -> None:
    settings = get_settings()

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn:
        with conn.transaction():
            numbers = claim_due(conn, limit, LEASE)

        if not numbers:
            print("nothing due")
            return

        ok = 0
        failed = 0
        with make_client(settings.ch_api_key.get_secret_value()) as client:
            for number in numbers:
                try:
                    company = get_company(client, number)
                except (CompanyNotFound, httpx.HTTPError) as exc:
                    with conn.transaction():
                        mark_failure(conn, number, RETRY_INTERVAL)
                    print(f"failed {number}: {exc!r}")
                    failed += 1
                    continue

                with conn.transaction():
                    upsert_company(conn, company)
                    mark_success(conn, number, WATCH_INTERVAL)
                ok += 1

        print(f"run finished: {ok} ok, {failed} failed, {len(numbers)} claimed")


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

    run = sub.add_parser("run", help="process due companies")
    run.add_argument("--limit", type=int, default=50)

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args.number, args.dry_run)
    elif args.command == "watch" and args.watch_command == "add":
        cmd_watch_add(args.number)
    elif args.command == "run":
        cmd_run(args.limit)