"""Tier 1 (docs/testing-strategy.md): pure correction-parsing logic, no
I/O, no DB session.
"""

from datetime import date

import pytest

from app.review import (
    CORRECTABLE_FIELDS,
    InvalidFieldValueError,
    UnknownFieldError,
    parse_corrected_value,
)


def test_correctable_fields_match_extracted_header_fields():
    assert CORRECTABLE_FIELDS == {
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax",
        "total",
    }


def test_parses_string_field_unchanged():
    assert parse_corrected_value("vendor_name", "Acme Corp") == "Acme Corp"


def test_parses_numeric_field():
    assert parse_corrected_value("total", "1080.50") == 1080.50


def test_parses_date_field():
    assert parse_corrected_value("invoice_date", "2026-03-01") == date(2026, 3, 1)


def test_parses_date_field_tolerating_full_iso_datetime():
    assert parse_corrected_value("due_date", "2026-03-31T00:00:00") == date(2026, 3, 31)


def test_empty_value_becomes_none():
    assert parse_corrected_value("due_date", "") is None
    assert parse_corrected_value("due_date", None) is None
    assert parse_corrected_value("due_date", "   ") is None


def test_unknown_field_raises():
    with pytest.raises(UnknownFieldError):
        parse_corrected_value("bank_account_number", "123")


def test_unparseable_numeric_value_raises():
    with pytest.raises(InvalidFieldValueError):
        parse_corrected_value("total", "not-a-number")


def test_unparseable_date_value_raises():
    with pytest.raises(InvalidFieldValueError):
        parse_corrected_value("invoice_date", "not-a-date")
