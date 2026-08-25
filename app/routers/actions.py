"""Phase 12 — Downstream Accounting Action; Phase 13 — Reliability &
Recovery. See docs/workflow.md step 9 and docs/api.md. No worker exists
yet to trigger this automatically (that's Phase 17's deployment
concern — see docs/adr/0003-worker-model.md); for now it's an explicit,
synchronous endpoint, the same honest simplification Phase 6/7 made for
extraction/validation before a worker existed to do it for them.

Idempotency follows docs/reliability.md's scenario 3: an
`accounting_actions` row is written ATTEMPTED *before* the downstream
write, and committed, so a crash between the two is distinguishable on
resume from "never started."

`_begin_action` (VALIDATED -> ACTIONED, eligibility checks) is split
from `_attempt_action` (the retried provider call + ACTIONED ->
COMPLETED/FAILED) so a worker recovering a document already stuck in
ACTIONED (app/worker.py) can call `_attempt_action` directly without
re-doing or mis-recording the VALIDATED -> ACTIONED transition — same
pattern as app/routers/documents.py's extraction/validation split.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import (
    AccountingProvider,
    NotificationProvider,
    check_action_eligibility,
    get_accounting_provider,
    get_notification_provider,
    notify_with_retry,
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
from app.retry import RetriesExhausted, call_with_retry
from app.schemas import DocumentActionOut

router = APIRouter(prefix="/documents", tags=["actions"], dependencies=[Depends(require_api_key)])


def _begin_action(
    session: Session, document: Document, extraction: ExtractionResult
) -> AccountingAction:
    """VALIDATED -> ACTIONED, after eligibility checks. Raises
    HTTPException on any precondition failure. Returns the (possibly
    newly created) AccountingAction row, ATTEMPTED and committed before
    the caller ever attempts the actual write.
    """
    if document.state != DocumentState.VALIDATED:
        raise HTTPException(
            status_code=409, detail=f"Document is {document.state}, not VALIDATED — cannot action"
        )

    threshold = get_settings().approval_threshold_amount
    has_approval = (
        session.scalar(select(Approval).where(Approval.document_id == document.id)) is not None
    )
    eligibility = check_action_eligibility(
        total=float(extraction.total), threshold=threshold, has_approval=has_approval
    )
    if not eligibility.eligible:
        raise HTTPException(status_code=409, detail=eligibility.reason)

    action = AccountingAction(
        document_id=document.id,
        status=AccountingActionStatus.ATTEMPTED,
        idempotency_key=str(document.id),
    )
    session.add(action)

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
    return action


def _attempt_action(
    session: Session,
    document: Document,
    extraction: ExtractionResult,
    action: AccountingAction,
    *,
    accounting: AccountingProvider,
    notifier: NotificationProvider,
) -> tuple[bool, bool]:
    """Assumes `document.state` is already ACTIONED and `action` is
    ATTEMPTED (see `_begin_action`). Retries the accounting write with
    bounded backoff (docs/reliability.md); on exhaustion moves the
    document to FAILED, sends a best-effort alert, and returns
    `(False, False)` — the caller turns that into a 502, so the second
    value (whether the alert itself landed) is never surfaced to a
    client. On success, moves the document to COMPLETED, sends a
    best-effort completion notification, and returns
    `(True, notification_sent)`.
    """
    settings = get_settings()
    try:
        external_reference = call_with_retry(
            lambda: accounting.create_payable(
                session=session,
                document_id=document.id,
                vendor_name=extraction.vendor_name,
                invoice_number=extraction.invoice_number,
                invoice_date=extraction.invoice_date,
                due_date=extraction.due_date,
                currency=extraction.currency,
                total=extraction.total,
            ),
            attempts=settings.retry_attempts,
        )
    except RetriesExhausted as exc:
        action.status = AccountingActionStatus.FAILED
        document.state = DocumentState.FAILED
        session.add(
            StateHistory(
                document_id=document.id,
                from_state=DocumentState.ACTIONED,
                to_state=DocumentState.FAILED,
                # Exception TYPE only, never its message — see
                # docs/security.md's "Secret-safe debugging practice".
                # MockAccountingProvider isn't credentialed today, but a
                # future real adapter (Xero/QuickBooks, Phase 19) would
                # be, and this code path shouldn't need to change then.
                reason=(
                    f"accounting write failed after {exc.attempts} attempt(s), "
                    f"last error type: {type(exc.last_error).__name__}"
                ),
            )
        )
        session.commit()
        notify_with_retry(
            notifier,
            subject="Document accounting write dead-lettered",
            message=(
                f"Document {document.id} failed the accounting write "
                f"after {exc.attempts} attempt(s)."
            ),
        )
        return False, False

    action.status = AccountingActionStatus.CONFIRMED
    action.external_reference = external_reference
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
    session.refresh(action)

    notification_sent = notify_with_retry(
        notifier,
        subject=f"Invoice actioned: {extraction.invoice_number}",
        message=(
            f"Document {document.id} (invoice {extraction.invoice_number}, "
            f"{extraction.currency} {extraction.total}) has been recorded in the "
            f"AP ledger — reference {external_reference}."
        ),
    )
    return True, notification_sent


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
        # CONFIRMED) — resuming that specific case is app/worker.py's
        # job (Phase 13), not this synchronous endpoint's. Left as an
        # honest 409 rather than silently retried here.
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

    action = _begin_action(session, document, extraction)
    succeeded, notification_sent = _attempt_action(
        session, document, extraction, action, accounting=accounting, notifier=notifier
    )
    if not succeeded:
        raise HTTPException(status_code=502, detail="Downstream accounting write failed")

    return DocumentActionOut(
        document=document, accounting_action=action, notification_sent=notification_sent
    )
