"""Phase 12 — Downstream Accounting Action. See docs/workflow.md step 9
and docs/architecture.md's adapter boundary: `AccountingProvider` and
`NotificationProvider` are both external dependencies behind small
interfaces, exactly like `ExtractionProvider`/`StorageProvider`.

`MockAccountingProvider` posts to an internal PostgreSQL table
(`ap_ledger_entries`, app/models.py) shaped like a real AP ledger,
per docs/architecture.md, "Mock ledger vs. real integration" — a real
Xero/QuickBooks adapter is explicitly Phase 19 stretch scope, not
built here.

`LogNotificationProvider` is the only NotificationProvider implemented:
a real SMTP adapter is deferred the same way a real accounting adapter
is — .env.example documents the SMTP_* variables a future
implementation would consume, but nothing here reads them yet, and no
real email is ever sent. See docs/reliability.md: a notification
failure is low-stakes and must never block the pipeline, so logging is
an honest MVP behavior, not a placeholder pretending to be more.

`check_action_eligibility` is pure — no I/O, no DB session.

`notify_with_retry` implements docs/reliability.md's notification-failure
row ("retry briefly, then log and continue — never block the pipeline")
using the same bounded-backoff primitive (app/retry.py) the provider
calls use, just with fewer attempts and a shorter delay.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from app.approval import requires_approval
from app.config import get_settings
from app.models import ApLedgerEntry
from app.retry import RetriesExhausted, call_with_retry

logger = logging.getLogger(__name__)


@dataclass
class ActionEligibility:
    eligible: bool
    reason: str


def check_action_eligibility(
    *, total: float, threshold: float, has_approval: bool
) -> ActionEligibility:
    """A VALIDATED document is eligible for the downstream action unless
    it's above the approval threshold and hasn't been approved yet. A
    document whose approval was *rejected* never reaches this check in
    the first place — rejection already moves it out of VALIDATED (see
    app/routers/approvals.py) — so there is no separate "was rejected"
    branch here.
    """
    requirement = requires_approval(total=total, threshold=threshold)
    if requirement.required and not has_approval:
        return ActionEligibility(False, f"awaiting approval: {requirement.reason}")
    return ActionEligibility(True, "eligible for the downstream accounting action")


class AccountingProvider(Protocol):
    def create_payable(
        self,
        *,
        session: Session,
        document_id: uuid.UUID,
        vendor_name: str,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None,
        currency: str,
        total: float,
    ) -> str:
        """Creates a payable record downstream; returns an opaque external
        reference id. Never executes a payment — see docs/api.md,
        "Explicitly not planned."
        """
        ...


class NotificationProvider(Protocol):
    def notify(self, *, subject: str, message: str) -> None:
        """Best-effort — a failure here must never block or roll back the
        accounting write. See docs/reliability.md.
        """
        ...


class MockAccountingProvider:
    """MVP's only AccountingProvider. See module docstring."""

    def create_payable(
        self,
        *,
        session: Session,
        document_id: uuid.UUID,
        vendor_name: str,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None,
        currency: str,
        total: float,
    ) -> str:
        entry = ApLedgerEntry(
            document_id=document_id,
            vendor_name=vendor_name,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            currency=currency,
            total=total,
        )
        session.add(entry)
        session.flush()
        return str(entry.id)


class LogNotificationProvider:
    """MVP's only NotificationProvider. See module docstring — a real
    SMTP implementation is deferred, not stubbed out silently.
    """

    def notify(self, *, subject: str, message: str) -> None:
        # Log only, per docs/security.md: never log full document text or
        # financial detail beyond what's already in `message` (callers are
        # responsible for keeping that to IDs/amounts, not raw extracted
        # text).
        logger.info("notification: %s — %s", subject, message)


def get_accounting_provider() -> AccountingProvider:
    return MockAccountingProvider()


def get_notification_provider() -> NotificationProvider:
    return LogNotificationProvider()


def notify_with_retry(notifier: NotificationProvider, *, subject: str, message: str) -> bool:
    """Best-effort notification: retries briefly, then gives up without
    raising — a notification must never block or unwind a state
    transition. Returns whether it ultimately succeeded, so callers can
    surface that (e.g. `DocumentActionOut.notification_sent`) without
    treating it as an error.
    """
    settings = get_settings()
    try:
        call_with_retry(
            lambda: notifier.notify(subject=subject, message=message),
            attempts=settings.notification_retry_attempts,
        )
        return True
    except RetriesExhausted as exc:
        logger.warning(
            "notification failed after %d attempt(s): %s — %s",
            exc.attempts,
            subject,
            exc.last_error,
        )
        return False
