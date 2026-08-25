"""Tier 1 (docs/testing-strategy.md): pure approval-threshold logic, no
I/O, no DB session.
"""

from app.approval import requires_approval


def test_total_under_threshold_does_not_require_approval():
    result = requires_approval(total=500.0, threshold=1000.0)
    assert not result.required


def test_total_at_threshold_requires_approval():
    # >= is deliberate: "at or above the configured amount" per
    # docs/workflow.md, not strictly above it.
    result = requires_approval(total=1000.0, threshold=1000.0)
    assert result.required


def test_total_above_threshold_requires_approval():
    result = requires_approval(total=1500.0, threshold=1000.0)
    assert result.required


def test_zero_threshold_requires_approval_for_any_positive_total():
    result = requires_approval(total=1.0, threshold=0.0)
    assert result.required
