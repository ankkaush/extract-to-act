"""Tier 2-ish integration tests for Phase 11 — Approval Workflow. Real
Postgres (via db_session, see conftest.py), local disk storage in a temp
dir, no external provider — extraction is always faked, so no test here
ever makes a real network call. See docs/testing-strategy.md.

Uses the default APPROVAL_THRESHOLD_AMOUNT (1000.0, app/config.py) —
tests pick totals comfortably above/below it rather than overriding
settings, so nothing here depends on environment configuration.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.extraction import ExtractedField, ExtractionOutput
from app.main import app
from app.models import Approval, ApprovalDecision, DocumentState, StateHistory, Vendor
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider
from app.vendor_matching import normalize_vendor_name

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}

# Comfortably above the default 1000.0 threshold, arithmetic-consistent
# so it reaches VALIDATED untouched and lands straight in the approval
# queue.
ABOVE_THRESHOLD_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-5000"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=4629.63),
    "tax": ExtractedField(value=370.37),
    "total": ExtractedField(value=5000.0),
}

# Comfortably below the threshold — should never appear in the queue.
BELOW_THRESHOLD_FIELDS = {
    **ABOVE_THRESHOLD_FIELDS,
    "invoice_number": ExtractedField(value="INV-5001"),
    "subtotal": ExtractedField(value=92.59),
    "tax": ExtractedField(value=7.41),
    "total": ExtractedField(value=100.0),
}


class FakeExtractionProvider:
    def __init__(self, *, output: ExtractionOutput | None = None):
        self._output = output

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        return self._output or ExtractionOutput(
            provider_name="fake", model_version="fake-1", fields=dict(ABOVE_THRESHOLD_FIELDS)
        )


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path, secret_key="test-secret"
    )
    app.dependency_overrides[documents_router.get_extraction_provider] = FakeExtractionProvider
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    db_session.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _upload(
    client, *, fields: dict, filename: str = "invoice.pdf", content: bytes = PDF_BYTES
) -> dict:
    output = ExtractionOutput(provider_name="fake", model_version="fake-1", fields=dict(fields))
    app.dependency_overrides[documents_router.get_extraction_provider] = (
        lambda: FakeExtractionProvider(output=output)
    )
    response = client.post(
        "/documents",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 201
    return response.json()


def test_approval_queue_lists_validated_document_above_threshold(client):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)
    assert document["state"] == DocumentState.VALIDATED

    response = client.get("/approvals", headers=AUTH_HEADER)

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == document["id"]
    assert items[0]["total"] == 5000.0
    assert "5000.00" in items[0]["reason"]


def test_approval_queue_excludes_document_under_threshold(client):
    document = _upload(
        client, fields=BELOW_THRESHOLD_FIELDS, filename="small.pdf", content=PDF_BYTES + b"\nA"
    )
    assert document["state"] == DocumentState.VALIDATED

    response = client.get("/approvals", headers=AUTH_HEADER)

    assert response.json() == []


def test_approval_queue_excludes_document_already_decided(client, db_session):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)

    approve_response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )
    assert approve_response.status_code == 200

    response = client.get("/approvals", headers=AUTH_HEADER)
    assert response.json() == []


def test_approve_document_writes_approval_and_leaves_state_validated(client, db_session):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)

    response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["state"] == DocumentState.VALIDATED
    assert body["approval"]["decision"] == ApprovalDecision.APPROVED
    assert body["approval"]["approver"] == "cfo@example.com"
    assert body["approval"]["amount"] == 5000.0
    assert body["approval"]["threshold_applied"] == 1000.0

    approvals = db_session.scalars(
        select(Approval).where(Approval.document_id == document["id"])
    ).all()
    assert len(approvals) == 1
    assert approvals[0].decision == ApprovalDecision.APPROVED

    # Approval must not appear in document.state_history — it isn't a
    # state transition, see docs/state-machine.md.
    history_states = db_session.scalars(
        select(StateHistory.to_state).where(StateHistory.document_id == document["id"])
    ).all()
    assert DocumentState.REJECTED not in history_states


def test_approve_document_under_threshold_returns_409(client):
    document = _upload(
        client, fields=BELOW_THRESHOLD_FIELDS, filename="small.pdf", content=PDF_BYTES + b"\nB"
    )

    response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_approve_document_twice_returns_409(client):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)
    client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )

    response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "someone-else@example.com"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_approve_document_not_validated_returns_409(client):
    # NEEDS_REVIEW documents (arithmetic mismatch) can't be approved.
    bad_fields = {**ABOVE_THRESHOLD_FIELDS, "total": ExtractedField(value=1.0)}
    document = _upload(client, fields=bad_fields, filename="bad.pdf", content=PDF_BYTES + b"\nC")
    assert document["state"] == DocumentState.NEEDS_REVIEW

    response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_reject_document_writes_approval_and_moves_to_rejected(client, db_session):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)

    response = client.post(
        f"/approvals/{document['id']}/reject",
        json={"approver": "cfo@example.com", "reason": "budget exceeded"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["state"] == DocumentState.REJECTED
    assert body["approval"]["decision"] == ApprovalDecision.REJECTED

    history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == document["id"])
        .order_by(StateHistory.created_at)
    ).all()
    assert history[-1].from_state == DocumentState.VALIDATED
    assert history[-1].to_state == DocumentState.REJECTED
    assert "cfo@example.com" in history[-1].reason
    assert "budget exceeded" in history[-1].reason


def test_reject_document_under_threshold_returns_409(client):
    document = _upload(
        client, fields=BELOW_THRESHOLD_FIELDS, filename="small.pdf", content=PDF_BYTES + b"\nD"
    )

    response = client.post(
        f"/approvals/{document['id']}/reject",
        json={"approver": "cfo@example.com", "reason": "n/a"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_approval_endpoints_require_auth(client):
    document = _upload(client, fields=ABOVE_THRESHOLD_FIELDS)

    assert client.get("/approvals").status_code == 401
    approve_response = client.post(
        f"/approvals/{document['id']}/approve", json={"approver": "x"}
    )
    assert approve_response.status_code == 401
