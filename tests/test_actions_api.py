"""Tier 2-ish integration tests for Phase 12 — Downstream Accounting
Action. Real Postgres (via db_session, see conftest.py), local disk
storage in a temp dir, no external provider — extraction is always
faked and the accounting/notification providers are the real Mock/Log
implementations unless a test injects a fault, so no test here ever
makes a real network call. See docs/testing-strategy.md.

Uses the default APPROVAL_THRESHOLD_AMOUNT (1000.0) — see
tests/test_approvals_api.py for the same convention.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.accounting import LogNotificationProvider, MockAccountingProvider
from app.config import get_settings
from app.db import get_session
from app.extraction import ExtractedField, ExtractionOutput
from app.main import app
from app.models import (
    AccountingAction,
    AccountingActionStatus,
    ApLedgerEntry,
    DocumentState,
    Vendor,
)
from app.routers import actions as actions_router
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider
from app.vendor_matching import normalize_vendor_name

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}

# Arithmetic-consistent, under the default 1000.0 threshold — reaches
# VALIDATED untouched and needs no approval before being actioned.
SMALL_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-100"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=92.59),
    "tax": ExtractedField(value=7.41),
    "total": ExtractedField(value=100.0),
}

# Above the threshold — needs an approval before it's action-eligible.
LARGE_FIELDS = {
    **SMALL_FIELDS,
    "invoice_number": ExtractedField(value="INV-200"),
    "subtotal": ExtractedField(value=4629.63),
    "tax": ExtractedField(value=370.37),
    "total": ExtractedField(value=5000.0),
}


class FakeExtractionProvider:
    def __init__(self, *, output: ExtractionOutput | None = None):
        self._output = output

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        return self._output or ExtractionOutput(
            provider_name="fake", model_version="fake-1", fields=dict(SMALL_FIELDS)
        )


class FailingAccountingProvider:
    def create_payable(self, **kwargs):
        raise RuntimeError("ledger unavailable")


class FailingNotificationProvider:
    def notify(self, **kwargs):
        raise RuntimeError("smtp unavailable")


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path, secret_key="test-secret"
    )
    app.dependency_overrides[documents_router.get_extraction_provider] = FakeExtractionProvider
    app.dependency_overrides[actions_router.get_accounting_provider] = MockAccountingProvider
    app.dependency_overrides[actions_router.get_notification_provider] = LogNotificationProvider
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


def test_action_document_completes_and_creates_ledger_entry(client, db_session):
    document = _upload(client, fields=SMALL_FIELDS)
    assert document["state"] == DocumentState.VALIDATED

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["state"] == DocumentState.COMPLETED
    assert body["accounting_action"]["status"] == AccountingActionStatus.CONFIRMED
    assert body["accounting_action"]["external_reference"] is not None
    assert body["notification_sent"] is True

    entries = db_session.scalars(
        select(ApLedgerEntry).where(ApLedgerEntry.document_id == document["id"])
    ).all()
    assert len(entries) == 1
    assert entries[0].vendor_name == "Acme Corp"
    assert float(entries[0].total) == 100.0


def test_action_document_above_threshold_without_approval_returns_409(client):
    document = _upload(
        client, fields=LARGE_FIELDS, filename="large.pdf", content=PDF_BYTES + b"\nA"
    )
    assert document["state"] == DocumentState.VALIDATED

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 409
    assert "awaiting approval" in response.json()["detail"]


def test_action_document_above_threshold_with_approval_completes(client):
    document = _upload(
        client, fields=LARGE_FIELDS, filename="large2.pdf", content=PDF_BYTES + b"\nB"
    )
    approve_response = client.post(
        f"/approvals/{document['id']}/approve",
        json={"approver": "cfo@example.com"},
        headers=AUTH_HEADER,
    )
    assert approve_response.status_code == 200

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 200
    assert response.json()["document"]["state"] == DocumentState.COMPLETED


def test_action_document_not_validated_returns_409(client):
    bad_fields = {**SMALL_FIELDS, "total": ExtractedField(value=1.0)}
    document = _upload(client, fields=bad_fields, filename="bad.pdf", content=PDF_BYTES + b"\nC")
    assert document["state"] == DocumentState.NEEDS_REVIEW

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 409


def test_action_document_unknown_id_returns_404(client):
    response = client.post(
        "/documents/00000000-0000-0000-0000-000000000000/action", headers=AUTH_HEADER
    )
    assert response.status_code == 404


def test_action_document_is_idempotent(client, db_session):
    document = _upload(client, fields=SMALL_FIELDS, filename="idem.pdf", content=PDF_BYTES + b"\nD")

    first = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)
    second = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()["accounting_action"]["external_reference"]
        == second.json()["accounting_action"]["external_reference"]
    )

    ledger_count = db_session.scalar(
        select(func.count())
        .select_from(ApLedgerEntry)
        .where(ApLedgerEntry.document_id == document["id"])
    )
    assert ledger_count == 1

    action_count = db_session.scalar(
        select(func.count())
        .select_from(AccountingAction)
        .where(AccountingAction.document_id == document["id"])
    )
    assert action_count == 1


def test_action_document_accounting_failure_marks_failed(client, db_session):
    document = _upload(client, fields=SMALL_FIELDS, filename="fail.pdf", content=PDF_BYTES + b"\nE")
    app.dependency_overrides[actions_router.get_accounting_provider] = FailingAccountingProvider

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 502

    action = db_session.scalar(
        select(AccountingAction).where(AccountingAction.document_id == document["id"])
    )
    assert action.status == AccountingActionStatus.FAILED

    detail = client.get(f"/documents/{document['id']}", headers=AUTH_HEADER).json()
    assert detail["state"] == DocumentState.FAILED


def test_action_document_notification_failure_does_not_block_completion(client):
    document = _upload(
        client, fields=SMALL_FIELDS, filename="notif.pdf", content=PDF_BYTES + b"\nF"
    )
    app.dependency_overrides[actions_router.get_notification_provider] = (
        FailingNotificationProvider
    )

    response = client.post(f"/documents/{document['id']}/action", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["state"] == DocumentState.COMPLETED
    assert body["notification_sent"] is False


def test_action_document_requires_auth(client):
    document = _upload(client, fields=SMALL_FIELDS, filename="auth.pdf", content=PDF_BYTES + b"\nG")

    response = client.post(f"/documents/{document['id']}/action")

    assert response.status_code == 401
