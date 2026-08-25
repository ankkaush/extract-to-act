"""Tier 2-ish integration tests for Phase 10 — Human Review Workflow.
Real Postgres (via db_session, see conftest.py), local disk storage in a
temp dir, no external provider — extraction is always faked, so no test
here ever makes a real network call. See docs/testing-strategy.md.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.extraction import ExtractedField, ExtractionOutput
from app.main import app
from app.models import DocumentState, ReviewEvent, StateHistory, Vendor
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider
from app.vendor_matching import normalize_vendor_name

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}

# Arithmetic-inconsistent on purpose: subtotal + tax != total, so this
# always lands in NEEDS_REVIEW (Phase 7's arithmetic rule) — the case
# every review-workflow test in this file starts from.
BAD_ARITHMETIC_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-9001"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=1000.0),
    "tax": ExtractedField(value=80.0),
    "total": ExtractedField(value=999.0),  # should be 1080.0
}


class FakeExtractionProvider:
    def __init__(self, *, output: ExtractionOutput | None = None):
        self._output = output

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        return self._output or ExtractionOutput(
            provider_name="fake", model_version="fake-1", fields=dict(BAD_ARITHMETIC_FIELDS)
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


def _upload_needs_review(client) -> str:
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 201
    assert response.json()["state"] == DocumentState.NEEDS_REVIEW
    return response.json()["id"]


def test_review_queue_lists_needs_review_documents_with_failed_rules(client):
    document_id = _upload_needs_review(client)

    response = client.get("/review", headers=AUTH_HEADER)

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == document_id
    rule_names = [r["rule_name"] for r in items[0]["failed_rules"]]
    assert "arithmetic:subtotal_plus_tax_equals_total" in rule_names


def test_review_queue_excludes_documents_not_in_needs_review(client):
    # A second, arithmetic-consistent upload should reach VALIDATED and
    # never show up in the review queue.
    good_output = ExtractionOutput(
        provider_name="fake",
        model_version="fake-1",
        fields={**BAD_ARITHMETIC_FIELDS, "total": ExtractedField(value=1080.0)},
    )
    app.dependency_overrides[documents_router.get_extraction_provider] = (
        lambda: FakeExtractionProvider(output=good_output)
    )
    response = client.post(
        "/documents",
        files={"file": ("invoice2.pdf", io.BytesIO(PDF_BYTES + b"\nX"), "application/pdf")},
        headers=AUTH_HEADER,
    )
    assert response.json()["state"] == DocumentState.VALIDATED

    review_response = client.get("/review", headers=AUTH_HEADER)
    assert review_response.json() == []


def test_review_detail_404_for_unknown_document(client):
    response = client.get(
        "/review/00000000-0000-0000-0000-000000000000", headers=AUTH_HEADER
    )
    assert response.status_code == 404


def test_review_detail_includes_extraction_failed_rules_and_signed_file_url(client):
    document_id = _upload_needs_review(client)

    response = client.get(f"/review/{document_id}", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["id"] == document_id
    assert body["extraction"]["total"] == 999.0
    assert len(body["failed_rules"]) == 1
    assert body["file_url"].startswith("/files/")
    assert "signature=" in body["file_url"]


def test_correct_document_fixes_field_and_reaches_validated(client, db_session):
    document_id = _upload_needs_review(client)

    response = client.post(
        f"/review/{document_id}/correct",
        json={
            "reviewer": "alice@example.com",
            "corrections": [{"field_name": "total", "corrected_value": "1080.0"}],
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["state"] == DocumentState.VALIDATED
    assert body["extraction"]["total"] == 1080.0
    assert body["failed_rules"] == []

    events = db_session.scalars(
        select(ReviewEvent).where(ReviewEvent.document_id == document_id)
    ).all()
    assert len(events) == 1
    assert events[0].field_name == "total"
    assert events[0].original_value == "999.00" or events[0].original_value == "999.0"
    assert events[0].corrected_value == "1080.0"
    assert events[0].reviewer == "alice@example.com"

    history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == document_id)
        .order_by(StateHistory.created_at)
    ).all()
    assert history[-1].from_state == DocumentState.NEEDS_REVIEW
    assert history[-1].to_state == DocumentState.VALIDATED
    assert "alice@example.com" in history[-1].reason


def test_correct_document_rejects_unknown_field(client):
    document_id = _upload_needs_review(client)

    response = client.post(
        f"/review/{document_id}/correct",
        json={
            "reviewer": "alice@example.com",
            "corrections": [{"field_name": "bank_account_number", "corrected_value": "123"}],
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 422


def test_correct_document_rejects_unparseable_value(client):
    document_id = _upload_needs_review(client)

    response = client.post(
        f"/review/{document_id}/correct",
        json={
            "reviewer": "alice@example.com",
            "corrections": [{"field_name": "total", "corrected_value": "not-a-number"}],
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 422


def test_correct_document_not_in_needs_review_returns_409(client):
    document_id = _upload_needs_review(client)
    client.post(
        f"/review/{document_id}/correct",
        json={
            "reviewer": "alice@example.com",
            "corrections": [{"field_name": "total", "corrected_value": "1080.0"}],
        },
        headers=AUTH_HEADER,
    )

    # Already VALIDATED — correcting again must not be allowed.
    response = client.post(
        f"/review/{document_id}/correct",
        json={
            "reviewer": "bob@example.com",
            "corrections": [{"field_name": "total", "corrected_value": "1090.0"}],
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_reject_document_moves_to_rejected_with_attribution(client, db_session):
    document_id = _upload_needs_review(client)

    response = client.post(
        f"/review/{document_id}/reject",
        json={"reviewer": "alice@example.com", "reason": "not a real invoice"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.json()["document"]["state"] == DocumentState.REJECTED

    history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == document_id)
        .order_by(StateHistory.created_at)
    ).all()
    assert history[-1].to_state == DocumentState.REJECTED
    assert "alice@example.com" in history[-1].reason
    assert "not a real invoice" in history[-1].reason


def test_reject_document_not_in_needs_review_returns_409(client):
    document_id = _upload_needs_review(client)
    client.post(
        f"/review/{document_id}/reject",
        json={"reviewer": "alice@example.com", "reason": "bad"},
        headers=AUTH_HEADER,
    )

    response = client.post(
        f"/review/{document_id}/reject",
        json={"reviewer": "bob@example.com", "reason": "again"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 409


def test_review_endpoints_require_auth(client):
    document_id = _upload_needs_review(client)

    assert client.get("/review").status_code == 401
    assert client.get(f"/review/{document_id}").status_code == 401
    reject_response = client.post(
        f"/review/{document_id}/reject", json={"reviewer": "x", "reason": "y"}
    )
    assert reject_response.status_code == 401


def test_signed_file_url_serves_original_content_without_bearer_auth(client):
    document_id = _upload_needs_review(client)
    detail = client.get(f"/review/{document_id}", headers=AUTH_HEADER).json()

    # No Authorization header at all — the signature is the authorization.
    response = client.get(detail["file_url"])

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"


def test_signed_file_url_rejects_tampered_signature(client):
    document_id = _upload_needs_review(client)
    detail = client.get(f"/review/{document_id}", headers=AUTH_HEADER).json()

    tampered = detail["file_url"][:-1] + ("0" if detail["file_url"][-1] != "0" else "1")
    response = client.get(tampered)

    assert response.status_code == 403


def test_signed_file_url_rejects_expired_link(client):
    document_id = _upload_needs_review(client)
    detail = client.get(f"/review/{document_id}", headers=AUTH_HEADER).json()

    expired_url = detail["file_url"].replace(
        detail["file_url"].split("expires=")[1].split("&")[0], "1"
    )
    response = client.get(expired_url)

    assert response.status_code == 403
