"""Tier 2-ish integration tests: real Postgres (via db_session, see
conftest.py), local disk storage in a temp dir, no external provider.
Covers docs/workflow.md steps 1-2 (ingestion + extraction) and the
idempotency/validation behavior documented in docs/reliability.md and
docs/security.md.

Extraction is always faked here — see FakeExtractionProvider — so no
test in this file ever makes a real network call. See
docs/testing-strategy.md.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.extraction import EXTRACTED_FIELDS, ExtractedField, ExtractionOutput
from app.main import app
from app.models import DocumentState, StateHistory
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}


class FakeExtractionProvider:
    """Test double — never calls a real provider. Defaults to a
    successful, minimal (all-null-field) extraction; pass `output` or
    `error` to exercise a specific case.
    """

    def __init__(self, *, output: ExtractionOutput | None = None, error: Exception | None = None):
        self._output = output
        self._error = error

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        if self._error is not None:
            raise self._error
        return self._output or ExtractionOutput(
            provider_name="fake",
            model_version="fake-1",
            fields={name: ExtractedField(value=None) for name in EXTRACTED_FIELDS},
        )


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path
    )
    _override_extraction()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override_extraction(*, output=None, error=None):
    def factory():
        return FakeExtractionProvider(output=output, error=error)

    app.dependency_overrides[documents_router.get_extraction_provider] = factory


def _upload(client, *, content=PDF_BYTES, filename="invoice.pdf", headers=None):
    merged_headers = {**AUTH_HEADER, **(headers or {})}
    return client.post(
        "/documents",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
        headers=merged_headers,
    )


def test_upload_requires_authentication(client):
    response = client.post(
        "/documents", files={"file": ("invoice.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    )
    assert response.status_code == 401


def test_upload_runs_extraction_and_reaches_extracted_state(client, db_session):
    response = _upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == DocumentState.EXTRACTED.value
    assert body["mime_type"] == "application/pdf"
    assert body["original_filename"] == "invoice.pdf"

    history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == body["id"])
        .order_by(StateHistory.created_at)
    ).all()
    assert [h.to_state for h in history] == [
        DocumentState.RECEIVED,
        DocumentState.EXTRACTING,
        DocumentState.EXTRACTED,
    ]


def test_upload_with_failing_extraction_reaches_failed_state(client):
    _override_extraction(error=RuntimeError("simulated provider failure"))

    response = _upload(client)

    assert response.status_code == 201  # the upload itself succeeded
    assert response.json()["state"] == DocumentState.FAILED.value


def test_repeated_request_with_same_idempotency_key_returns_existing_document(client):
    headers = {"Idempotency-Key": "same-key-123"}
    first = _upload(client, headers=headers)
    second = _upload(client, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201  # not an error — same record, returned again
    assert first.json()["id"] == second.json()["id"]


def test_requests_without_an_idempotency_key_are_independent(client):
    first = _upload(client)
    second = _upload(client)
    assert first.json()["id"] != second.json()["id"]


def test_upload_rejects_content_that_is_not_a_supported_file_type(client):
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 415


def test_upload_rejects_oversized_content(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_bytes", 10)
    response = _upload(client, content=PDF_BYTES)
    assert response.status_code == 413


def test_get_document_by_id(client):
    created = _upload(client).json()
    response = client.get(f"/documents/{created['id']}", headers=AUTH_HEADER)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_document_not_found(client):
    response = client.get(
        "/documents/00000000-0000-0000-0000-000000000000", headers=AUTH_HEADER
    )
    assert response.status_code == 404


def test_list_documents_filters_by_state(client):
    _upload(client)
    response = client.get("/documents", params={"state": "EXTRACTED"}, headers=AUTH_HEADER)
    assert response.status_code == 200
    assert len(response.json()) >= 1
    assert all(doc["state"] == "EXTRACTED" for doc in response.json())


def test_get_extraction_returns_normalized_fields(client):
    output = ExtractionOutput(
        provider_name="fake",
        model_version="fake-1",
        fields={
            "vendor_name": ExtractedField(value="Acme Corp", confidence=0.95),
            "invoice_number": ExtractedField(value="INV-1"),
            "invoice_date": ExtractedField(value="2026-03-01"),
            "due_date": ExtractedField(value=None),
            "currency": ExtractedField(value="USD"),
            "subtotal": ExtractedField(value=100.0),
            "tax": ExtractedField(value=8.0),
            "total": ExtractedField(value=108.0),
        },
    )
    _override_extraction(output=output)

    document_id = _upload(client).json()["id"]
    response = client.get(f"/documents/{document_id}/extraction", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["vendor_name"] == "Acme Corp"
    assert body["total"] == 108.0
    assert body["fields"]["vendor_name"]["confidence"] == 0.95


def test_get_extraction_not_found_when_extraction_failed(client):
    _override_extraction(error=RuntimeError("simulated provider failure"))
    document_id = _upload(client).json()["id"]

    response = client.get(f"/documents/{document_id}/extraction", headers=AUTH_HEADER)

    assert response.status_code == 404
