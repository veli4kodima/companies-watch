from dataclasses import replace
from datetime import timedelta

import pytest

from companies_watch.status import (
    LastRun,
    PausedCompany,
    QueueSummary,
    RunningRun,
    Status,
    fmt_duration,
    plural,
    render,
)

STALE = timedelta(minutes=15)

BASE_RUN = LastRun(
    id=95,
    status="completed",
    started_ago=timedelta(minutes=18),
    duration=timedelta(seconds=3),
    heartbeat_age=timedelta(minutes=18),
    taken_count=13,
    ok_count=13,
    failed_count=0,
    gone_count=0,
    changed_count=0,
    error_message=None,
)

BASE_STATUS = Status(
    last_run=BASE_RUN,
    running=[],
    last_success_ago=timedelta(minutes=18),
    queue=QueueSummary(
        total=301, due=0, paused=0, gone=0, next_check_in=timedelta(minutes=10)
    ),
    paused=[],
    changes_24h=0,
    changed_companies_24h=0,
)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m 0s"),
        (3599, "59m 59s"),
        (3600, "1h 0m"),
        (86399, "23h 59m"),
        (86400, "1d 0h"),
    ],
)
def test_fmt_duration_boundaries(seconds: int, expected: str) -> None:
    assert fmt_duration(timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "0 fields"), (1, "1 field"), (2, "2 fields")],
)
def test_plural(n: int, expected: str) -> None:
    assert plural(n, "field", "fields") == expected


def test_render_empty_system() -> None:
    status = replace(BASE_STATUS, last_run=None, last_success_ago=None)
    out = render(status, STALE)
    assert "Last run      never" in out
    assert "Last success  never" in out


def test_render_singular_changes() -> None:
    status = replace(BASE_STATUS, changes_24h=1, changed_companies_24h=1)
    assert "1 field in 1 company" in render(status, STALE)


def test_render_stale_running_run() -> None:
    run = replace(BASE_RUN, status="running", heartbeat_age=timedelta(minutes=20))
    running = RunningRun(
        id=95,
        started_ago=timedelta(minutes=25),
        heartbeat_age=timedelta(minutes=20),
        taken_count=13,
        ok_count=4,
    )
    out = render(replace(BASE_STATUS, last_run=run, running=[running]), STALE)
    assert "!! STALE: will be marked abandoned on next run" in out
    assert "4/13 done  !! STALE" in out


def test_render_heartbeat_exactly_at_threshold_is_not_stale() -> None:
    run = replace(BASE_RUN, status="running", heartbeat_age=STALE)
    assert "STALE" not in render(replace(BASE_STATUS, last_run=run), STALE)


def test_render_paused_section() -> None:
    paused = PausedCompany(
        company_number="12345678",
        paused_ago=timedelta(hours=2),
        fail_count=5,
        pause_reason="HTTP 500",
    )
    out = render(replace(BASE_STATUS, paused=[paused]), STALE)
    assert "Paused:" in out
    assert "12345678  2h 0m ago  fails 5  HTTP 500" in out


def test_render_error_message() -> None:
    run = replace(BASE_RUN, status="error", error_message="ReadTimeout()")
    assert "error: ReadTimeout()" in render(replace(BASE_STATUS, last_run=run), STALE)


@pytest.mark.parametrize(
    ("next_check_in", "expected"),
    [
        (None, "nothing scheduled"),
        (timedelta(0), "next check now"),
        (timedelta(seconds=-30), "next check now"),
        (timedelta(minutes=10), "next check in 10m 0s"),
    ],
)
def test_render_next_check(next_check_in: timedelta | None, expected: str) -> None:
    queue = replace(BASE_STATUS.queue, next_check_in=next_check_in)
    assert expected in render(replace(BASE_STATUS, queue=queue), STALE)
