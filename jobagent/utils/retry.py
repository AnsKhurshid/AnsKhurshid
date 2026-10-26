"""Bounded retries with exponential backoff + jitter, and a simple rate limiter."""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger("jobagent.retry")


class PermanentError(Exception):
    """An error that must not be retried (bad request, 403/404, auth failure, validation error)."""


class TransientError(Exception):
    """An error worth retrying (timeouts, 429, 5xx, connection resets)."""


def retry_call(fn: Callable[[], T], *, max_attempts: int = 3, base_delay: float = 1.0,
               max_delay: float = 30.0, retry_on: tuple[type[BaseException], ...] = (TransientError,),
               sleep: Callable[[float], None] = time.sleep) -> T:
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except PermanentError:
            raise
        except retry_on as exc:
            if attempt >= max_attempts:
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1))
            delay = delay * (0.5 + random.random() / 2)  # jitter in [50%, 100%]
            log.info("transient failure (attempt %d/%d): %s; retrying in %.1fs", attempt, max_attempts, exc, delay)
            sleep(delay)


class RateLimiter:
    """Ensures at least `min_interval` seconds between calls sharing the same key."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep

    def wait(self, key: str = "default") -> None:
        with self._lock:
            now = self._clock()
            last = self._last.get(key)
            if last is not None and (gap := self.min_interval - (now - last)) > 0:
                self._sleep(gap)
                now = self._clock()
            self._last[key] = now
