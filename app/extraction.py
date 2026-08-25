"""ExtractionProvider adapter — see docs/architecture.md on the adapter
boundary. Mistral OCR is the concrete implementation, selected in Phase 5
(docs/adr/0006-extraction-provider.md) from a real, evaluated run — not a
placeholder guess.

The provider call shape here mirrors spike/providers/mistral_provider.py
exactly (same import path, same `schema_definition` field name), both of
which were only discovered correct by hitting real SDK-shape bugs during
the Phase 5 spike. This is deliberately duplicated rather than imported
from `spike/` — see spike/README.md, "why not part of the application":
the application must never depend on the throwaway spike package.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.models import ExtractionResult, InvoiceLineItem

# The header fields extracted and persisted — matches the promoted
# columns on ExtractionResult (app/models.py) and docs/data-model.md.
# Kept as a local constant (not imported from spike/schema.py) for the
# same reason as the provider shape above: no app -> spike dependency.
EXTRACTED_FIELDS = [
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
]

_ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        **{name: {"type": ["string", "number", "null"]} for name in EXTRACTED_FIELDS},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "line_total": {"type": ["number", "null"]},
                },
            },
        },
    },
    "required": EXTRACTED_FIELDS,
}


@dataclass
class ExtractedField:
    value: str | float | None
    confidence: float | None = None
    page: int | None = None
    bbox: list[float] | None = None
    source_text: str | None = None


@dataclass
class ExtractedLineItem:
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    confidence: float | None = None


@dataclass
class ExtractionOutput:
    provider_name: str
    model_version: str | None
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    line_items: list[ExtractedLineItem] = field(default_factory=list)
    raw_response: dict | None = None


class ExtractionProvider(Protocol):
    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput: ...


class MistralExtractionProvider:
    """Real Mistral OCR integration. See docs/adr/0006-extraction-provider.md."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        from mistralai.client import Mistral

        client = Mistral(api_key=self._api_key)

        uploaded = client.files.upload(
            file={"file_name": filename, "content": content}, purpose="ocr"
        )
        signed = client.files.get_signed_url(file_id=uploaded.id)

        response = client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "document_url", "document_url": signed.url},
            document_annotation_format={
                "type": "json_schema",
                "json_schema": {"name": "invoice_fields", "schema_definition": _ANNOTATION_SCHEMA},
            },
            include_image_base64=False,
        )

        annotation = getattr(response, "document_annotation", None) or {}
        if isinstance(annotation, str):
            annotation = json.loads(annotation)

        fields = {name: ExtractedField(value=annotation.get(name)) for name in EXTRACTED_FIELDS}
        line_items = [
            ExtractedLineItem(
                description=item.get("description"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                line_total=item.get("line_total"),
            )
            for item in annotation.get("line_items", [])
        ]

        return ExtractionOutput(
            provider_name="mistral_ocr",
            model_version="mistral-ocr-latest",
            fields=fields,
            line_items=line_items,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
        )


def _as_number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value) -> date | None:
    if value is None:
        return None
    try:
        # Tolerates a full ISO datetime string, not just a bare date.
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        # A provider returning an unparseable date string is a real,
        # expected case (see docs/extraction-strategy.md's real-run
        # findings) — the raw string is preserved in `fields` below for
        # audit/review even when it can't populate the typed column.
        return None


def build_extraction_result(document_id: uuid.UUID, output: ExtractionOutput) -> ExtractionResult:
    """Maps provider output onto the DB schema — no I/O, not yet added to
    a session. The caller (app/routers/documents.py) owns persistence and
    the state transition.
    """
    fields = output.fields

    def _value(name: str):
        f = fields.get(name)
        return f.value if f else None

    result = ExtractionResult(
        document_id=document_id,
        provider_name=output.provider_name,
        provider_model_version=output.model_version,
        vendor_name=_value("vendor_name"),
        invoice_number=_value("invoice_number"),
        invoice_date=_as_date(_value("invoice_date")),
        due_date=_as_date(_value("due_date")),
        currency=_value("currency"),
        subtotal=_as_number(_value("subtotal")),
        tax=_as_number(_value("tax")),
        total=_as_number(_value("total")),
        fields={name: vars(f) for name, f in fields.items()},
        raw_response=output.raw_response or {},
    )
    result.line_items = [
        InvoiceLineItem(
            line_number=i,
            description=li.description,
            quantity=_as_number(li.quantity),
            unit_price=_as_number(li.unit_price),
            line_total=_as_number(li.line_total),
            confidence=li.confidence,
        )
        for i, li in enumerate(output.line_items, start=1)
    ]
    return result
