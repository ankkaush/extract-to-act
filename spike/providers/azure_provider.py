"""Azure AI Document Intelligence — prebuilt-invoice model.

Requires AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and
AZURE_DOCUMENT_INTELLIGENCE_KEY. Free tier: 500 pages/month, ongoing, no
card — see docs/extraction-strategy.md.

Written against the documented `azure-ai-documentintelligence` SDK shape
but not yet run against a live account (see spike/providers/__init__.py).
Field/attribute names on the SDK's result objects are the most likely
thing to need a small fix on first real run.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from spike.schema import EVALUATED_FIELDS, FieldResult, LineItemResult, NormalizedExtraction

# Maps this project's field names to Azure's prebuilt-invoice field names.
_AZURE_FIELD_MAP = {
    "vendor_name": "VendorName",
    "invoice_number": "InvoiceId",
    "invoice_date": "InvoiceDate",
    "due_date": "DueDate",
    "subtotal": "SubTotal",
    "tax": "TotalTax",
    "total": "InvoiceTotal",
}


def _field_result(field) -> FieldResult:  # noqa: ANN001 — azure SDK type, avoid importing for typing only
    if field is None:
        return FieldResult(value=None)
    value = getattr(field, "value", None)
    # Amount fields (SubTotal, TotalTax, InvoiceTotal) come back as a
    # CurrencyValue with .amount, not a bare number.
    if hasattr(value, "amount"):
        value = value.amount
    page = None
    bbox = None
    if getattr(field, "bounding_regions", None):
        region = field.bounding_regions[0]
        page = getattr(region, "page_number", None)
        bbox = list(getattr(region, "polygon", []) or [])
    return FieldResult(
        value=value,
        confidence=getattr(field, "confidence", None),
        page=page,
        bbox=bbox or None,
        source_text=getattr(field, "content", None),
    )


def parse_result(result, doc_id: str, latency: float) -> NormalizedExtraction:  # noqa: ANN001
    """Pure mapping from an Azure `AnalyzeResult`-shaped object to our
    normalized schema — no network I/O, no SDK import required to call
    this. Deliberately separated from `extract()` below so it can be
    unit-tested against a fake result object without an Azure account or
    the azure-ai-documentintelligence package installed. See
    spike/test_providers.py.
    """
    if not result.documents:
        return NormalizedExtraction(
            provider_name="azure_document_intelligence",
            model_version="prebuilt-invoice",
            doc_id=doc_id,
            latency_seconds=latency,
            error="No documents in Azure result — extraction likely failed to recognize an invoice",
        )

    document = result.documents[0]
    azure_fields = document.fields or {}

    fields: dict[str, FieldResult] = {}
    for our_name in EVALUATED_FIELDS:
        azure_name = _AZURE_FIELD_MAP.get(our_name)
        fields[our_name] = (
            _field_result(azure_fields.get(azure_name)) if azure_name else FieldResult(value=None)
        )

    # Currency isn't its own top-level field in the prebuilt-invoice model
    # — it rides along on the amount CurrencyValue objects.
    total_field = azure_fields.get("InvoiceTotal")
    total_value = getattr(total_field, "value", None) if total_field else None
    has_currency = hasattr(total_value, "currency_code")
    currency_code = getattr(total_value, "currency_code", None) if has_currency else None
    fields["currency"] = FieldResult(value=currency_code)

    line_items: list[LineItemResult] = []
    items_field = azure_fields.get("Items")
    if items_field and getattr(items_field, "value", None):
        for item in items_field.value:
            item_fields = getattr(item, "value", {}) or {}
            desc = item_fields.get("Description")
            qty = item_fields.get("Quantity")
            unit_price = item_fields.get("UnitPrice")
            amount = item_fields.get("Amount")
            unit_price_value = getattr(unit_price, "value", None) if unit_price else None
            if hasattr(unit_price_value, "amount"):
                unit_price_value = unit_price_value.amount
            amount_value = getattr(amount, "value", None) if amount else None
            if hasattr(amount_value, "amount"):
                amount_value = amount_value.amount
            line_items.append(
                LineItemResult(
                    description=getattr(desc, "value", None) if desc else None,
                    quantity=getattr(qty, "value", None) if qty else None,
                    unit_price=unit_price_value,
                    line_total=amount_value,
                    confidence=getattr(item, "confidence", None),
                )
            )

    return NormalizedExtraction(
        provider_name="azure_document_intelligence",
        model_version="prebuilt-invoice",
        doc_id=doc_id,
        fields=fields,
        line_items=line_items,
        latency_seconds=latency,
        estimated_cost_usd=0.0,  # within the free 500-pages/month tier for a spike this size
        raw_response=result.as_dict() if hasattr(result, "as_dict") else None,
    )


def extract(doc_path: Path, doc_id: str) -> NormalizedExtraction:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    endpoint = os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"]
    key = os.environ["AZURE_DOCUMENT_INTELLIGENCE_KEY"]
    client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    start = time.monotonic()
    with open(doc_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-invoice", body=f, content_type="application/octet-stream"
        )
        result = poller.result()
    latency = time.monotonic() - start

    return parse_result(result, doc_id, latency)
