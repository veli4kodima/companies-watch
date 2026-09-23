from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Literal

from psycopg import Connection
from psycopg.rows import TupleRow


@dataclass
class RunStats:
    taken: int = 0
    ok: int = 0
    failed: int = 0
    gone: int = 0
    changed: int = 0
    retries: int = 0


def abandon_stale(conn: Connection[TupleRow], stale_after: timedelta) -> int:
    cur = conn.execute(
        """
        update refresh_log
        set status        = 'abandoned',
            finished_at   = heartbeat_at,
            error_message = 'heartbeat lost'
        where status = 'running'
          and heartbeat_at < now() - %(stale)s
        """,
        {"stale": stale_after},
    )
    return cur.rowcount


def start_run(conn: Connection[TupleRow]) -> int:
    row = conn.execute("insert into refresh_log default values returning id").fetchone()
    assert row is not None
    return int(row[0])


def update_run(conn: Connection[TupleRow], run_id: int, stats: RunStats) -> None:
    conn.execute(
        """
        update refresh_log
        set heartbeat_at  = now(),
            taken_count   = %(taken)s,
            ok_count      = %(ok)s,
            failed_count  = %(failed)s,
            gone_count    = %(gone)s,
            changed_count = %(changed)s,
            retry_count   = %(retries)s
        where id = %(id)s
          and status = 'running'
        """,
        {"id": run_id, **asdict(stats)},
    )


def finish_run(
    conn: Connection[TupleRow],
    run_id: int,
    stats: RunStats,
    status: Literal["completed", "error"],
    error: str | None = None,
) -> None:
    with conn.transaction():
        update_run(conn, run_id, stats)
        conn.execute(
            """
            update refresh_log
            set status        = %(status)s,
                finished_at   = now(),
                error_message = %(error)s
            where id = %(id)s
              and status = 'running'
            """,
            {"id": run_id, "status": status, "error": error},
        )
