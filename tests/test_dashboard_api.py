"""Tier 2-ish integration tests for Phase 16 — Observability & Business
Metrics. Real Postgres (via db_session, see conftest.py), local disk
storage in a temp dir, no external provider — extraction is always
faked, so no test here ever makes a real network call. See
docs/testing-strategy.md.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.accounting import LogNotificationProvider, MockAccountingProvider
from app.config import get_settings
from app.db import get_session
from app.extraction import ExtractedField, ExtractionOutput
from app.main import app
from app.models import Vendor
from app.routers import actions as actions_router
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider
from app.vendor_matching import normalize_vendor_name

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}

GOOD_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-1"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=100.0),
    "tax": ExtractedField(value=8.0),
    "total": ExtractedField(value=108.0),
}

BAD_ARITHMETIC_FIELDS = {**GOOD_FIELDS, "total": ExtractedField(value=1.0)}


class FakeExtractionProvider:
    def __init__(self, *, output: ExtractionOutput):
        self._output = output

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        return self._output


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path, secret_key="test-secret"
    )
    app.dependency_overrides[actions_router.get_accounting_provider] = MockAccountingProvider
    app.dependency_overrides[actions_router.get_notification_provider] = LogNotificationProvider
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    db_session.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _upload(client, *, fields: dict, filename: str, content: bytes = PDF_BYTES) -> dict:
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


def test_dashboard_on_empty_database_is_all_zeroed(client):
    response = client.get("/dashboard", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["total_processed"] == 0
    assert body["straight_through_rate"] == 0.0
    assert body["review_rate"] == 0.0
    assert body["correction_rate"] == 0.0
    assert body["average_processing_time_seconds"] is None
    assert body["estimated_minutes_saved"] == 0.0


def test_dashboard_requires_auth(client):
    response = client.get("/dashboard")
    assert response.status_code == 401


def test_dashboard_reflects_mixed_outcomes(client):
    # A: straight-through, actioned all the way to COMPLETED (terminal).
    doc_a = _upload(client, fields=GOOD_FIELDS, filename="a.pdf")
    assert doc_a["state"] == "VALIDATED"
    action_response = client.post(f"/documents/{doc_a['id']}/action", headers=AUTH_HEADER)
    assert action_response.status_code == 200

    # B: needed review, corrected -> VALIDATED (not terminal).
    doc_b = _upload(
        client, fields=BAD_ARITHMETIC_FIELDS, filename="b.pdf", content=PDF_BYTES + b"B"
    )
    assert doc_b["state"] == "NEEDS_REVIEW"
    correct_response = client.post(
        f"/review/{doc_b['id']}/correct",
        json={
            "reviewer": "alice@example.com",
            "corrections": [{"field_name": "total", "corrected_value": "108.0"}],
        },
        headers=AUTH_HEADER,
    )
    assert correct_response.status_code == 200

    # C: needed review, rejected -> REJECTED (terminal, not corrected).
    doc_c = _upload(
        client, fields=BAD_ARITHMETIC_FIELDS, filename="c.pdf", content=PDF_BYTES + b"C"
    )
    assert doc_c["state"] == "NEEDS_REVIEW"
    reject_response = client.post(
        f"/review/{doc_c['id']}/reject",
        json={"reviewer": "alice@example.com", "reason": "not valid"},
        headers=AUTH_HEADER,
    )
    assert reject_response.status_code == 200

    # D: exact re-upload of A's bytes -> DUPLICATE (terminal, never
    # touched NEEDS_REVIEW, so counts as straight-through).
    dup_response = client.post(
        "/documents",
        files={"file": ("d.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers={**AUTH_HEADER, "Idempotency-Key": "distinct-from-a"},
    )
    assert dup_response.status_code == 201
    assert dup_response.json()["state"] == "DUPLICATE"

    response = client.get("/dashboard", headers=AUTH_HEADER)
    assert response.status_code == 200
    body = response.json()

    assert body["total_processed"] == 4
    assert body["needs_review_count"] == 2
    assert body["review_rate"] == 0.5
    assert body["straight_through_count"] == 2
    assert body["straight_through_rate"] == 0.5
    assert body["corrected_count"] == 1
    assert body["correction_rate"] == 0.5
    # A, C, D reached a terminal state -> a real average exists.
    assert body["average_processing_time_seconds"] is not None
    assert body["average_processing_time_seconds"] >= 0.0
    assert body["estimated_minutes_saved"] == 2 * body["estimated_manual_minutes_per_document"]
