"""API request/response shapes. See docs/api.md."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import DocumentState


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: DocumentState
    original_filename: str
    mime_type: str
    content_hash: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_number: int
    description: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float | None
    confidence: float | None


class ExtractionResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    provider_name: str
    provider_model_version: str | None
    vendor_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: float | None
    tax: float | None
    total: float | None
    # Per-field {value, confidence, page, bbox, source_text} — see
    # docs/extraction-strategy.md, "Provenance: what's kept".
    fields: dict
    line_items: list[LineItemOut]
    created_at: datetime


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_name: str
    passed: bool
    reason: str | None


class ReviewQueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    created_at: datetime
    updated_at: datetime
    failed_rules: list[ValidationResultOut]


class ReviewDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document: DocumentOut
    extraction: ExtractionResultOut | None
    failed_rules: list[ValidationResultOut]
    file_url: str | None


class FieldCorrectionIn(BaseModel):
    field_name: str
    corrected_value: str | None = None


class ReviewCorrectionIn(BaseModel):
    reviewer: str
    corrections: list[FieldCorrectionIn]


class ReviewRejectionIn(BaseModel):
    reviewer: str
    reason: str
