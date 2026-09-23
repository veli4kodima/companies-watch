import logging
from collections.abc import Callable
from datetime import timedelta
from functools import partial

import httpx
import psycopg

from companies_watch.client import (
    CompanyNotFound,
    get_company,
    make_client,
    normalize_number,
)
from companies_watch.config import get_settings
from companies_watch.retry import call_with_retry
from companies_watch.runlog import (
    RunStats,
    abandon_stale,
    finish_run,
    start_run,
    update_run,
)
from companies_watch.status import load_status, render
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
log = logging.getLogger("companies_watch")


def cmd_fetch(number: str, dry_run: bool) -> None:
    settings = get_settings()

    with make_client(settings.ch_api_key.get_secret_value()) as client:
        company = get_company(client, normalize_number(number))

    if dry_run:
        print(f"dry-run {company['company_number']} {company['company_name']}")
        return

    with (
        psycopg.connect(
            settings.database_url, autocommit=True, connect_timeout=5
        ) as conn,
        conn.transaction(),
    ):
        changed = save_company(conn, company)

    if changed:
        print(f"changed: {', '.join(changed)}")

    print(f"saved {company['company_number']} {company['company_name']}")


def cmd_watch_add(number: str) -> None:
    settings = get_settings()
    normalized = normalize_number(number)

    with (
        psycopg.connect(
            settings.database_url, autocommit=True, connect_timeout=5
        ) as conn,
        conn.transaction(),
    ):
        added = add_to_watchlist(conn, normalized)

    print(f"{'added' if added else 'already present'} {normalized}")


def cmd_watch_resume(number: str) -> None:
    settings = get_settings()
    normalized = normalize_number(number)

    with (
        psycopg.connect(
            settings.database_url, autocommit=True, connect_timeout=5
        ) as conn,
        conn.transaction(),
    ):
        resumed = resume_watch(conn, normalized)

    print(f"{'resumed' if resumed else 'not paused'} {normalized}")


def cmd_run(limit: int) -> int:
    settings = get_settings()

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn:
        abandoned = abandon_stale(conn, STALE_AFTER)
        if abandoned:
            log.warning("marked %d stale run(s) as abandoned", abandoned)

        run_id = start_run(conn)
        stats = RunStats()

        try:
            with conn.transaction():
                numbers = claim_due(conn, limit, LEASE)
                stats.taken = len(numbers)
                update_run(conn, run_id, stats)

            if not numbers:
                log.info("nothing due")
            else:
                with make_client(settings.ch_api_key.get_secret_value()) as client:

                    def make_on_retry(
                        number: str,
                    ) -> Callable[[int, Exception, float], None]:
                        def on_retry(
                            attempt: int, exc: Exception, delay: float
                        ) -> None:
                            stats.retries += 1
                            update_run(conn, run_id, stats)
                            log.warning(
                                "retry %s #%d in %.1fs: %r", number, attempt, delay, exc
                            )

                        return on_retry

                    for number in numbers:
                        try:
                            company = call_with_retry(
                                partial(get_company, client, number),
                                make_on_retry(number),
                            )
                        except CompanyNotFound:
                            with conn.transaction():
                                mark_gone(conn, number)
                                stats.gone += 1
                                update_run(conn, run_id, stats)
                            log.info("gone %s", number)
                            continue
                        except httpx.HTTPError as exc:
                            with conn.transaction():
                                paused = mark_failure(
                                    conn, number, RETRY_INTERVAL, MAX_FAILS
                                )
                                stats.failed += 1
                                update_run(conn, run_id, stats)
                                log.warning(
                                    "failed %s: %r%s",
                                    number,
                                    exc,
                                    " -> paused" if paused else "",
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
                            log.info("changed %s: %s", number, ", ".join(changed))
        except BaseException as exc:
            finish_run(conn, run_id, stats, "error", repr(exc))
            raise

        finish_run(conn, run_id, stats, "completed")
        log.info(
            "run #%d finished: %d ok, %d failed, %d gone, %d changed, %d claimed",
            run_id,
            stats.ok,
            stats.failed,
            stats.gone,
            stats.changed,
            stats.taken,
        )
        if stats.taken > 0 and stats.ok == 0 and stats.gone == 0:
            return 1
        return 0


def cmd_status() -> None:
    settings = get_settings()
    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn:
        status = load_status(conn)
    print(render(status, STALE_AFTER))
