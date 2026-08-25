"""Tier 2-ish integration tests: real Postgres (via db_session, see
conftest.py), local disk storage in a temp dir, no external provider.
Covers docs/workflow.md steps 1-3 (ingestion + extraction + validation)
and the idempotency/validation behavior documented in
docs/reliability.md and docs/security.md.

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
from app.extraction import ExtractedField, ExtractionOutput
from app.main import app
from app.models import DocumentState, StateHistory, ValidationResult, Vendor
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider
from app.vendor_matching import normalize_vendor_name

PDF_BYTES = b"%PDF-1.4\n%fake but valid-looking pdf content"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}

# A complete, arithmetic-consistent extraction — the "everything went
# right" case, which should sail through Phase 7's validation to
# VALIDATED without a human touching it.
VALID_FIELDS = {
    "vendor_name": ExtractedField(value="Acme Corp"),
    "invoice_number": ExtractedField(value="INV-1042"),
    "invoice_date": ExtractedField(value="2026-03-01"),
    "due_date": ExtractedField(value="2026-03-31"),
    "currency": ExtractedField(value="USD"),
    "subtotal": ExtractedField(value=1000.0),
    "tax": ExtractedField(value=80.0),
    "total": ExtractedField(value=1080.0),
}


class FakeExtractionProvider:
    """Test double — never calls a real provider. Defaults to a complete,
    valid extraction (see VALID_FIELDS); pass `output` or `error` to
    exercise a specific case. `call_log`, if given, records every call —
    used to prove an exact-hash duplicate never reaches this at all
    (Phase 9's whole point: no re-spend on a known re-upload).
    """

    def __init__(
        self,
        *,
        output: ExtractionOutput | None = None,
        error: Exception | None = None,
        call_log: list | None = None,
    ):
        self._output = output
        self._error = error
        self._call_log = call_log

    def extract(self, *, content: bytes, filename: str) -> ExtractionOutput:
        if self._call_log is not None:
            self._call_log.append(filename)
        if self._error is not None:
            raise self._error
        return self._output or ExtractionOutput(
            provider_name="fake", model_version="fake-1", fields=dict(VALID_FIELDS)
        )


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path
    )
    _override_extraction()
    # VALID_FIELDS' vendor ("Acme Corp") must be a known vendor for the
    # default happy-path tests to reach VALIDATED rather than
    # NEEDS_REVIEW — Phase 8 folds vendor matching into the same
    # validation step as Phase 7's rules.
    db_session.add(Vendor(name="Acme Corp", normalized_name=normalize_vendor_name("Acme Corp")))
    db_session.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override_extraction(*, output=None, error=None, call_log=None):
    def factory():
        return FakeExtractionProvider(output=output, error=error, call_log=call_log)

    app.dependency_overrides[documents_router.get_extraction_provider] = factory


def _fields_with(**overrides) -> dict:
    fields = dict(VALID_FIELDS)
    for name, value in overrides.items():
        fields[name] = ExtractedField(value=value)
    return fields


def _upload(client, *, content=PDF_BYTES, filename="invoice.pdf", headers=None):
    merged_headers = {**AUTH_HEADER, **(headers or {})}
    return client.post(
        "/documents",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
        headers=merged_headers,
    )


def _state_sequence(db_session, document_id) -> list[DocumentState]:
    history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == document_id)
        .order_by(StateHistory.created_at)
    ).all()
    return [h.to_state for h in history]


def test_upload_requires_authentication(client):
    response = client.post(
        "/documents", files={"file": ("invoice.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    )
    assert response.status_code == 401


def test_upload_with_valid_data_reaches_validated_state(client, db_session):
    response = _upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == DocumentState.VALIDATED.value
    assert body["mime_type"] == "application/pdf"
    assert body["original_filename"] == "invoice.pdf"

    assert _state_sequence(db_session, body["id"]) == [
        DocumentState.RECEIVED,
        DocumentState.EXTRACTING,
        DocumentState.EXTRACTED,
        DocumentState.VALIDATING,
        DocumentState.VALIDATED,
    ]


def test_upload_with_failing_extraction_reaches_failed_state(client):
    _override_extraction(error=RuntimeError("simulated provider failure"))

    response = _upload(client)

    assert response.status_code == 201  # the upload itself succeeded
    assert response.json()["state"] == DocumentState.FAILED.value


def test_upload_with_missing_required_field_reaches_needs_review(client, db_session):
    output = ExtractionOutput(
        provider_name="fake", model_version="fake-1", fields=_fields_with(invoice_number=None)
    )
    _override_extraction(output=output)

    response = _upload(client)

    assert response.json()["state"] == DocumentState.NEEDS_REVIEW.value
    assert DocumentState.NEEDS_REVIEW in _state_sequence(db_session, response.json()["id"])

    results = db_session.scalars(
        select(ValidationResult).where(
            ValidationResult.document_id == response.json()["id"],
            ValidationResult.rule_name == "required:invoice_number",
        )
    ).all()
    assert len(results) == 1
    assert results[0].passed is False
    assert "invoice_number" in results[0].reason


def test_upload_with_arithmetic_mismatch_reaches_needs_review(client, db_session):
    # Total is a cent off from subtotal + tax — a deliberately adversarial
    # case, not a rounding artifact (tolerance is 0.02).
    output = ExtractionOutput(
        provider_name="fake", model_version="fake-1", fields=_fields_with(total=1080.05)
    )
    _override_extraction(output=output)

    response = _upload(client)

    assert response.json()["state"] == DocumentState.NEEDS_REVIEW.value
    results = db_session.scalars(
        select(ValidationResult).where(
            ValidationResult.document_id == response.json()["id"],
            ValidationResult.rule_name == "arithmetic:subtotal_plus_tax_equals_total",
        )
    ).all()
    assert len(results) == 1
    assert results[0].passed is False


def test_upload_missing_due_date_alone_still_reaches_validated(client):
    # due_date is deliberately not a required field — see
    # docs/extraction-strategy.md's real-run finding. A missing due date
    # on its own must not send a document to review.
    output = ExtractionOutput(
        provider_name="fake", model_version="fake-1", fields=_fields_with(due_date=None)
    )
    _override_extraction(output=output)

    response = _upload(client)

    assert response.json()["state"] == DocumentState.VALIDATED.value


def test_upload_with_unknown_vendor_reaches_needs_review(client, db_session):
    output = ExtractionOutput(
        provider_name="fake",
        model_version="fake-1",
        fields=_fields_with(vendor_name="Totally Unrelated Company Ltd"),
    )
    _override_extraction(output=output)

    response = _upload(client)

    assert response.json()["state"] == DocumentState.NEEDS_REVIEW.value
    results = db_session.scalars(
        select(ValidationResult).where(
            ValidationResult.document_id == response.json()["id"],
            ValidationResult.rule_name == "vendor:known",
        )
    ).all()
    assert len(results) == 1
    assert results[0].passed is False
    assert "Totally Unrelated Company Ltd" in results[0].reason


def test_upload_with_near_miss_vendor_spelling_still_matches(client):
    # A typo/formatting variation of the known "Acme Corp" — deterministic
    # fuzzy matching must still find it, not force a human to fix a
    # cosmetic spelling difference.
    output = ExtractionOutput(
        provider_name="fake", model_version="fake-1", fields=_fields_with(vendor_name="Acme Corp.")
    )
    _override_extraction(output=output)

    response = _upload(client)

    assert response.json()["state"] == DocumentState.VALIDATED.value


def test_exact_duplicate_file_reaches_duplicate_without_calling_extraction(client, db_session):
    call_log: list = []
    _override_extraction(call_log=call_log)

    # Different Idempotency-Key headers, same bytes — Phase 4's
    # request-level idempotency must NOT be what catches this; only
    # Phase 9's content-hash check should.
    first = _upload(client, headers={"Idempotency-Key": "key-a"})
    second = _upload(client, headers={"Idempotency-Key": "key-b"})

    assert first.json()["id"] != second.json()["id"]
    assert first.json()["state"] == DocumentState.VALIDATED.value
    assert second.json()["state"] == DocumentState.DUPLICATE.value
    # Extraction ran exactly once — the duplicate never reached it.
    assert len(call_log) == 1

    assert _state_sequence(db_session, second.json()["id"]) == [
        DocumentState.RECEIVED,
        DocumentState.DUPLICATE,
    ]


def test_content_level_duplicate_with_different_file_bytes_reaches_duplicate(client):
    # Different file bytes (so the exact-hash check doesn't catch this),
    # same extracted vendor/invoice_number/total/date — the same invoice,
    # re-scanned or re-typed as a different file.
    first = _upload(client, content=PDF_BYTES)
    second = _upload(client, content=PDF_BYTES + b"\n%extra padding, different hash")

    assert first.json()["state"] == DocumentState.VALIDATED.value
    assert second.json()["state"] == DocumentState.DUPLICATE.value


def test_genuinely_different_invoices_same_vendor_are_not_flagged_as_duplicate(client):
    first = _upload(client, content=PDF_BYTES)

    output = ExtractionOutput(
        provider_name="fake",
        model_version="fake-1",
        fields=_fields_with(invoice_number="INV-2099", total=250.0, subtotal=231.48, tax=18.52),
    )
    _override_extraction(output=output)
    second = _upload(client, content=PDF_BYTES + b"\n%a genuinely different invoice")

    assert first.json()["state"] == DocumentState.VALIDATED.value
    assert second.json()["state"] == DocumentState.VALIDATED.value
    assert second.json()["id"] != first.json()["id"]


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
    response = client.get("/documents", params={"state": "VALIDATED"}, headers=AUTH_HEADER)
    assert response.status_code == 200
    assert len(response.json()) >= 1
    assert all(doc["state"] == "VALIDATED" for doc in response.json())


def test_get_extraction_returns_normalized_fields(client):
    # Default fixture output (VALID_FIELDS) — no override needed.
    document_id = _upload(client).json()["id"]
    response = client.get(f"/documents/{document_id}/extraction", headers=AUTH_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["vendor_name"] == "Acme Corp"
    assert body["invoice_number"] == "INV-1042"
    assert body["total"] == 1080.0
    assert body["fields"]["vendor_name"]["value"] == "Acme Corp"


def test_get_extraction_not_found_when_extraction_failed(client):
    _override_extraction(error=RuntimeError("simulated provider failure"))
    document_id = _upload(client).json()["id"]

    response = client.get(f"/documents/{document_id}/extraction", headers=AUTH_HEADER)

    assert response.status_code == 404
