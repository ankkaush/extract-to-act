"""Phase 12 — Downstream Accounting Action. See docs/workflow.md step 9
and docs/api.md. No worker exists yet to trigger this automatically
(that's Phase 13 — see docs/adr/0003-worker-model.md); for now it's an
explicit, synchronous endpoint, the same honest simplification Phase
6/7 made for extraction/validation before a worker existed to do it
for them.

Idempotency follows docs/reliability.md's scenario 3: an
`accounting_actions` row is written ATTEMPTED *before* the downstream
write, and committed, so a crash between the two is distinguishable on
resume from "never started" — full resume/retry logic is Phase 13's
job, but the row this endpoint writes is what that logic will read.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import (
    AccountingProvider,
    LogNotificationProvider,
    MockAccountingProvider,
    NotificationProvider,
    check_action_eligibility,
)
from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.models import (
    AccountingAction,
    AccountingActionStatus,
    Approval,
    Document,
    DocumentState,
    ExtractionResult,
    StateHistory,
)
from app.schemas import DocumentActionOut

router = APIRouter(prefix="/documents", tags=["actions"], dependencies=[Depends(require_api_key)])


def get_accounting_provider() -> AccountingProvider:
    return MockAccountingProvider()


def get_notification_provider() -> NotificationProvider:
    return LogNotificationProvider()


@router.post("/{document_id}/action", response_model=DocumentActionOut)
def action_document(
    document_id: uuid.UUID,
    session: Session = Depends(get_session),
    accounting: AccountingProvider = Depends(get_accounting_provider),
    notifier: NotificationProvider = Depends(get_notification_provider),
):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    existing_action = session.scalar(
        select(AccountingAction).where(AccountingAction.document_id == document_id)
    )
    if existing_action is not None and existing_action.status == AccountingActionStatus.CONFIRMED:
        # Idempotent replay — already actioned, never write twice.
        return DocumentActionOut(
            document=document,
            accounting_action=existing_action,
            notification_sent=False,
        )

    if document.state != DocumentState.VALIDATED:
        # Includes the case of a document stuck in ACTIONED from a prior
        # crashed attempt (existing_action.status == ATTEMPTED but not
        # CONFIRMED) — resuming that specific case is Phase 13's job (the
        # scheduled worker that scans for anything not in a terminal
        # state, docs/state-machine.md), not this synchronous endpoint's.
        # Left as an honest 409 rather than silently retried here.
        raise HTTPException(
            status_code=409, detail=f"Document is {document.state}, not VALIDATED — cannot action"
        )

    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    if extraction is None or extraction.total is None:
        raise HTTPException(
            status_code=404, detail="No extraction result with a total for this document"
        )

    threshold = get_settings().approval_threshold_amount
    has_approval = (
        session.scalar(select(Approval).where(Approval.document_id == document_id)) is not None
    )
    eligibility = check_action_eligibility(
        total=float(extraction.total), threshold=threshold, has_approval=has_approval
    )
    if not eligibility.eligible:
        raise HTTPException(status_code=409, detail=eligibility.reason)

    if existing_action is None:
        existing_action = AccountingAction(
            document_id=document.id,
            status=AccountingActionStatus.ATTEMPTED,
            idempotency_key=str(document.id),
        )
        session.add(existing_action)

    document.state = DocumentState.ACTIONED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.VALIDATED,
            to_state=DocumentState.ACTIONED,
            reason="downstream accounting write attempted",
        )
    )
    session.commit()

    try:
        external_reference = accounting.create_payable(
            session=session,
            document_id=document.id,
            vendor_name=extraction.vendor_name,
            invoice_number=extraction.invoice_number,
            invoice_date=extraction.invoice_date,
            due_date=extraction.due_date,
            currency=extraction.currency,
            total=extraction.total,
        )
    except Exception as exc:  # noqa: BLE001 — recorded as a dead-lettered failure, not re-raised
        existing_action.status = AccountingActionStatus.FAILED
        document.state = DocumentState.FAILED
        session.add(
            StateHistory(
                document_id=document.id,
                from_state=DocumentState.ACTIONED,
                to_state=DocumentState.FAILED,
                reason=f"accounting write failed: {type(exc).__name__}: {exc}",
            )
        )
        session.commit()
        raise HTTPException(status_code=502, detail="Downstream accounting write failed") from exc

    existing_action.status = AccountingActionStatus.CONFIRMED
    existing_action.external_reference = external_reference
    document.state = DocumentState.COMPLETED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.ACTIONED,
            to_state=DocumentState.COMPLETED,
            reason="downstream accounting write confirmed",
        )
    )
    session.commit()
    session.refresh(document)
    session.refresh(existing_action)

    notification_sent = True
    try:
        notifier.notify(
            subject=f"Invoice actioned: {extraction.invoice_number}",
            message=(
                f"Document {document.id} (invoice {extraction.invoice_number}, "
                f"{extraction.currency} {extraction.total}) has been recorded in the "
                f"AP ledger — reference {external_reference}."
            ),
        )
    except Exception:  # noqa: BLE001 — never block the pipeline on a notification
        notification_sent = False

    return DocumentActionOut(
        document=document, accounting_action=existing_action, notification_sent=notification_sent
    )
