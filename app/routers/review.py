"""Phase 10 — Human Review Workflow. See docs/workflow.md and
docs/api.md. A NEEDS_REVIEW document is queued here; a reviewer sees the
original file (via the signed file_url — app/routers/files.py) and
extracted fields side by side, then either corrects the fields
(-> VALIDATED, rejoining the same forward path a touchless document
takes — docs/state-machine.md) or rejects the document outright
(-> REJECTED). Neither is a technical failure; see docs/reliability.md's
business-exception distinction.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_session
from app.models import (
    Document,
    DocumentState,
    ExtractionResult,
    ReviewEvent,
    StateHistory,
    ValidationResult,
)
from app.review import InvalidFieldValueError, UnknownFieldError, parse_corrected_value
from app.routers.documents import get_storage_provider
from app.schemas import (
    ReviewCorrectionIn,
    ReviewDetailOut,
    ReviewQueueItemOut,
    ReviewRejectionIn,
)
from app.storage import StorageProvider

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(require_api_key)])


def _failed_rules(session: Session, document: Document) -> list[ValidationResult]:
    """The rules currently blocking this document. Only meaningful while
    the document is NEEDS_REVIEW — a correction moves it to VALIDATED
    without re-running Phase 7/8's rules (see app/review.py), so the
    original failing `validation_results` rows are left in place as
    history, not deleted or updated (same append-only rationale as
    state_history, docs/data-model.md) but are no longer "current" once
    the document has moved on.
    """
    if document.state != DocumentState.NEEDS_REVIEW:
        return []
    return list(
        session.scalars(
            select(ValidationResult)
            .where(ValidationResult.document_id == document.id)
            .where(ValidationResult.passed.is_(False))
        ).all()
    )


def _get_document_or_404(session: Session, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _detail(
    session: Session,
    storage: StorageProvider,
    document: Document,
    extraction: ExtractionResult | None,
) -> ReviewDetailOut:
    return ReviewDetailOut(
        document=document,
        extraction=extraction,
        failed_rules=_failed_rules(session, document),
        file_url=storage.sign_url(storage_path=document.storage_path),
    )


@router.get("", response_model=list[ReviewQueueItemOut])
def list_review_queue(session: Session = Depends(get_session)):
    documents = session.scalars(
        select(Document)
        .where(Document.state == DocumentState.NEEDS_REVIEW)
        .order_by(Document.created_at.asc())
    ).all()
    return [
        ReviewQueueItemOut(
            id=doc.id,
            original_filename=doc.original_filename,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            failed_rules=_failed_rules(session, doc),
        )
        for doc in documents
    ]


@router.get("/{document_id}", response_model=ReviewDetailOut)
def get_review_detail(
    document_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
):
    document = _get_document_or_404(session, document_id)
    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    return _detail(session, storage, document, extraction)


@router.post("/{document_id}/correct", response_model=ReviewDetailOut)
def correct_document(
    document_id: uuid.UUID,
    body: ReviewCorrectionIn,
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
):
    document = _get_document_or_404(session, document_id)
    if document.state != DocumentState.NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Document is {document.state}, not NEEDS_REVIEW — cannot correct",
        )

    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="No extraction result for this document")

    if not body.corrections:
        raise HTTPException(status_code=422, detail="At least one correction is required")

    for correction in body.corrections:
        try:
            parsed_value = parse_corrected_value(correction.field_name, correction.corrected_value)
        except (UnknownFieldError, InvalidFieldValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        original_value = getattr(extraction, correction.field_name)
        session.add(
            ReviewEvent(
                document_id=document.id,
                field_name=correction.field_name,
                original_value=None if original_value is None else str(original_value),
                corrected_value=correction.corrected_value,
                reviewer=body.reviewer,
            )
        )
        setattr(extraction, correction.field_name, parsed_value)

    document.state = DocumentState.VALIDATED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.NEEDS_REVIEW,
            to_state=DocumentState.VALIDATED,
            reason=f"corrected by reviewer: {body.reviewer}",
        )
    )
    session.commit()
    session.refresh(document)
    session.refresh(extraction)

    return _detail(session, storage, document, extraction)


@router.post("/{document_id}/reject", response_model=ReviewDetailOut)
def reject_document(
    document_id: uuid.UUID,
    body: ReviewRejectionIn,
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
):
    document = _get_document_or_404(session, document_id)
    if document.state != DocumentState.NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Document is {document.state}, not NEEDS_REVIEW — cannot reject",
        )

    document.state = DocumentState.REJECTED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.NEEDS_REVIEW,
            to_state=DocumentState.REJECTED,
            reason=f"rejected by {body.reviewer}: {body.reason}",
        )
    )
    session.commit()
    session.refresh(document)

    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    return _detail(session, storage, document, extraction)
