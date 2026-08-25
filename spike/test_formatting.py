"""Regression tests for spike/formatting.py. Promoted from an ad-hoc
verification script that caught a real bug during Phase 5: rounding the
integer and fractional parts of an amount independently turned 839.70
into "$840.70" — see the git history for spike/formatting.py.
"""

import pytest

from spike.formatting import format_amount, format_date


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        (839.70, "USD", "$839.70"),
        (612.26, "EUR", "612,26 €"),
        (408.00, "GBP", "£408.00"),
        (52250, "JPY", "¥52,250"),
        (236000.00, "INR", "₹2,36,000.00"),
        (2532.32, "EUR", "2.532,32 €"),
        (706.25, "CAD", "$706.25"),
        (-120.00, "USD", "-$120.00"),
        (200000.00, "INR", "₹2,00,000.00"),
        (90000.00, "INR", "₹90,000.00"),
        # The exact regression case: rounding int/frac parts separately
        # previously turned this into "$1,234,568.89".
        (1234567.89, "USD", "$1,234,567.89"),
    ],
)
def test_format_amount(value, currency, expected):
    assert format_amount(value, currency) == expected


def test_format_amount_ambiguous_symbol_only_drops_the_code():
    # inv_11's whole point: a bare "$" with no currency code, even for a
    # non-USD currency like CAD.
    assert format_amount(706.25, "CAD", ambiguous_symbol_only=True) == "$706.25"


@pytest.mark.parametrize(
    ("iso_date", "style", "expected"),
    [
        ("2026-02-03", "us", "02/03/2026"),
        ("2026-01-15", "eu_dot", "15.01.2026"),
        ("2026-01-30", "dd_mm_yyyy_slash", "30/01/2026"),
        ("2026-02-08", "dd_mm_yyyy_dash", "08-02-2026"),
        ("2026-02-12", "iso", "2026-02-12"),
    ],
)
def test_format_date(iso_date, style, expected):
    assert format_date(iso_date, style) == expected


def test_format_date_rejects_unknown_style():
    with pytest.raises(ValueError, match="unknown date style"):
        format_date("2026-01-01", "not_a_real_style")
