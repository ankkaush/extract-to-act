"""Tests the response-PARSING logic of each provider wrapper against fake,
SDK-shaped objects — no network call, no credentials, no provider SDK
package installed required. This is exactly the risk flagged in
spike/providers/__init__.py ("written against the documented API shape
but not yet run against a live account") — these tests don't eliminate
that risk (only a real run against real API responses can), but they do
verify the mapping/normalization logic itself is correct, so the first
real run is testing provider behavior, not also debugging basic
dict-shuffling bugs at the same time.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from spike.providers import azure_provider, claude_provider, mistral_provider

# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------


class _FakeCurrencyValue:
    def __init__(self, amount, currency_code):
        self.amount = amount
        self.currency_code = currency_code


class _FakeBoundingRegion:
    def __init__(self, page_number, polygon):
        self.page_number = page_number
        self.polygon = polygon


class _FakeAzureField:
    def __init__(self, value=None, confidence=None, content=None, bounding_regions=None):
        self.value = value
        self.confidence = confidence
        self.content = content
        self.bounding_regions = bounding_regions or []


def _fake_azure_result(fields: dict, has_documents: bool = True):
    document = SimpleNamespace(fields=fields)
    return SimpleNamespace(documents=[document] if has_documents else [])


def test_azure_parse_result_maps_header_fields_and_currency():
    fields = {
        "VendorName": _FakeAzureField(
            value="Acme Corp",
            confidence=0.98,
            content="Acme Corp",
            bounding_regions=[_FakeBoundingRegion(1, [0, 0, 1, 1])],
        ),
        "InvoiceId": _FakeAzureField(value="INV-1042", confidence=0.95),
        "InvoiceDate": _FakeAzureField(value="2026-03-01", confidence=0.9),
        "DueDate": _FakeAzureField(value="2026-03-31", confidence=0.9),
        "SubTotal": _FakeAzureField(value=_FakeCurrencyValue(1000.0, "USD"), confidence=0.97),
        "TotalTax": _FakeAzureField(value=_FakeCurrencyValue(80.0, "USD"), confidence=0.95),
        "InvoiceTotal": _FakeAzureField(value=_FakeCurrencyValue(1080.0, "USD"), confidence=0.99),
    }
    result = _fake_azure_result(fields)

    extraction = azure_provider.parse_result(result, "doc1", latency=1.2)

    assert extraction.error is None
    assert extraction.fields["vendor_name"].value == "Acme Corp"
    assert extraction.fields["vendor_name"].confidence == 0.98
    assert extraction.fields["vendor_name"].page == 1
    assert extraction.fields["invoice_number"].value == "INV-1042"
    # CurrencyValue amounts must be unwrapped to a bare number, not left
    # as the SDK's CurrencyValue object.
    assert extraction.fields["subtotal"].value == 1000.0
    assert extraction.fields["tax"].value == 80.0
    assert extraction.fields["total"].value == 1080.0
    # Currency isn't a top-level Azure field — it must be derived from
    # the InvoiceTotal CurrencyValue.
    assert extraction.fields["currency"].value == "USD"


def test_azure_parse_result_handles_no_documents():
    result = _fake_azure_result(fields={}, has_documents=False)
    extraction = azure_provider.parse_result(result, "doc1", latency=0.5)
    assert extraction.error is not None
    assert extraction.fields == {}


def test_azure_parse_result_maps_line_items():
    items_field = _FakeAzureField(
        value=[
            SimpleNamespace(
                value={
                    "Description": _FakeAzureField(value="Widget"),
                    "Quantity": _FakeAzureField(value=10),
                    "UnitPrice": _FakeAzureField(value=_FakeCurrencyValue(100.0, "USD")),
                    "Amount": _FakeAzureField(value=_FakeCurrencyValue(1000.0, "USD")),
                },
                confidence=0.93,
            )
        ]
    )
    fields = {"Items": items_field}
    result = _fake_azure_result(fields)

    extraction = azure_provider.parse_result(result, "doc1", latency=1.0)

    assert len(extraction.line_items) == 1
    item = extraction.line_items[0]
    assert item.description == "Widget"
    assert item.quantity == 10
    assert item.unit_price == 100.0
    assert item.line_total == 1000.0
    assert item.confidence == 0.93


# ---------------------------------------------------------------------------
# Mistral
# ---------------------------------------------------------------------------


def _annotation_payload():
    return {
        "vendor_name": "Acme Corp",
        "invoice_number": "INV-1042",
        "invoice_date": "2026-03-01",
        "due_date": "2026-03-31",
        "currency": "USD",
        "subtotal": 1000.0,
        "tax": 80.0,
        "total": 1080.0,
        "line_items": [
            {"description": "Widget", "quantity": 10, "unit_price": 100.0, "line_total": 1000.0}
        ],
    }


def test_mistral_parse_response_with_dict_annotation():
    response = SimpleNamespace(document_annotation=_annotation_payload(), pages=[1])

    extraction = mistral_provider.parse_response(response, "doc1", latency=2.1)

    assert extraction.fields["vendor_name"].value == "Acme Corp"
    assert extraction.fields["total"].value == 1080.0
    assert len(extraction.line_items) == 1
    assert extraction.line_items[0].description == "Widget"
    assert extraction.estimated_cost_usd is not None and extraction.estimated_cost_usd >= 0


def test_mistral_parse_response_with_json_string_annotation():
    # The SDK may return the annotation as a JSON string rather than an
    # already-parsed dict, depending on version — both must work.
    response = SimpleNamespace(document_annotation=json.dumps(_annotation_payload()), pages=[1, 2])

    extraction = mistral_provider.parse_response(response, "doc1", latency=2.1)

    assert extraction.fields["invoice_number"].value == "INV-1042"
    assert len(extraction.line_items) == 1


def test_mistral_parse_response_missing_annotation_does_not_crash():
    response = SimpleNamespace(document_annotation=None, pages=[])
    extraction = mistral_provider.parse_response(response, "doc1", latency=1.0)
    assert extraction.fields["vendor_name"].value is None
    assert extraction.line_items == []


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


def _tool_use_block(input_data: dict):
    return SimpleNamespace(type="tool_use", input=input_data)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _claude_field_payload():
    return {
        name: {"value": value, "confidence": 0.9, "source_text": str(value)}
        for name, value in _annotation_payload().items()
        if name != "line_items"
    } | {"line_items": _annotation_payload()["line_items"]}


def test_claude_parse_response_extracts_tool_use_block():
    response = SimpleNamespace(
        content=[_text_block("thinking..."), _tool_use_block(_claude_field_payload())],
        usage=SimpleNamespace(input_tokens=1500, output_tokens=300),
    )

    extraction = claude_provider.parse_response(response, "doc1", latency=3.4)

    assert extraction.error is None
    assert extraction.fields["vendor_name"].value == "Acme Corp"
    assert extraction.fields["vendor_name"].confidence == 0.9
    # Claude has no native page/bbox — must stay unset, not fabricated.
    assert extraction.fields["vendor_name"].page is None
    assert extraction.fields["vendor_name"].bbox is None
    assert len(extraction.line_items) == 1
    assert extraction.estimated_cost_usd > 0  # Claude has no free tier


def test_claude_parse_response_handles_missing_tool_use():
    response = SimpleNamespace(
        content=[_text_block("I couldn't process this document.")],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )
    extraction = claude_provider.parse_response(response, "doc1", latency=1.0)
    assert extraction.error is not None
    assert extraction.fields == {}
