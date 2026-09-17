import argparse

import psycopg

from companies_watch.client import get_company, make_client, normalize_number
from companies_watch.config import get_settings
from companies_watch.store import upsert_company


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="companies-watch")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch one company and store it")
    fetch.add_argument("number", help="company number, e.g. 00000006")
    fetch.add_argument("--dry-run", action="store_true", help="do not write to database")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args.number, args.dry_run)