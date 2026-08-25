"""Tier 1 (docs/testing-strategy.md): pure action-eligibility logic, no
I/O, no DB session.
"""

from app.accounting import check_action_eligibility


def test_under_threshold_is_eligible_without_approval():
    result = check_action_eligibility(total=100.0, threshold=1000.0, has_approval=False)
    assert result.eligible


def test_at_or_above_threshold_without_approval_is_not_eligible():
    result = check_action_eligibility(total=1000.0, threshold=1000.0, has_approval=False)
    assert not result.eligible
    assert "awaiting approval" in result.reason


def test_at_or_above_threshold_with_approval_is_eligible():
    result = check_action_eligibility(total=5000.0, threshold=1000.0, has_approval=True)
    assert result.eligible


def test_under_threshold_with_approval_is_still_eligible():
    # An approval row existing shouldn't ever make an already-eligible
    # document ineligible.
    result = check_action_eligibility(total=100.0, threshold=1000.0, has_approval=True)
    assert result.eligible
