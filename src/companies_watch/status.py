from dataclasses import dataclass
from datetime import timedelta

from psycopg import Connection
from psycopg.rows import TupleRow, class_row

LAST_RUN_SQL = """
    select id,
           status,
           now() - started_at                          as started_ago,
           coalesce(finished_at, now()) - started_at   as duration,
           now() - heartbeat_at                        as heartbeat_age,
           taken_count,
           ok_count,
           failed_count,
           gone_count,
           changed_count,
           error_message
    from refresh_log
    order by started_at desc
    limit 1
"""

RUNNING_SQL = """
    select id,
           now() - started_at   as started_ago,
           now() - heartbeat_at as heartbeat_age,
           taken_count,
           ok_count
    from refresh_log
    where status = 'running'
    order by started_at
"""

LAST_COMPLETED_SQL = """
    select now() - max(finished_at)
    from refresh_log
    where status = 'completed'
"""

QUEUE_SQL = """
    select count(*)                                                    as total,
           count(*) filter (where paused_at is null
                              and gone_at is null
                              and next_check_at <= now())              as due,
           count(*) filter (where paused_at is not null)               as paused,
           count(*) filter (where gone_at is not null)                 as gone,
           min(next_check_at) filter (where paused_at is null
                                        and gone_at is null) - now()   as next_check_in
    from watchlist
"""

PAUSED_SQL = """
    select company_number,
           now() - paused_at as paused_ago,
           fail_count,
           pause_reason
    from watchlist
    where paused_at is not null
    order by paused_at
"""

CHANGES_SQL = """
    select count(*), count(distinct company_number)
    from company_changes
    where detected_at > now() - interval '24 hours'
"""


@dataclass
class LastRun:
    id: int
    status: str
    started_ago: timedelta
    duration: timedelta
    heartbeat_age: timedelta
    taken_count: int
    ok_count: int
    failed_count: int
    gone_count: int
    changed_count: int
    error_message: str | None

@dataclass
class RunningRun:
    id: int
    started_ago: timedelta
    heartbeat_age: timedelta
    taken_count: int
    ok_count: int


@dataclass
class QueueSummary:
    total: int
    due: int
    paused: int
    gone: int
    next_check_in: timedelta | None


@dataclass
class PausedCompany:
    company_number: str
    paused_ago: timedelta
    fail_count: int
    pause_reason: str | None


@dataclass
class Status:
    last_run: LastRun | None
    running: list[RunningRun]
    last_completed_ago: timedelta | None
    queue: QueueSummary
    paused: list[PausedCompany]
    changes_24h: int
    changed_companies_24h: int


def load_status(conn: Connection[TupleRow]) -> Status:
    with conn.cursor(row_factory=class_row(LastRun)) as cur:
        last_run = cur.execute(LAST_RUN_SQL).fetchone()

    with conn.cursor(row_factory=class_row(RunningRun)) as cur:
        running = cur.execute(RUNNING_SQL).fetchall()

    with conn.cursor(row_factory=class_row(QueueSummary)) as cur:
        queue = cur.execute(QUEUE_SQL).fetchone()
    assert queue is not None

    with conn.cursor(row_factory=class_row(PausedCompany)) as cur:
        paused = cur.execute(PAUSED_SQL).fetchall()

    row = conn.execute(LAST_COMPLETED_SQL).fetchone()
    assert row is not None
    last_completed_ago: timedelta | None = row[0]

    row = conn.execute(CHANGES_SQL).fetchone()
    assert row is not None

    return Status(
        last_run=last_run,
        running=running,
        last_completed_ago=last_completed_ago,
        queue=queue,
        paused=paused,
        changes_24h=int(row[0]),
        changed_companies_24h=int(row[1]),
    )


def fmt_duration(td: timedelta) -> str:
    seconds = int(td.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def render(status: Status, stale_after: timedelta) -> str:
    lines: list[str] = []

    run = status.last_run
    if run is None:
        lines.append("Last run      never")
    else:
        head = (
            f"Last run      #{run.id} {run.status}, "
            f"started {fmt_duration(run.started_ago)} ago, "
            f"took {fmt_duration(run.duration)}"
        )
        lines.append(head)
        lines.append(
            f"              taken {run.taken_count}, ok {run.ok_count}, "
            f"failed {run.failed_count}, gone {run.gone_count}, "
            f"changed {run.changed_count}"
        )
        if run.status == "running":
            lines.append(
                f"              heartbeat {fmt_duration(run.heartbeat_age)} ago"
            )
            if run.heartbeat_age > stale_after:
                lines.append(
                    "              !! STALE: will be marked abandoned on next run"
                )
        if run.error_message:
            lines.append(f"              error: {run.error_message}")

        for r in status.running:
            mark = "  !! STALE" if r.heartbeat_age > stale_after else ""
            lines.append(
                f"Running       #{r.id} started {fmt_duration(r.started_ago)} ago, "
                f"heartbeat {fmt_duration(r.heartbeat_age)} ago, "
                f"{r.ok_count}/{r.taken_count} done{mark}"
            )

    if status.last_completed_ago is None:
        lines.append("Last success  never")
    else:
        lines.append(
            f"Last success  {fmt_duration(status.last_completed_ago)} ago"
        )

    q = status.queue
    if q.next_check_in is None:
        next_check = "nothing scheduled"
    elif q.next_check_in <= timedelta(0):
        next_check = "next check now"
    else:
        next_check = f"next check in {fmt_duration(q.next_check_in)}"
    lines.append(f"Queue         {q.total} watched, {q.due} due, {next_check}")
    lines.append(f"              paused {q.paused}, gone {q.gone}")

    lines.append(
        f"Changes 24h   {status.changes_24h} fields "
        f"in {status.changed_companies_24h} companies"
    )

    if status.paused:
        lines.append("")
        lines.append("Paused:")
        for p in status.paused:
            lines.append(
                f"  {p.company_number}  {fmt_duration(p.paused_ago)} ago  "
                f"fails {p.fail_count}  {p.pause_reason or ''}"
            )

    return "\n".join(lines)