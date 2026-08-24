"""Model/schema-level tests. Needs a real (local, free) Postgres — see
tests/conftest.py. Not a Tier 3/4 "real provider" test.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Document, DocumentState, StateHistory


def _make_document(**overrides) -> Document:
    defaults = dict(
        content_hash="a" * 64,
        idempotency_key=str(uuid.uuid4()),
        storage_path="local/some-file.pdf",
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        state=DocumentState.RECEIVED,
    )
    defaults.update(overrides)
    return Document(**defaults)


def test_document_round_trip(db_session):
    doc = _make_document()
    db_session.add(doc)
    db_session.flush()

    fetched = db_session.get(Document, doc.id)
    assert fetched is not None
    assert fetched.state == DocumentState.RECEIVED
    assert fetched.original_filename == "invoice.pdf"


def test_idempotency_key_must_be_unique(db_session):
    key = str(uuid.uuid4())
    db_session.add(_make_document(idempotency_key=key))
    db_session.flush()

    db_session.add(_make_document(idempotency_key=key))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_state_history_requires_an_existing_document(db_session):
    """A crash-recovery/audit row can't reference a document that doesn't
    exist — see docs/data-model.md on state_history being the backbone of
    both audit and crash recovery.
    """
    orphan_entry = StateHistory(
        document_id=uuid.uuid4(),  # no such document
        from_state=None,
        to_state=DocumentState.RECEIVED,
    )
    db_session.add(orphan_entry)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_state_history_is_append_only_by_convention(db_session):
    """Not a DB-enforced constraint (see docs/state-machine.md) — this
    documents the expected usage pattern: each transition is a new row,
    not an update to a prior one.
    """
    doc = _make_document()
    db_session.add(doc)
    db_session.flush()

    db_session.add(
        StateHistory(document_id=doc.id, from_state=None, to_state=DocumentState.RECEIVED)
    )
    db_session.add(
        StateHistory(
            document_id=doc.id,
            from_state=DocumentState.RECEIVED,
            to_state=DocumentState.EXTRACTING,
        )
    )
    db_session.flush()

    history = (
        db_session.query(StateHistory)
        .filter_by(document_id=doc.id)
        .order_by(StateHistory.created_at)
        .all()
    )
    assert [h.to_state for h in history] == [DocumentState.RECEIVED, DocumentState.EXTRACTING]
