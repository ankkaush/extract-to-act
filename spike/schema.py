"""The normalized shape every provider's output is mapped into for
comparison — mirrors the promoted columns + `fields` JSONB shape in
app/models.py's ExtractionResult, but deliberately standalone (no
import from `app`): this spike is throwaway evaluation code, not part
of the application. See docs/extraction-strategy.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The header fields every provider is asked to extract and every result
# is scored against. Matches the "essential" tier from docs/problem.md's
# schema discussion — line items are evaluated separately since their
# accuracy is scored per-line, not per-field.
EVALUATED_FIELDS = [
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
]


@dataclass
class FieldResult:
    value: str | float | None
    confidence: float | None = None
    page: int | None = None
    bbox: list[float] | None = None
    source_text: str | None = None


@dataclass
class LineItemResult:
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    confidence: float | None = None


@dataclass
class NormalizedExtraction:
    provider_name: str
    model_version: str | None
    doc_id: str
    fields: dict[str, FieldResult] = field(default_factory=dict)
    line_items: list[LineItemResult] = field(default_factory=list)
    latency_seconds: float | None = None
    estimated_cost_usd: float | None = None
    raw_response: dict | None = None
    error: str | None = None

    def to_json(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "model_version": self.model_version,
            "doc_id": self.doc_id,
            "fields": {k: vars(v) for k, v in self.fields.items()},
            "line_items": [vars(li) for li in self.line_items],
            "latency_seconds": self.latency_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
            "raw_response": self.raw_response,
            "error": self.error,
        }
