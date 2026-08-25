"""Tier 2-ish tests for Phase 13's scheduled worker (app/worker.py).
Real Postgres (via db_session, see conftest.py). Crashes are simulated
exactly as docs/testing-strategy.md describes: a stuck in-flight state
is written directly to the database, never by actually killing a
process, and the test asserts the worker recovers it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.extraction import ExtractedField, ExtractionOutput, build_extraction_result
from app.models import (
    AccountingAction,
    AccountingActionStatus,
    Document,
    DocumentState,
    StateHistory,
    Vendor,
)
from app.vendor_matching import normalize_vendor_name
from app.worker import find_stuck_documents, recover_document, run_once

VALID_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-1"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=100.0),
    "tax": ExtractedField(value=8.0),
    "total": ExtractedField(value=108.0),
}


def _output() -> ExtractionOutput:
    return ExtractionOutput(
        provider_name="fake", model_version="fake-1", fields=dict(VALID_FIELDS)
    )


class FakeExtractionProvider:
    def __init__(self, *, error: Exception | None = None):
        self._error = error

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        if self._error is not None:
            raise self._error
        return _output()


class FakeStorage:
    def __init__(self, content: bytes = b"%PDF-1.4\nfake"):
        self._content = content

    def get(self, *, storage_path: str) -> bytes:
        return self._content

    def put(self, *, content, suggested_name):  # pragma: no cover — unused here
        raise NotImplementedError

    def sign_url(self, *, storage_path, expires_in=300):  # pragma: no cover — unused here
        raise NotImplementedError


class FakeAccountingProvider:
    def __init__(self, *, error: Exception | None = None):
        self._error = error

    def create_payable(self, *, session, **kwargs) -> str:
        if self._error is not None:
            raise self._error
        return "ext-ref-1"


class RecordingNotificationProvider:
    def __init__(self):
        self.sent = []

    def notify(self, *, subject: str, message: str) -> None:
        self.sent.append((subject, message))


def _make_document(
    db_session, *, state: DocumentState, updated_at: datetime, retry_count: int = 0
) -> Document:
    document = Document(
        content_hash=f"hash-{state}-{updated_at.timestamp()}",
        idempotency_key=f"key-{state}-{updated_at.timestamp()}",
        storage_path="fake.pdf",
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        state=state,
        retry_count=retry_count,
        updated_at=updated_at,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        StateHistory(document_id=document.id, from_state=None, to_state=state, reason="test setup")
    )
    db_session.commit()
    return document


@pytest.fixture
def old_timestamp():
    return datetime.now(UTC) - timedelta(seconds=600)


@pytest.fixture
def recent_timestamp():
    return datetime.now(UTC) - timedelta(seconds=5)


def test_find_stuck_documents_finds_old_in_flight_states(db_session, old_timestamp):
    stuck = _make_document(db_session, state=DocumentState.EXTRACTING, updated_at=old_timestamp)

    found = find_stuck_documents(db_session, now=datetime.now(UTC), timeout_seconds=300)

    assert [d.id for d in found] == [stuck.id]


def test_find_stuck_documents_excludes_recent_in_flight_states(db_session, recent_timestamp):
    _make_document(db_session, state=DocumentState.EXTRACTING, updated_at=recent_timestamp)

    found = find_stuck_documents(db_session, now=datetime.now(UTC), timeout_seconds=300)

    assert found == []


def test_find_stuck_documents_excludes_terminal_states(db_session, old_timestamp):
    _make_document(db_session, state=DocumentState.COMPLETED, updated_at=old_timestamp)
    _make_document(db_session, state=DocumentState.FAILED, updated_at=old_timestamp)

    found = find_stuck_documents(db_session, now=datetime.now(UTC), timeout_seconds=300)

    assert found == []


def test_recover_extracting_document_succeeds_through_to_validated(db_session, old_timestamp):
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    db_session.commit()
    document = _make_document(db_session, state=DocumentState.EXTRACTING, updated_at=old_timestamp)
    notifier = RecordingNotificationProvider()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        extraction_provider=FakeExtractionProvider(),
        accounting_provider=FakeAccountingProvider(),
        notifier=notifier,
    )

    assert document.state == DocumentState.VALIDATED
    assert document.retry_count == 1
    assert notifier.sent == []


def test_recover_extracting_document_dead_letters_on_persistent_provider_failure(
    db_session, old_timestamp
):
    document = _make_document(db_session, state=DocumentState.EXTRACTING, updated_at=old_timestamp)
    notifier = RecordingNotificationProvider()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        extraction_provider=FakeExtractionProvider(error=RuntimeError("provider down")),
        accounting_provider=FakeAccountingProvider(),
        notifier=notifier,
    )

    # _attempt_extraction's own in-call retries (RETRY_ATTEMPTS) already
    # exhaust within this single recovery attempt — the document reaches
    # FAILED immediately, it doesn't stay "stuck" for another poll.
    assert document.state == DocumentState.FAILED
    assert len(notifier.sent) == 1
    assert "dead-lettered" in notifier.sent[0][0]


def test_recover_validating_document_resumes_without_provider_call(db_session, old_timestamp):
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    document = _make_document(db_session, state=DocumentState.VALIDATING, updated_at=old_timestamp)
    output = _output()
    extraction_result = build_extraction_result(document.id, output)
    db_session.add(extraction_result)
    db_session.commit()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        # A provider that would blow up if called — proves VALIDATING
        # recovery never touches extraction at all.
        extraction_provider=FakeExtractionProvider(error=RuntimeError("must not be called")),
        accounting_provider=FakeAccountingProvider(),
        notifier=RecordingNotificationProvider(),
    )

    assert document.state == DocumentState.VALIDATED


def test_recover_actioned_document_completes_idempotency_row(db_session, old_timestamp):
    document = _make_document(db_session, state=DocumentState.ACTIONED, updated_at=old_timestamp)
    output = _output()
    extraction_result = build_extraction_result(document.id, output)
    db_session.add(extraction_result)
    action = AccountingAction(
        document_id=document.id,
        status=AccountingActionStatus.ATTEMPTED,
        idempotency_key=str(document.id),
    )
    db_session.add(action)
    db_session.commit()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        extraction_provider=FakeExtractionProvider(),
        accounting_provider=FakeAccountingProvider(),
        notifier=RecordingNotificationProvider(),
    )

    assert document.state == DocumentState.COMPLETED
    assert action.status == AccountingActionStatus.CONFIRMED
    assert action.external_reference == "ext-ref-1"


def test_recover_actioned_document_fails_on_persistent_accounting_failure(
    db_session, old_timestamp
):
    document = _make_document(db_session, state=DocumentState.ACTIONED, updated_at=old_timestamp)
    output = _output()
    extraction_result = build_extraction_result(document.id, output)
    db_session.add(extraction_result)
    action = AccountingAction(
        document_id=document.id,
        status=AccountingActionStatus.ATTEMPTED,
        idempotency_key=str(document.id),
    )
    db_session.add(action)
    db_session.commit()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        extraction_provider=FakeExtractionProvider(),
        accounting_provider=FakeAccountingProvider(error=RuntimeError("ledger down")),
        notifier=RecordingNotificationProvider(),
    )

    assert document.state == DocumentState.FAILED
    assert action.status == AccountingActionStatus.FAILED


def test_recover_document_at_retry_cap_dead_letters_without_attempting(db_session, old_timestamp):
    document = _make_document(
        db_session, state=DocumentState.EXTRACTING, updated_at=old_timestamp, retry_count=3
    )
    notifier = RecordingNotificationProvider()

    recover_document(
        db_session,
        document,
        storage=FakeStorage(),
        # Would succeed if called — proves the cap short-circuits before
        # ever attempting extraction again.
        extraction_provider=FakeExtractionProvider(),
        accounting_provider=FakeAccountingProvider(),
        notifier=notifier,
    )

    assert document.state == DocumentState.FAILED
    assert document.retry_count == 3  # not incremented — dead-lettered, not attempted
    assert len(notifier.sent) == 1
    assert "dead-lettered" in notifier.sent[0][0]
    assert "moved to FAILED" in notifier.sent[0][1]

    # Not ordered by created_at: within this test's single outer
    # transaction, Postgres's now() is transaction-scoped, not
    # statement-scoped, so every row here can share one timestamp —
    # existence, not recency, is what's actually being asserted.
    history_reasons = db_session.scalars(
        select(StateHistory.reason).where(StateHistory.document_id == document.id)
    ).all()
    assert any("worker gave up" in reason for reason in history_reasons if reason)


def test_run_once_recovers_multiple_stuck_documents_and_isolates_failures(
    db_session, old_timestamp, monkeypatch
):
    good = _make_document(db_session, state=DocumentState.VALIDATING, updated_at=old_timestamp)
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    good_output = _output()
    db_session.add(build_extraction_result(good.id, good_output))
    db_session.commit()

    bad = _make_document(db_session, state=DocumentState.EXTRACTING, updated_at=old_timestamp)

    class ExplodingStorage(FakeStorage):
        def get(self, *, storage_path: str) -> bytes:
            raise OSError("disk gone")

    import app.worker as worker_module

    monkeypatch.setattr(worker_module, "get_storage_provider", lambda: ExplodingStorage())
    monkeypatch.setattr(worker_module, "get_extraction_provider", FakeExtractionProvider)
    monkeypatch.setattr(worker_module, "get_accounting_provider", FakeAccountingProvider)
    monkeypatch.setattr(worker_module, "get_notification_provider", RecordingNotificationProvider)

    count = run_once(db_session)

    assert count == 2
    db_session.refresh(good)
    assert good.state == DocumentState.VALIDATED
    # `bad` raised inside recovery (storage.get) — isolated, doesn't
    # crash the pass, and its own state is left for the next poll.
    db_session.refresh(bad)
    assert bad.retry_count == 1
