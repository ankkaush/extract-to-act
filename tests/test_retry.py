"""Tier 1 (docs/testing-strategy.md): pure retry/backoff logic, no I/O
— `sleep` is injected so this runs with zero real wall-clock delay.
"""

import pytest

from app.retry import RetriesExhausted, call_with_retry


def test_succeeds_on_first_attempt_without_sleeping():
    sleeps = []
    result = call_with_retry(lambda: 42, attempts=3, sleep=sleeps.append)
    assert result == 42
    assert sleeps == []


def test_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    sleeps = []
    result = call_with_retry(flaky, attempts=5, base_delay_seconds=0.1, sleep=sleeps.append)

    assert result == "ok"
    assert calls["n"] == 3
    # Exponential backoff: 0.1, 0.2 between the two failed attempts.
    assert sleeps == [0.1, 0.2]


def test_raises_retries_exhausted_after_all_attempts_fail():
    def always_fails():
        raise ValueError("still broken")

    sleeps = []
    with pytest.raises(RetriesExhausted) as exc_info:
        call_with_retry(always_fails, attempts=3, base_delay_seconds=0.1, sleep=sleeps.append)

    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.last_error, ValueError)
    # Sleeps between attempts, never after the final one.
    assert sleeps == [0.1, 0.2]


def test_single_attempt_never_sleeps():
    def always_fails():
        raise ValueError("broken")

    sleeps = []
    with pytest.raises(RetriesExhausted):
        call_with_retry(always_fails, attempts=1, sleep=sleeps.append)

    assert sleeps == []
