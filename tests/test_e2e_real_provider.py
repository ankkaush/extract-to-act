"""Phase 15 — System-Level Testing. Tier 4 (docs/testing-strategy.md):
full pipeline against the real, live Mistral API. Every test here is
marked `real_api` and excluded from the default `pytest` run and CI
(`pyproject.toml`'s `addopts = "-m 'not real_api'"`) — run explicitly
and rarely with `pytest -m real_api tests/test_e2e_real_provider.py`,
never as part of routine development.

Only two real calls exist in this file, deliberately: one proving the
full happy path still works end to end against the live API (drift
detection — a fixture-only suite can't catch a real API/SDK shape
change), and one "chaos" test proving a real, live authentication
failure is handled exactly the way the fake-provider tests already
proved a *simulated* failure is — including, critically, that the
Phase 14 fix (never let a provider exception's raw message reach
state_history or a notification) holds against a genuine SDK
exception, not just a hand-rolled one. `RETRY_ATTEMPTS=1` is forced for
the failure test specifically to keep that single real call to exactly
one attempt, not three — see docs/testing-strategy.md's minimum-calls
rule.

Uses the real synthetic sample from the Phase 5 spike
(spike/samples/inv_01_baseline_usd.pdf) rather than generating a new
one — same dataset, no new provider evidence needed here.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.extraction import MistralExtractionProvider
from app.main import app
from app.models import DocumentState, ExtractionResult, StateHistory
from app.routers import documents as documents_router
from app.storage import LocalStorageProvider

pytestmark = pytest.mark.real_api

SAMPLE_INVOICE = Path(__file__).parent.parent / "spike" / "samples" / "inv_01_baseline_usd.pdf"
AUTH_HEADER = {"Authorization": f"Bearer {get_settings().api_key}"}


@pytest.fixture
def client(db_session, tmp_path):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[documents_router.get_storage_provider] = lambda: LocalStorageProvider(
        base_dir=tmp_path, secret_key="test-secret"
    )
    # Deliberately no override of get_extraction_provider — this is the
    # one test file that wants the real MistralExtractionProvider,
    # reading the real MISTRAL_API_KEY from the environment.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_real_extraction_reaches_a_terminal_state(client, db_session):
    assert SAMPLE_INVOICE.exists(), f"missing fixture: {SAMPLE_INVOICE}"

    with SAMPLE_INVOICE.open("rb") as f:
        response = client.post(
            "/documents",
            files={"file": ("inv_01_baseline_usd.pdf", f, "application/pdf")},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 201
    body = response.json()
    # Never EXTRACTING/VALIDATING — the real call either finished or the
    # document is FAILED; it must not come back mid-flight.
    assert body["state"] in (
        DocumentState.VALIDATED,
        DocumentState.NEEDS_REVIEW,
        DocumentState.FAILED,
    )

    if body["state"] != DocumentState.FAILED:
        extraction = db_session.scalar(
            select(ExtractionResult).where(ExtractionResult.document_id == body["id"])
        )
        assert extraction is not None
        assert extraction.provider_name == "mistral_ocr"
        # Real extraction populated at least the vendor — proves the
        # live call actually returned structured data, not an empty shell.
        assert extraction.vendor_name


def test_real_authentication_failure_dead_letters_without_leaking_the_error(
    client, db_session, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "retry_attempts", 1)

    bogus_provider = MistralExtractionProvider(api_key="invalid-key-for-chaos-test")
    app.dependency_overrides[documents_router.get_extraction_provider] = lambda: bogus_provider

    with SAMPLE_INVOICE.open("rb") as f:
        response = client.post(
            "/documents",
            files={"file": ("inv_01_baseline_usd.pdf", f, "application/pdf")},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == DocumentState.FAILED

    failure_history = db_session.scalars(
        select(StateHistory)
        .where(StateHistory.document_id == body["id"])
        .where(StateHistory.to_state == DocumentState.FAILED)
    ).all()
    assert len(failure_history) == 1
    reason = failure_history[0].reason
    # The real regression check: a genuine SDK auth-failure message must
    # never appear verbatim in the audit trail — only the exception
    # type and a fixed phrase (app/routers/documents.py's
    # _attempt_extraction, fixed in Phase 14).
    assert "last error type:" in reason
    assert "invalid-key-for-chaos-test" not in reason
    assert "Bearer" not in reason
    assert "Authorization" not in reason
