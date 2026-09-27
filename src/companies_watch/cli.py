import argparse
import sys
from datetime import date

import httpx
import psycopg
from pydantic import ValidationError

from companies_watch import migrate
from companies_watch.client import BadResponse, CompanyNotFound
from companies_watch.commands import (
    cmd_discover,
    cmd_fetch,
    cmd_run,
    cmd_status,
    cmd_watch_add,
    cmd_watch_import,
    cmd_watch_resume,
)
from companies_watch.logs import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="companies-watch")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch one company and store it")
    fetch.add_argument("number", help="company number, e.g. 00000006")
    fetch.add_argument(
        "--dry-run", action="store_true", help="do not write to database"
    )

    watch = sub.add_parser("watch", help="manage the watchlist")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)

    watch_add = watch_sub.add_parser("add", help="add a company to the watchlist")
    watch_add.add_argument("number")

    watch_import = watch_sub.add_parser(
        "import", help="add numbers from a file ('-' for stdin)"
    )
    watch_import.add_argument("path")

    watch_resume = watch_sub.add_parser("resume", help="unpause a company")
    watch_resume.add_argument("number")

    run = sub.add_parser("run", help="process due companies")
    run.add_argument("--limit", type=int, default=50)

    sub.add_parser("status", help="show pipeline state")
    sub.add_parser("migrate", help="apply pending migrations")

    discover = sub.add_parser(
        "discover", help="search Companies House, print numbers to stdout"
    )
    discover.add_argument("--status")
    discover.add_argument("--sic", action="append", dest="sic_codes")
    discover.add_argument("--from", dest="incorporated_from", type=date.fromisoformat)
    discover.add_argument("--to", dest="incorporated_to", type=date.fromisoformat)
    discover.add_argument("--size", type=int, default=100)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging()

    try:
        if args.command == "fetch":
            cmd_fetch(args.number, args.dry_run)
        elif args.command == "watch":
            if args.watch_command == "add":
                cmd_watch_add(args.number)
            elif args.watch_command == "import":
                return cmd_watch_import(args.path)
            elif args.watch_command == "resume":
                cmd_watch_resume(args.number)
            else:
                parser.error(f"unknown watch command: {args.watch_command}")
        elif args.command == "run":
            return cmd_run(args.limit)
        elif args.command == "status":
            cmd_status()
        elif args.command == "migrate":
            migrate.main()
        elif args.command == "discover":
            return cmd_discover(
                status=args.status,
                sic_codes=args.sic_codes,
                incorporated_from=args.incorporated_from,
                incorporated_to=args.incorporated_to,
                size=args.size,
            )
        else:
            parser.error(f"unknown command: {args.command}")
    except ValidationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except psycopg.OperationalError as exc:
        print(f"database unavailable: {exc}", file=sys.stderr)
        return 3
    except psycopg.Error as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 4
    except CompanyNotFound as exc:
        print(f"company not found: {exc}", file=sys.stderr)
        return 5
    except BadResponse as exc:
        print(f"bad api response: {exc}", file=sys.stderr)
        return 5
    except httpx.HTTPError as exc:
        print(f"api error: {exc}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0
