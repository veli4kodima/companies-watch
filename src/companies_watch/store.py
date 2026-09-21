from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from companies_watch.changes import diff_fields


def upsert_company(conn: psycopg.Connection[TupleRow], data: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into companies (
            company_number, company_name, company_status, etag, raw, fetched_at
        )
        values (%s, %s, %s, %s, %s, %s)
        on conflict (company_number) do update
        set company_name   = excluded.company_name,
            company_status = excluded.company_status,
            etag           = excluded.etag,
            raw            = excluded.raw,
            fetched_at     = excluded.fetched_at
        """,
        (
            data["company_number"],
            data["company_name"],
            data.get("company_status"),
            data.get("etag"),
            Jsonb(data),
            datetime.now(tz=UTC),
        ),
    )

def _jsonb_or_null(value: Any) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def save_company(conn: psycopg.Connection[TupleRow], data: dict[str, Any]) -> list[str]:
    number = data["company_number"]
    row = conn.execute(
        "select raw, etag from companies where company_number = %s for update",
        (number,),
    ).fetchone()

    if row is None:
        upsert_company(conn, data)
        return []

    old_raw, old_etag = row
    if old_etag is not None and old_etag == data.get("etag"):
        return []

    changes = diff_fields(old_raw, data)
    for field, old_value, new_value in changes:
        conn.execute(
            """
            insert into company_changes (company_number, field, old_value, new_value)
            values (%s, %s, %s, %s)
            """,
            (number, field, _jsonb_or_null(old_value), _jsonb_or_null(new_value)),
        )

    upsert_company(conn, data)
    return [field for field, _, _ in changes]

def add_to_watchlist(conn: psycopg.Connection[TupleRow], number: str) -> bool:
    cursor = conn.execute(
        """
        insert into watchlist (company_number)
        values (%s)
        on conflict (company_number) do nothing
        """,
        (number,),
    )
    return cursor.rowcount == 1

def claim_due(
    conn: psycopg.Connection[TupleRow], limit: int, lease: timedelta
) -> list[str]:
    cursor = conn.execute(
        """
        with due as (
            select company_number
            from watchlist
            where paused_at is null
              and gone_at is null
              and next_check_at <= now()
            order by next_check_at
            limit %s
            for update skip locked
        )
        update watchlist w
        set next_check_at = now() + %s
        from due
        where w.company_number = due.company_number
        returning w.company_number
        """,
        (limit, lease),
    )
    return [row[0] for row in cursor]

def mark_success(
    conn: psycopg.Connection[TupleRow], number: str, interval: timedelta
) -> None:
    conn.execute(
        """
        update watchlist
        set last_checked_at = now(),
            next_check_at   = now() + %s,
            fail_count      = 0,
            paused_at       = null,
            pause_reason    = null,
            gone_at         = null
        where company_number = %s
        """,
        (interval, number),
    )

def mark_failure(
    conn: psycopg.Connection[TupleRow],
    number: str,
    retry_in: timedelta,
    max_fails: int,
) -> bool:
    row = conn.execute(
        """
        update watchlist
        set last_checked_at = now(),
            next_check_at   = now() + %(retry_in)s,
            fail_count      = fail_count + 1,
            paused_at       = case when fail_count + 1 >= %(max_fails)s
                                   then now() else paused_at end,
            pause_reason    = case when fail_count + 1 >= %(max_fails)s
                                   then %(reason)s else pause_reason end
        where company_number = %(number)s
        returning paused_at is not null
        """,
        {
            "number": number,
            "retry_in": retry_in,
            "max_fails": max_fails,
            "reason": f"{max_fails} consecutive failures",
        },
    ).fetchone()
    return bool(row and row[0])

def mark_gone(conn: psycopg.Connection[TupleRow], number: str) -> None:
    conn.execute(
        """
        update watchlist
        set gone_at         = now(),
            last_checked_at = now(),
            paused_at       = null,
            pause_reason    = null
        where company_number = %s
        """,
        (number,),
    )

def resume_watch(conn: psycopg.Connection[TupleRow], number: str) -> bool:
    cursor = conn.execute(
        """
            update watchlist
            set paused_at     = null,
                pause_reason  = null,
                gone_at       = null,
                fail_count    = 0,
                next_check_at = now()
            where company_number = %s
              and (paused_at is not null or gone_at is not null)
        """,
        (number,),
    )
    return cursor.rowcount == 1