"""Tier 2-ish integration tests: real Postgres (via db_session, see
conftest.py), local disk storage in a temp dir, no external provider.
Covers docs/workflow.md step 1 (ingestion) and the idempotency/validation
behavior documented in docs/reliability.md and docs/security.md.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import DocumentState, StateHistory
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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


def test_upload_creates_a_received_document(client, db_session):
    response = _upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == DocumentState.RECEIVED.value
    assert body["mime_type"] == "application/pdf"
    assert body["original_filename"] == "invoice.pdf"

    history = db_session.scalars(select(StateHistory)).all()
    assert len(history) == 1
    assert history[0].from_state is None
    assert history[0].to_state == DocumentState.RECEIVED


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
    response = client.get("/documents", params={"state": "RECEIVED"}, headers=AUTH_HEADER)
    assert response.status_code == 200
    assert len(response.json()) >= 1
    assert all(doc["state"] == "RECEIVED" for doc in response.json())
