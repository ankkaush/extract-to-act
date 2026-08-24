"""ORM models — see docs/data-model.md for entity purpose/rationale and
docs/state-machine.md for the state enum and transitions.

Phase 3 scope: schema only. No code here reads or writes these tables yet
— that starts in Phase 4 (ingestion) onward.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class DocumentState(enum.StrEnum):
    """See docs/state-machine.md for what each state means and why it exists."""

    RECEIVED = "RECEIVED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    VALIDATING = "VALIDATING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    VALIDATED = "VALIDATED"
    ACTIONED = "ACTIONED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


class ApprovalDecision(enum.StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccountingActionStatus(enum.StrEnum):
    ATTEMPTED = "ATTEMPTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class Document(Base):
    """One row per uploaded file. See docs/data-model.md."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(1024))
    original_filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(127))
    state: Mapped[DocumentState] = mapped_column(
        Enum(DocumentState, name="document_state"), default=DocumentState.RECEIVED, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    extraction_result: Mapped["ExtractionResult | None"] = relationship(
        back_populates="document", uselist=False
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(back_populates="document")
    review_events: Mapped[list["ReviewEvent"]] = relationship(back_populates="document")
    approval: Mapped["Approval | None"] = relationship(back_populates="document", uselist=False)
    state_history: Mapped[list["StateHistory"]] = relationship(back_populates="document")
    accounting_action: Mapped["AccountingAction | None"] = relationship(
        back_populates="document", uselist=False
    )


class ExtractionResult(Base):
    """Normalized extraction output for a document, plus the raw provider
    payload. Header fields likely to be queried or validated against
    (vendor, invoice number, dates, amounts) are promoted to real columns;
    full per-field provenance (confidence, page, bbox, source text) for
    every extracted field — promoted or not — lives in `fields`.
    See docs/extraction-strategy.md for what provenance is kept and why.
    """

    __tablename__ = "extraction_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), unique=True
    )
    provider_name: Mapped[str] = mapped_column(String(64))
    provider_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    vendor_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    invoice_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    subtotal: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # {field_name: {value, confidence, page, bbox, source_text}} for every
    # extracted field, including the promoted ones above.
    fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="extraction_result")
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(back_populates="extraction_result")


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    extraction_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_results.id"), index=True
    )
    line_number: Mapped[int] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    line_total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)

    extraction_result: Mapped["ExtractionResult"] = relationship(back_populates="line_items")


class Vendor(Base):
    """Known-vendor table used for deterministic fuzzy matching (Phase 8)."""

    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationResult(Base):
    """One row per deterministic rule run against a document. See
    docs/reliability.md for the business-exception vs. technical-failure
    distinction this feeds into.
    """

    __tablename__ = "validation_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128))
    passed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="validation_results")


class ReviewEvent(Base):
    """Correction audit trail — one row per corrected field. Never
    overwritten; see docs/workflow.md on human review.
    """

    __tablename__ = "review_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(128))
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="review_events")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), unique=True
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    threshold_applied: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    approver: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="approval")


class StateHistory(Base):
    """Append-only log of every state transition. Never updated or deleted
    — this is both the audit trail and the crash-recovery mechanism. See
    docs/state-machine.md.
    """

    __tablename__ = "state_history"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), index=True
    )
    from_state: Mapped[DocumentState | None] = mapped_column(
        Enum(DocumentState, name="document_state"), nullable=True
    )
    to_state: Mapped[DocumentState] = mapped_column(Enum(DocumentState, name="document_state"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="state_history")


class AccountingAction(Base):
    """Idempotency ledger for downstream writes — recorded as ATTEMPTED
    before a write, checked before ever writing again. See
    docs/reliability.md, idempotency scenario 3.
    """

    __tablename__ = "accounting_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_accounting_actions_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), unique=True
    )
    status: Mapped[AccountingActionStatus] = mapped_column(
        Enum(AccountingActionStatus, name="accounting_action_status")
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="accounting_action")


__all__ = [
    "Base",
    "DocumentState",
    "ApprovalDecision",
    "AccountingActionStatus",
    "Document",
    "ExtractionResult",
    "InvoiceLineItem",
    "Vendor",
    "ValidationResult",
    "ReviewEvent",
    "Approval",
    "StateHistory",
    "AccountingAction",
]
