"""Tier 1 (docs/testing-strategy.md): pure deterministic validation logic,
no I/O, no DB session, no provider. Per PLAN.md Phase 7's completion
criteria — every rule gets both a passing and a failing case with a
specific reason string, including the deliberately adversarial ones
(a total off by one cent, a missing invoice number).
"""

from app.models import ExtractionResult
from app.validation import (
    REQUIRED_FIELDS,
    check_arithmetic_consistency,
    check_required_fields,
    run_validation,
)


def _valid_extraction(**overrides) -> ExtractionResult:
    defaults = dict(
        vendor_name="Acme Corp",
        invoice_number="INV-1042",
        invoice_date="2026-03-01",
        due_date="2026-03-31",
        currency="USD",
        subtotal=1000.00,
        tax=80.00,
        total=1080.00,
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


def test_required_fields_all_pass_on_a_complete_extraction():
    results = check_required_fields(_valid_extraction())
    assert all(r.passed for r in results)
    assert {r.rule_name for r in results} == {f"required:{f}" for f in REQUIRED_FIELDS}


def test_required_fields_reports_a_specific_missing_field_by_name():
    results = check_required_fields(_valid_extraction(invoice_number=None))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].rule_name == "required:invoice_number"
    assert "invoice_number" in failed[0].reason
    assert "required but was not extracted" in failed[0].reason


def test_required_fields_does_not_require_due_date():
    # A real Phase 5 finding: a missing due date is a legitimate value
    # (e.g. "Net 30" terms with no explicit date), not an extraction
    # failure — see docs/extraction-strategy.md.
    results = check_required_fields(_valid_extraction(due_date=None))
    assert all(r.passed for r in results)
    assert "due_date" not in [r.rule_name for r in results]


def test_required_fields_reports_every_missing_field_independently():
    results = check_required_fields(_valid_extraction(vendor_name=None, currency=None))
    failed_names = {r.rule_name for r in results if not r.passed}
    assert failed_names == {"required:vendor_name", "required:currency"}


def test_arithmetic_consistency_passes_on_exact_match():
    result = check_arithmetic_consistency(_valid_extraction())
    assert result.passed
    assert result.rule_name == "arithmetic:subtotal_plus_tax_equals_total"


def test_arithmetic_consistency_passes_within_rounding_tolerance():
    result = check_arithmetic_consistency(_valid_extraction(total=1080.01))
    assert result.passed


def test_arithmetic_consistency_fails_on_a_total_off_by_one_cent_beyond_tolerance():
    # The deliberately adversarial case PLAN.md names explicitly.
    result = check_arithmetic_consistency(_valid_extraction(total=1080.05))
    assert not result.passed
    assert "1000.0" in result.reason
    assert "80.0" in result.reason
    assert "1080.05" in result.reason


def test_arithmetic_consistency_fails_clearly_when_a_component_is_missing():
    result = check_arithmetic_consistency(_valid_extraction(subtotal=None))
    assert not result.passed
    assert "missing" in result.reason


def test_run_validation_returns_all_rules_together():
    results = run_validation(_valid_extraction())
    assert len(results) == len(REQUIRED_FIELDS) + 1  # required fields + arithmetic
    assert all(r.passed for r in results)


def test_run_validation_surfaces_multiple_independent_failures():
    results = run_validation(_valid_extraction(invoice_number=None, total=1080.05))
    failed_names = {r.rule_name for r in results if not r.passed}
    assert failed_names == {
        "required:invoice_number",
        "arithmetic:subtotal_plus_tax_equals_total",
    }
