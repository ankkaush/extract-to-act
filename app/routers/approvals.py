"""Phase 11 — Approval Workflow. See docs/workflow.md step 8 and
docs/api.md. Separate from Phase 10's data-quality review: a VALIDATED
document at or above `APPROVAL_THRESHOLD_AMOUNT` needs a person's
sign-off before any downstream action, regardless of how confidently it
was extracted and validated.

Approval deliberately does **not** transition document.state — an
approved document stays VALIDATED; the resulting `approvals` row
(unique per document) is the signal a later worker (Phase 12/13, not
built yet) checks before writing to accounting. No new "pending
approval" state was added for this — see docs/state-machine.md, which
was written to route that decision entirely through this table, not a
document state. Rejection is the one case that does transition state,
since a rejected invoice is genuinely finished, not just waiting on
someone: VALIDATED -> REJECTED, a new transition documented in
docs/state-machine.md alongside Phase 10's NEEDS_REVIEW -> REJECTED.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval import requires_approval
from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.models import (
    Approval,
    ApprovalDecision,
    Document,
    DocumentState,
    ExtractionResult,
    StateHistory,
)
from app.schemas import (
    ApprovalActionOut,
    ApprovalDecisionIn,
    ApprovalQueueItemOut,
    ApprovalRejectionIn,
)

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_api_key)])


def _get_document_or_404(session: Session, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _get_extraction_with_total(session: Session, document_id: uuid.UUID) -> ExtractionResult:
    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    if extraction is None or extraction.total is None:
        raise HTTPException(
            status_code=404, detail="No extraction result with a total for this document"
        )
    return extraction


def _require_approval_eligible(session: Session, document: Document, extraction: ExtractionResult):
    threshold = get_settings().approval_threshold_amount
    requirement = requires_approval(total=float(extraction.total), threshold=threshold)
    if not requirement.required:
        raise HTTPException(
            status_code=409, detail=f"Document does not require approval: {requirement.reason}"
        )

    existing = session.scalar(select(Approval).where(Approval.document_id == document.id))
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="This document already has an approval decision"
        )

    return threshold


@router.get("", response_model=list[ApprovalQueueItemOut])
def list_pending_approvals(session: Session = Depends(get_session)):
    threshold = get_settings().approval_threshold_amount
    documents = session.scalars(
        select(Document)
        .where(Document.state == DocumentState.VALIDATED)
        .order_by(Document.created_at.asc())
    ).all()

    pending = []
    for document in documents:
        extraction = session.scalar(
            select(ExtractionResult).where(ExtractionResult.document_id == document.id)
        )
        if extraction is None or extraction.total is None:
            continue
        requirement = requires_approval(total=float(extraction.total), threshold=threshold)
        if not requirement.required:
            continue
        existing = session.scalar(select(Approval).where(Approval.document_id == document.id))
        if existing is not None:
            continue
        pending.append(
            ApprovalQueueItemOut(
                id=document.id,
                original_filename=document.original_filename,
                total=float(extraction.total),
                created_at=document.created_at,
                reason=requirement.reason,
            )
        )
    return pending


@router.post("/{document_id}/approve", response_model=ApprovalActionOut)
def approve_document(
    document_id: uuid.UUID, body: ApprovalDecisionIn, session: Session = Depends(get_session)
):
    document = _get_document_or_404(session, document_id)
    if document.state != DocumentState.VALIDATED:
        raise HTTPException(
            status_code=409, detail=f"Document is {document.state}, not VALIDATED — cannot approve"
        )
    extraction = _get_extraction_with_total(session, document_id)
    threshold = _require_approval_eligible(session, document, extraction)

    approval = Approval(
        document_id=document.id,
        amount=extraction.total,
        threshold_applied=threshold,
        approver=body.approver,
        decision=ApprovalDecision.APPROVED,
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)
    session.refresh(document)

    return ApprovalActionOut(document=document, approval=approval)


@router.post("/{document_id}/reject", response_model=ApprovalActionOut)
def reject_document(
    document_id: uuid.UUID, body: ApprovalRejectionIn, session: Session = Depends(get_session)
):
    document = _get_document_or_404(session, document_id)
    if document.state != DocumentState.VALIDATED:
        raise HTTPException(
            status_code=409, detail=f"Document is {document.state}, not VALIDATED — cannot reject"
        )
    extraction = _get_extraction_with_total(session, document_id)
    threshold = _require_approval_eligible(session, document, extraction)

    approval = Approval(
        document_id=document.id,
        amount=extraction.total,
        threshold_applied=threshold,
        approver=body.approver,
        decision=ApprovalDecision.REJECTED,
    )
    session.add(approval)

    document.state = DocumentState.REJECTED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.VALIDATED,
            to_state=DocumentState.REJECTED,
            reason=f"approval rejected by {body.approver}: {body.reason}",
        )
    )
    session.commit()
    session.refresh(approval)
    session.refresh(document)

    return ApprovalActionOut(document=document, approval=approval)
