"""Phase 13 — generic bounded retry with exponential backoff. Pure: no
I/O beyond the injected `sleep` function. See docs/reliability.md:
"Retry with bounded backoff — no human judgment involved" for provider
timeouts/rate limits, and the same pattern reused for the "retry
briefly, then log and continue" notification-failure row.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RetriesExhausted(Exception):
    """Every attempt failed. Wraps the last underlying error rather than
    losing it — callers need the real cause to write an honest
    state_history/alert reason, not just "it didn't work."
    """

    def __init__(self, attempts: int, last_error: BaseException):
        super().__init__(f"gave up after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def call_with_retry[T](
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Calls fn() up to `attempts` times, doubling the delay between
    attempts (base_delay_seconds, 2x, 4x, ...). Returns fn()'s result on
    the first success. Raises RetriesExhausted if every attempt fails.
    `sleep` is injectable so tests exercise real retry behavior without
    real wall-clock delay — docs/testing-strategy.md's Tier 1 bar.
    """
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — any failure here is retryable; callers decide what's technical
            last_error = exc
            if attempt < attempts - 1:
                sleep(base_delay_seconds * (2**attempt))
    assert last_error is not None  # attempts >= 1 guarantees at least one failure was recorded
    raise RetriesExhausted(attempts, last_error)
