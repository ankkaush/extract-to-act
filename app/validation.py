"""Deterministic validation — see docs/reliability.md and PLAN.md Phase 7.

This is the load-bearing proof of the project's central principle: an
AI-extracted value is never trusted on its own for a financial fact that
can be checked with plain code. Nothing in this module looks at
confidence scores — Mistral doesn't return per-field confidence anyway
(see docs/adr/0006-extraction-provider.md), which makes this the *only*
gate for financial correctness, not one of several.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ExtractionResult

# Every field here must be present for a document to proceed untouched.
# due_date is deliberately excluded: the real Phase 5 run confirmed a
# missing due date is a legitimate value (e.g. "Net 30" terms with no
# explicit date on the document), not an extraction failure — see
# docs/extraction-strategy.md, "Real results".
REQUIRED_FIELDS = [
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax",
    "total",
]

# Rounding tolerance for currency arithmetic, in currency units — matches
# the tolerance already established for the synthetic dataset's own
# internal consistency (spike/test_dataset_integrity.py).
ARITHMETIC_TOLERANCE = 0.02


@dataclass
class RuleResult:
    rule_name: str
    passed: bool
    reason: str | None = None


def check_required_fields(extraction: ExtractionResult) -> list[RuleResult]:
    """One rule per field, not one combined rule — so a reviewer (and a
    test) can see exactly which field was missing, not just that
    "something" was.
    """
    results = []
    for field_name in REQUIRED_FIELDS:
        value = getattr(extraction, field_name)
        rule_name = f"required:{field_name}"
        if value is None:
            results.append(
                RuleResult(rule_name, False, f"{field_name} is required but was not extracted")
            )
        else:
            results.append(RuleResult(rule_name, True))
    return results


def check_arithmetic_consistency(extraction: ExtractionResult) -> RuleResult:
    rule_name = "arithmetic:subtotal_plus_tax_equals_total"
    subtotal, tax, total = extraction.subtotal, extraction.tax, extraction.total

    if subtotal is None or tax is None or total is None:
        # Genuinely different from a required-field failure: the fields
        # exist or don't independently of whether the *arithmetic* can be
        # checked, so this is reported as its own specific reason rather
        # than silently reusing the required-field failure.
        return RuleResult(rule_name, False, "cannot verify: subtotal, tax, or total is missing")

    expected_total = float(subtotal) + float(tax)
    difference = abs(expected_total - float(total))
    if difference > ARITHMETIC_TOLERANCE:
        return RuleResult(
            rule_name,
            False,
            f"subtotal ({subtotal}) + tax ({tax}) = {expected_total:.2f}, but total is {total} "
            f"— difference of {difference:.2f} exceeds the {ARITHMETIC_TOLERANCE} tolerance",
        )
    return RuleResult(rule_name, True)


def run_validation(extraction: ExtractionResult) -> list[RuleResult]:
    results = check_required_fields(extraction)
    results.append(check_arithmetic_consistency(extraction))
    return results
