"""Tier 1 (docs/testing-strategy.md): pure normalization logic, no I/O,
no provider SDK, no network."""

import uuid

from app.extraction import (
    ExtractedField,
    ExtractedLineItem,
    ExtractionOutput,
    _as_date,
    _as_number,
    build_extraction_result,
)


def test_as_number_coerces_valid_values():
    assert _as_number(100.5) == 100.5
    assert _as_number("42") == 42.0
    assert _as_number(None) is None
    assert _as_number("not a number") is None


def test_as_date_parses_iso_strings():
    assert _as_date("2026-03-01").isoformat() == "2026-03-01"
    assert _as_date("2026-03-01T00:00:00").isoformat() == "2026-03-01"


def test_as_date_returns_none_for_unparseable_or_missing_values():
    # A real, expected case per docs/extraction-strategy.md's real-run
    # findings — must not raise.
    assert _as_date(None) is None
    assert _as_date("Net 30") is None
    assert _as_date("not-a-date") is None


def test_build_extraction_result_maps_header_fields():
    output = ExtractionOutput(
        provider_name="mistral_ocr",
        model_version="mistral-ocr-latest",
        fields={
            "vendor_name": ExtractedField(value="Acme Corp"),
            "invoice_number": ExtractedField(value="INV-1042"),
            "invoice_date": ExtractedField(value="2026-03-01"),
            "due_date": ExtractedField(value=None),
            "currency": ExtractedField(value="USD"),
            "subtotal": ExtractedField(value=1000.0),
            "tax": ExtractedField(value=80.0),
            "total": ExtractedField(value=1080.0),
        },
    )
    document_id = uuid.uuid4()

    result = build_extraction_result(document_id, output)

    assert result.document_id == document_id
    assert result.provider_name == "mistral_ocr"
    assert result.vendor_name == "Acme Corp"
    assert result.invoice_number == "INV-1042"
    assert result.invoice_date.isoformat() == "2026-03-01"
    assert result.due_date is None
    assert result.currency == "USD"
    assert result.subtotal == 1000.0
    assert result.tax == 80.0
    assert result.total == 1080.0
    # Full per-field provenance preserved in the JSONB fields blob even
    # for the promoted columns above.
    assert result.fields["vendor_name"]["value"] == "Acme Corp"


def test_build_extraction_result_handles_missing_fields_without_crashing():
    output = ExtractionOutput(provider_name="mistral_ocr", model_version=None, fields={})
    result = build_extraction_result(uuid.uuid4(), output)
    assert result.vendor_name is None
    assert result.total is None


def test_build_extraction_result_maps_line_items_with_sequential_numbers():
    output = ExtractionOutput(
        provider_name="mistral_ocr",
        model_version=None,
        line_items=[
            ExtractedLineItem(description="Widget", quantity=2, unit_price=50.0, line_total=100.0),
            ExtractedLineItem(description="Gadget", quantity=1, unit_price=25.0, line_total=25.0),
        ],
    )

    result = build_extraction_result(uuid.uuid4(), output)

    assert [li.line_number for li in result.line_items] == [1, 2]
    assert result.line_items[0].description == "Widget"
    assert result.line_items[1].line_total == 25.0
