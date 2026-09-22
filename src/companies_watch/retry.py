import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_RETRY_AFTER = 300.0


def parse_retry_after(value: str) -> float | None:
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def retry_after_delay(exc: Exception) -> float | None:
    """Сколько ждать по указанию сервера, или None, если это не 429."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    if exc.response.status_code != 429:
        return None
    header = exc.response.headers.get("retry-after")
    if header is None:
        return BASE_DELAY
    delay = parse_retry_after(header)
    return BASE_DELAY if delay is None else delay


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def call_with_retry[T](
    fn: Callable[[], T],
    on_retry: Callable[[int, Exception, float], None] | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    max_retry_after: float = MAX_RETRY_AFTER,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries or not is_retryable(exc):
                raise

            server_delay = retry_after_delay(exc)
            if server_delay is not None and server_delay > max_retry_after:
                raise

            attempt += 1
            if server_delay is None:
                delay = base_delay * 2 ** (attempt - 1)
                delay += random.uniform(0, delay * 0.1)
            else:
                delay = server_delay

            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)