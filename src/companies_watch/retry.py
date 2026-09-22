import random
import time
from collections.abc import Callable

import httpx

MAX_RETRIES = 3
BASE_DELAY = 1.0


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def call_with_retry[T](
    fn: Callable[[], T],
    on_retry: Callable[[int, Exception, float], None] | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries or not is_retryable(exc):
                raise
            attempt += 1
            delay = base_delay * 2 ** (attempt - 1)
            delay += random.uniform(0, delay * 0.1)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)