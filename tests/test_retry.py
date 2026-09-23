import httpx
import pytest

from companies_watch.retry import call_with_retry


def make_status_error(
    code: int, headers: dict[str, str] | None = None
) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(code, request=request, headers=headers)
    return httpx.HTTPStatusError("error", request=request, response=response)


class Flaky:
    """Падает заданными исключениями по очереди, потом возвращает 'ok'."""

    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def no_sleep(_: float) -> None:
    pass


def test_retries_then_succeeds() -> None:
    fn = Flaky([httpx.ConnectTimeout("timeout"), make_status_error(503)])
    assert call_with_retry(fn, sleep=no_sleep) == "ok"
    assert fn.calls == 3


def test_gives_up_after_max_retries() -> None:
    fn = Flaky([httpx.ConnectTimeout("timeout") for _ in range(10)])
    with pytest.raises(httpx.ConnectTimeout):
        call_with_retry(fn, sleep=no_sleep)
    assert fn.calls == 4


def test_does_not_retry_4xx() -> None:
    fn = Flaky([make_status_error(400)])
    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(fn, sleep=no_sleep)
    assert fn.calls == 1


class Recorder:
    """Фейковый sleep: не спит, но запоминает длительности."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def test_waits_exactly_retry_after_on_429() -> None:
    fn = Flaky([make_status_error(429, {"Retry-After": "2"})])
    sleep = Recorder()
    assert call_with_retry(fn, sleep=sleep) == "ok"
    assert sleep.delays == [2.0]


def test_uses_base_delay_when_429_has_no_header() -> None:
    fn = Flaky([make_status_error(429)])
    sleep = Recorder()
    assert call_with_retry(fn, sleep=sleep) == "ok"
    assert sleep.delays == [1.0]


def test_gives_up_when_retry_after_too_long() -> None:
    fn = Flaky([make_status_error(429, {"Retry-After": "3600"})])
    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(fn, sleep=no_sleep)
    assert fn.calls == 1
