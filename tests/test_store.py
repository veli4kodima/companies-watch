from datetime import timedelta
from typing import Any

import psycopg
from psycopg.rows import TupleRow

from companies_watch.store import (
    add_to_watchlist,
    claim_due,
    import_watchlist,
    mark_failure,
    mark_gone,
    mark_success,
    save_company,
)

Conn = psycopg.Connection[TupleRow]
LEASE = timedelta(minutes=30)
RETRY = timedelta(hours=1)
DAY = timedelta(hours=24)


def company(number: str = "00000006", **fields: Any) -> dict[str, Any]:
    return {
        "company_number": number,
        "company_name": "ACME LTD",
        "company_status": "active",
        "etag": "e1",
        **fields,
    }


def scalar(conn: Conn, query: str, *params: Any) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


# --- save_company: change detection and idempotency ---


def test_first_save_is_not_a_change(conn: Conn) -> None:
    assert save_company(conn, company()) == []
    assert scalar(conn, "select count(*) from companies") == 1
    assert scalar(conn, "select count(*) from company_changes") == 0


def test_same_etag_is_skipped(conn: Conn) -> None:
    save_company(conn, company())
    assert save_company(conn, company(company_name="IGNORED")) == []
    assert scalar(conn, "select company_name from companies") == "ACME LTD"


def test_change_is_recorded_once(conn: Conn) -> None:
    save_company(conn, company())
    changed = company(company_status="dissolved", etag="e2")

    assert save_company(conn, changed) == ["company_status"]
    assert save_company(conn, changed) == []

    row = conn.execute(
        "select field, old_value, new_value from company_changes"
    ).fetchall()
    assert row == [("company_status", "active", "dissolved")]


def test_missing_old_value_is_sql_null(conn: Conn) -> None:
    save_company(conn, company())
    save_company(conn, company(date_of_cessation="2026-09-01", etag="e2"))
    assert scalar(conn, "select old_value is null from company_changes") is True


# --- watchlist import ---


def test_import_skips_existing_and_duplicates(conn: Conn) -> None:
    assert import_watchlist(conn, ["00000001", "00000002"]) == 2
    assert import_watchlist(conn, ["00000002", "00000003", "00000003"]) == 1
    assert scalar(conn, "select count(*) from watchlist") == 3


def test_import_spreads_checks_over_a_day(conn: Conn) -> None:
    numbers = [f"{n:08d}" for n in range(1, 501)]
    import_watchlist(conn, numbers)
    assert (
        scalar(
            conn,
            "select bool_and(next_check_at between now() and now() + interval '1 day')"
            " from watchlist",
        )
        is True
    )
    hours = scalar(
        conn, "select count(distinct date_trunc('hour', next_check_at)) from watchlist"
    )
    assert hours >= 20


# --- queue: failures, pause, gone ---


def test_autopause_on_fifth_failure(conn: Conn) -> None:
    add_to_watchlist(conn, "00000006")
    results = [mark_failure(conn, "00000006", RETRY, 5) for _ in range(5)]
    assert results == [False, False, False, False, True]
    assert scalar(conn, "select fail_count from watchlist") == 5


def test_success_resets_failures(conn: Conn) -> None:
    add_to_watchlist(conn, "00000006")
    for _ in range(3):
        mark_failure(conn, "00000006", RETRY, 5)
    mark_success(conn, "00000006", DAY)
    assert scalar(conn, "select fail_count from watchlist") == 0


def test_gone_company_is_not_claimed(conn: Conn) -> None:
    add_to_watchlist(conn, "00000006")
    mark_gone(conn, "00000006")
    assert claim_due(conn, 10, LEASE) == []


def test_paused_company_is_not_claimed(conn: Conn) -> None:
    add_to_watchlist(conn, "00000006")
    for _ in range(5):
        mark_failure(conn, "00000006", timedelta(0), 5)
    assert claim_due(conn, 10, LEASE) == []


# --- queue: lease and parallel runs ---


def test_lease_hides_claimed_companies(conn: Conn) -> None:
    add_to_watchlist(conn, "00000006")
    assert claim_due(conn, 10, LEASE) == ["00000006"]
    assert claim_due(conn, 10, LEASE) == []


def test_parallel_claims_do_not_overlap(conn: Conn, test_db_url: str) -> None:
    numbers = [f"{n:08d}" for n in range(1, 6)]
    for number in numbers:
        add_to_watchlist(conn, number)

    with psycopg.connect(test_db_url, autocommit=True) as other, conn.transaction():
        first = claim_due(conn, 3, LEASE)
        second = claim_due(other, 10, LEASE)

    assert len(first) == 3
    assert sorted(first + second) == numbers
