"""Tier 1 (docs/testing-strategy.md): pure fuzzy vendor-matching logic,
no I/O, no DB session. Per PLAN.md Phase 8's completion criteria — a
known vendor with a typo still matches, a genuinely new vendor is
correctly flagged.
"""

import uuid

from app.vendor_matching import check_vendor_known, find_best_match, normalize_vendor_name

ACME_ID = uuid.uuid4()
KNOWN_VENDORS = [
    (ACME_ID, "Acme Corp"),
    (uuid.uuid4(), "Bluepeak Office Supplies"),
    (uuid.uuid4(), "Harborline Industrial Supply"),
]


def test_normalize_vendor_name_strips_punctuation_and_case():
    assert normalize_vendor_name("Acme Corp.") == "acme corp"
    assert normalize_vendor_name("  ACME   Corp  ") == "acme corp"
    assert normalize_vendor_name("Acme, Corp") == "acme corp"


def test_find_best_match_exact_match():
    result = find_best_match("Acme Corp", KNOWN_VENDORS)
    assert result.matched
    assert result.vendor_id == ACME_ID
    assert result.score == 100.0


def test_find_best_match_near_miss_spelling_still_matches():
    # Trailing period — a cosmetic difference, not a different vendor.
    result = find_best_match("Acme Corp.", KNOWN_VENDORS)
    assert result.matched
    assert result.vendor_id == ACME_ID


def test_find_best_match_genuinely_unknown_vendor_does_not_match():
    result = find_best_match("Totally Unrelated Company Ltd", KNOWN_VENDORS)
    assert not result.matched
    # The closest name is still surfaced for review context, even though
    # it didn't clear the threshold.
    assert result.vendor_name is not None


def test_find_best_match_with_no_known_vendors():
    result = find_best_match("Acme Corp", [])
    assert not result.matched
    assert result.vendor_id is None


def test_find_best_match_with_empty_name():
    result = find_best_match("", KNOWN_VENDORS)
    assert not result.matched


def test_check_vendor_known_passes_on_a_match():
    result = check_vendor_known("Acme Corp", KNOWN_VENDORS)
    assert result.rule_name == "vendor:known"
    assert result.passed
    assert "Acme Corp" in result.reason


def test_check_vendor_known_fails_on_an_unrecognized_vendor():
    result = check_vendor_known("Totally Unrelated Company Ltd", KNOWN_VENDORS)
    assert not result.passed
    assert "Totally Unrelated Company Ltd" in result.reason
    assert "did not match" in result.reason


def test_check_vendor_known_fails_clearly_when_name_is_missing():
    # Distinct from an unmatched name — this is "nothing to match at
    # all", not "matched nothing closely enough".
    result = check_vendor_known(None, KNOWN_VENDORS)
    assert not result.passed
    assert "missing" in result.reason


def test_check_vendor_known_with_no_vendors_on_file():
    result = check_vendor_known("Acme Corp", [])
    assert not result.passed
    assert "no vendors on file" in result.reason.lower() or "did not match" in result.reason
