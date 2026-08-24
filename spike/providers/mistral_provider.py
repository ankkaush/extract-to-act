"""Mistral OCR 4 — general document OCR with schema-constrained structured
JSON output (document annotation).

Requires MISTRAL_API_KEY. Free "Experiment" tier: no card, rate-limited
(~2 RPM) — fine for a slow spike, see docs/extraction-strategy.md.

Written against Mistral's documented OCR + document-annotation API shape
but not yet run against a live account — the annotation-schema parameter
name/shape is the most likely thing to need a small fix on first real
run (see spike/providers/__init__.py).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from spike.schema import EVALUATED_FIELDS, FieldResult, LineItemResult, NormalizedExtraction

_ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        **{name: {"type": ["string", "number", "null"]} for name in EVALUATED_FIELDS},
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
    "required": EVALUATED_FIELDS,
}


def extract(doc_path: Path, doc_id: str) -> NormalizedExtraction:
    from mistralai import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    start = time.monotonic()
    with open(doc_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": doc_path.name, "content": f.read()}, purpose="ocr"
        )
    signed = client.files.get_signed_url(file_id=uploaded.id)

    response = client.ocr.process(
        model="mistral-ocr-latest",
        document={"type": "document_url", "document_url": signed.url},
        document_annotation_format={
            "type": "json_schema",
            "json_schema": {"name": "invoice_fields", "schema": _ANNOTATION_SCHEMA},
        },
        include_image_base64=False,
    )
    latency = time.monotonic() - start

    annotation = getattr(response, "document_annotation", None) or {}
    if isinstance(annotation, str):
        import json

        annotation = json.loads(annotation)

    fields: dict[str, FieldResult] = {}
    for name in EVALUATED_FIELDS:
        # Mistral OCR returns document-level confidence/bbox for text
        # blocks, not natively per structured-field — this spike is
        # partly what determines whether that's a real gap in practice.
        # See docs/extraction-strategy.md, "on confidence scores".
        fields[name] = FieldResult(value=annotation.get(name))

    line_items = [
        LineItemResult(
            description=item.get("description"),
            quantity=item.get("quantity"),
            unit_price=item.get("unit_price"),
            line_total=item.get("line_total"),
        )
        for item in annotation.get("line_items", [])
    ]

    page_count = len(getattr(response, "pages", []) or [1])
    from spike.pricing import MISTRAL_OCR_USD_PER_PAGE

    return NormalizedExtraction(
        provider_name="mistral_ocr",
        model_version="mistral-ocr-latest",
        doc_id=doc_id,
        fields=fields,
        line_items=line_items,
        latency_seconds=latency,
        estimated_cost_usd=page_count * MISTRAL_OCR_USD_PER_PAGE,  # 0 in practice on the free tier
        raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
    )
