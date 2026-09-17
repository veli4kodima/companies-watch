from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb


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