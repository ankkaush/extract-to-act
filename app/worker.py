"""Phase 13 — the scheduled polling worker described in
docs/adr/0003-worker-model.md. Scans for documents stuck in an
in-flight state (EXTRACTING, VALIDATING, ACTIONED) longer than
`worker_stuck_timeout_seconds` and resumes each from exactly where it
left off — never reprocessed from RECEIVED, matching
docs/state-machine.md's crash-recovery section — by calling the same
`_attempt_*` functions the synchronous request path already uses
(app/routers/documents.py, app/routers/actions.py).

Each recovery attempt increments `Document.retry_count`; once that
exceeds `worker_max_retries`, the document is dead-lettered (-> FAILED,
with a best-effort alert) instead of being retried again on the next
poll. In practice this rarely triggers from a plain provider outage —
`_attempt_extraction`/`_attempt_action` already exhaust their own
in-call retry-with-backoff (app/retry.py) and self-dead-letter before
ever returning "still stuck." `retry_count` instead bounds the rarer,
uglier case: the worker process itself dying *again* mid-recovery
(OOM, a poison-pill document whose storage read throws) — without it,
that failure mode would retry forever.

Run as a standalone process: `python -m app.worker`. Scheduling it (a
loop, a cron job, a Render background worker) is a deployment decision
— Phase 17's job, not this phase's; `run_once()` is what's tested here.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import (
    AccountingProvider,
    NotificationProvider,
    get_accounting_provider,
    get_notification_provider,
    notify_with_retry,
)
from app.config import get_settings
from app.db import SessionLocal
from app.extraction import ExtractionProvider
from app.models import AccountingAction, Document, DocumentState, ExtractionResult, StateHistory
from app.routers.actions import _attempt_action
from app.routers.documents import (
    _attempt_extraction,
    _attempt_validation,
    _begin_validation,
    get_extraction_provider,
    get_storage_provider,
)
from app.storage import StorageProvider

logger = logging.getLogger(__name__)

STUCK_STATES = (DocumentState.EXTRACTING, DocumentState.VALIDATING, DocumentState.ACTIONED)


def find_stuck_documents(
    session: Session, *, now: datetime, timeout_seconds: int
) -> list[Document]:
    """Anything in an in-flight state whose last transition is older
    than the timeout — see docs/state-machine.md's crash-recovery
    section. `updated_at` is bumped by every state-changing commit, so
    this is exactly "hasn't moved in `timeout_seconds`."
    """
    cutoff = now - timedelta(seconds=timeout_seconds)
    return list(
        session.scalars(
            select(Document)
            .where(Document.state.in_(STUCK_STATES))
            .where(Document.updated_at < cutoff)
            .order_by(Document.updated_at.asc())
        ).all()
    )


def _dead_letter(session: Session, document: Document, notifier: NotificationProvider) -> None:
    from_state = document.state
    document.state = DocumentState.FAILED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=from_state,
            to_state=DocumentState.FAILED,
            reason=f"worker gave up after {document.retry_count} recovery attempt(s)",
        )
    )
    session.commit()
    notify_with_retry(
        notifier,
        subject="Document dead-lettered by worker",
        message=(
            f"Document {document.id} moved to FAILED after {document.retry_count} "
            f"worker recovery attempt(s) from {from_state}."
        ),
    )


def recover_document(
    session: Session,
    document: Document,
    *,
    storage: StorageProvider,
    extraction_provider: ExtractionProvider,
    accounting_provider: AccountingProvider,
    notifier: NotificationProvider,
) -> None:
    """Resumes a single stuck document. Assumes it's actually stuck —
    callers filter via `find_stuck_documents`, this does not re-check
    the timeout itself.
    """
    settings = get_settings()
    if document.retry_count >= settings.worker_max_retries:
        _dead_letter(session, document, notifier)
        return

    document.retry_count += 1
    session.commit()

    if document.state == DocumentState.EXTRACTING:
        content = storage.get(storage_path=document.storage_path)
        extraction_result = _attempt_extraction(
            session, document, content=content, provider=extraction_provider, notifier=notifier
        )
        if extraction_result is not None:
            _begin_validation(session, document)
            _attempt_validation(session, document, extraction_result)
        return

    if document.state == DocumentState.VALIDATING:
        extraction_result = session.scalar(
            select(ExtractionResult).where(ExtractionResult.document_id == document.id)
        )
        if extraction_result is None:
            # Shouldn't happen — VALIDATING is only ever reached after a
            # committed ExtractionResult — but dead-letter loudly rather
            # than crash the poll pass on a None.
            _dead_letter(session, document, notifier)
            return
        _attempt_validation(session, document, extraction_result)
        return

    if document.state == DocumentState.ACTIONED:
        extraction_result = session.scalar(
            select(ExtractionResult).where(ExtractionResult.document_id == document.id)
        )
        action = session.scalar(
            select(AccountingAction).where(AccountingAction.document_id == document.id)
        )
        if extraction_result is None or action is None:
            _dead_letter(session, document, notifier)
            return
        _attempt_action(
            session,
            document,
            extraction_result,
            action,
            accounting=accounting_provider,
            notifier=notifier,
        )
        return


def run_once(session: Session | None = None) -> int:
    """One polling pass: recovers every currently-stuck document. A
    single document's recovery raising an unexpected error (e.g. a
    poison-pill storage read) is caught and logged rather than aborting
    the whole pass — that document's already-incremented retry_count
    still bounds it via the next pass's dead-letter check. Returns how
    many stuck documents were found (attempted, not necessarily
    resolved — a still-down provider legitimately fails again).
    """
    settings = get_settings()
    owns_session = session is None
    session = session or SessionLocal()
    try:
        stuck = find_stuck_documents(
            session, now=datetime.now(UTC), timeout_seconds=settings.worker_stuck_timeout_seconds
        )
        storage = get_storage_provider()
        extraction_provider = get_extraction_provider()
        accounting_provider = get_accounting_provider()
        notifier = get_notification_provider()
        for document in stuck:
            try:
                recover_document(
                    session,
                    document,
                    storage=storage,
                    extraction_provider=extraction_provider,
                    accounting_provider=accounting_provider,
                    notifier=notifier,
                )
            except Exception:  # noqa: BLE001 — one bad document must not halt the whole poll pass
                logger.exception("recovery raised for document %s", document.id)
                session.rollback()
        return len(stuck)
    finally:
        if owns_session:
            session.close()


def main() -> None:  # pragma: no cover — trivial loop wrapper, not itself unit tested
    logging.basicConfig(level=logging.INFO)
    poll_interval_seconds = 30
    logger.info("worker starting, polling every %ds", poll_interval_seconds)
    while True:
        recovered = run_once()
        if recovered:
            logger.info("processed %d stuck document(s)", recovered)
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":  # pragma: no cover
    main()
