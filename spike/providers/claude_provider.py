"""Claude vision — no native OCR/confidence layer. Forced tool-use gives
reliable structured JSON; confidence is self-reported by the model on
request, which is exactly the gap this spike is meant to characterize —
see docs/extraction-strategy.md, "on confidence scores": a self-reported
number from an LLM with no native calibration is a hypothesis to test,
not a substitute for Azure/Mistral's native confidence scores.

Requires ANTHROPIC_API_KEY. No free tier — every call here costs real
money, budgeted in docs/cost-strategy.md.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from spike.pricing import estimate_claude_cost_usd
from spike.schema import EVALUATED_FIELDS, FieldResult, LineItemResult, NormalizedExtraction

MODEL = "claude-sonnet-5"

_EXTRACTION_TOOL = {
    "name": "record_invoice_extraction",
    "description": "Record the extracted invoice fields, each with a self-assessed confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            **{
                name: {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["string", "number", "null"]},
                        "confidence": {
                            "type": "number",
                            "description": "Your own confidence in this value, 0.0-1.0.",
                        },
                        "source_text": {
                            "type": ["string", "null"],
                            "description": "The exact text in the document this value came from.",
                        },
                    },
                    "required": ["value", "confidence"],
                }
                for name in EVALUATED_FIELDS
            },
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
    },
}


def extract(doc_path: Path, doc_id: str) -> NormalizedExtraction:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    pdf_b64 = base64.b64encode(doc_path.read_bytes()).decode("ascii")

    start = time.monotonic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_invoice_extraction"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract the invoice fields via the record_invoice_extraction tool. "
                            "Use null for anything genuinely not present rather than guessing."
                        ),
                    },
                ],
            }
        ],
    )
    latency = time.monotonic() - start

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        return NormalizedExtraction(
            provider_name="claude_vision",
            model_version=MODEL,
            doc_id=doc_id,
            latency_seconds=latency,
            error="Claude did not return a tool_use block",
        )

    data = tool_use.input
    fields: dict[str, FieldResult] = {}
    for name in EVALUATED_FIELDS:
        field_data = data.get(name) or {}
        fields[name] = FieldResult(
            value=field_data.get("value"),
            confidence=field_data.get("confidence"),
            source_text=field_data.get("source_text"),
            # No native page/bbox — this is the documented, expected gap.
        )

    line_items = [
        LineItemResult(
            description=item.get("description"),
            quantity=item.get("quantity"),
            unit_price=item.get("unit_price"),
            line_total=item.get("line_total"),
        )
        for item in data.get("line_items", [])
    ]

    cost = estimate_claude_cost_usd(
        model=MODEL,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    return NormalizedExtraction(
        provider_name="claude_vision",
        model_version=MODEL,
        doc_id=doc_id,
        fields=fields,
        line_items=line_items,
        latency_seconds=latency,
        estimated_cost_usd=cost,
        raw_response={
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        },
    )
