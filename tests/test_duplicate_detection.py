"""Tier 1 (docs/testing-strategy.md): pure duplicate-detection logic, no
I/O, no DB session. Per PLAN.md Phase 9's stated tests — identical file
twice, same invoice re-typed with a formatting difference, two genuinely
different invoices from the same vendor on the same day (must NOT flag).
"""

import uuid
from datetime import date

from app.duplicate_detection import (
    find_content_duplicate,
    find_exact_hash_duplicate,
    normalize_invoice_number,
)

OTHER_DOC_ID = uuid.uuid4()


def test_normalize_invoice_number_strips_whitespace_and_case():
    assert normalize_invoice_number(" INV-1042 ") == "inv-1042"


def test_exact_hash_duplicate_found_when_identical_content_hash_exists():
    result = find_exact_hash_duplicate("abc123", [(OTHER_DOC_ID, "abc123")])
    assert result.is_duplicate
    assert result.matched_document_id == OTHER_DOC_ID


def test_exact_hash_duplicate_not_found_when_hashes_differ():
    result = find_exact_hash_duplicate("abc123", [(OTHER_DOC_ID, "different-hash")])
    assert not result.is_duplicate


def test_exact_hash_duplicate_with_no_existing_documents():
    result = find_exact_hash_duplicate("abc123", [])
    assert not result.is_duplicate


def _candidate(**overrides):
    defaults = dict(
        doc_id=OTHER_DOC_ID,
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1080.00,
        invoice_date=date(2026, 3, 1),
    )
    defaults.update(overrides)
    return (
        defaults["doc_id"],
        defaults["vendor_name"],
        defaults["invoice_number"],
        defaults["total"],
        defaults["invoice_date"],
    )


def test_content_duplicate_exact_match_on_all_four_fields():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1080.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate()],
    )
    assert result.is_duplicate
    assert result.matched_document_id == OTHER_DOC_ID


def test_content_duplicate_matches_despite_cosmetic_formatting_differences():
    # The same invoice re-typed with a formatting difference — vendor
    # punctuation and invoice-number casing/whitespace vary, the
    # underlying invoice does not.
    result = find_content_duplicate(
        vendor_name="Acme Corp.",
        invoice_number=" inv-1042 ",
        total=1080.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(vendor_name="Acme Corp", invoice_number="INV-1042")],
    )
    assert result.is_duplicate


def test_content_duplicate_matches_within_amount_tolerance():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1080.01,  # a cent off, within the 0.02 tolerance
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(total=1080.00)],
    )
    assert result.is_duplicate


def test_two_different_invoices_same_vendor_same_day_are_not_flagged():
    # PLAN.md's explicit adversarial case: same vendor, same day, but a
    # genuinely different invoice (different number and amount) — must
    # NOT be treated as a duplicate.
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-2099",
        total=250.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(invoice_number="INV-1042", total=1080.00)],
    )
    assert not result.is_duplicate


def test_different_vendor_same_other_fields_not_flagged():
    result = find_content_duplicate(
        vendor_name="Beta Inc",
        invoice_number="INV-1042",
        total=1080.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(vendor_name="Acme Corp")],
    )
    assert not result.is_duplicate


def test_different_date_not_flagged():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1080.00,
        invoice_date=date(2026, 4, 1),
        candidates=[_candidate(invoice_date=date(2026, 3, 1))],
    )
    assert not result.is_duplicate


def test_amount_beyond_tolerance_not_flagged():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1090.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(total=1080.00)],
    )
    assert not result.is_duplicate


def test_missing_field_declines_to_guess():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number=None,
        total=1080.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate()],
    )
    assert not result.is_duplicate


def test_candidate_with_missing_field_is_skipped_not_crashed_on():
    result = find_content_duplicate(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        total=1080.00,
        invoice_date=date(2026, 3, 1),
        candidates=[_candidate(total=None)],
    )
    assert not result.is_duplicate
