"""Tests spike/run_spike.py's orchestration logic — provider dispatch,
skip-when-no-credentials behavior, per-call error handling, and the
budget-cap safety net — with every provider's `extract()` faked out.
No network call, no credentials, no real spend. This is the "happy path"
the earlier manual checks (no-samples / no-providers) didn't cover.
"""

import sys

import pytest

from spike import run_spike
from spike.providers import azure_provider, claude_provider, mistral_provider
from spike.schema import NormalizedExtraction


def _fake_extract(provider_name: str, *, cost: float = 0.0, error: str | None = None):
    def _extract(doc_path, doc_id):  # noqa: ARG001 — signature must match the real extract()
        return NormalizedExtraction(
            provider_name=provider_name,
            model_version="fake",
            doc_id=doc_id,
            estimated_cost_usd=cost,
            error=error,
        )

    return _extract


def _make_samples(tmp_path, names=("doc1.pdf", "doc2.pdf")):
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    for name in names:
        (samples_dir / name).write_bytes(b"fake content, never actually read")
    return samples_dir


def test_main_only_calls_providers_with_credentials_configured(tmp_path, monkeypatch):
    samples_dir = _make_samples(tmp_path)
    results_dir = tmp_path / "results"
    monkeypatch.setattr(run_spike, "SAMPLES_DIR", samples_dir)
    monkeypatch.setattr(run_spike, "RESULTS_DIR", results_dir)

    monkeypatch.setenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "https://fake.example")
    monkeypatch.setenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "fake-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(azure_provider, "extract", _fake_extract("azure_document_intelligence"))
    monkeypatch.setattr(sys, "argv", ["run_spike.py", "--providers", "azure,mistral,claude"])

    run_spike.main()  # no SystemExit expected — this is the success path

    assert (results_dir / "azure" / "doc1.json").exists()
    assert (results_dir / "azure" / "doc2.json").exists()
    assert not (results_dir / "mistral").exists()
    assert not (results_dir / "claude").exists()


def test_run_one_records_a_provider_exception_as_an_error_not_a_crash(tmp_path, monkeypatch):
    def _raises(doc_path, doc_id):  # noqa: ARG001
        raise RuntimeError("simulated provider SDK failure")

    monkeypatch.setattr(mistral_provider, "extract", _raises)

    result = run_spike._run_one("mistral", tmp_path / "doc1.pdf", "doc1")

    assert result.error == "simulated provider SDK failure"
    assert result.provider_name == "mistral"


def test_main_stops_before_exceeding_the_budget_cap(tmp_path, monkeypatch):
    samples_dir = _make_samples(tmp_path, names=("doc1.pdf",))
    results_dir = tmp_path / "results"
    monkeypatch.setattr(run_spike, "SAMPLES_DIR", samples_dir)
    monkeypatch.setattr(run_spike, "RESULTS_DIR", results_dir)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    # A single call already costs more than the cap — simulates a bug
    # (e.g. an accidental loop) producing runaway spend.
    monkeypatch.setattr(claude_provider, "extract", _fake_extract("claude_vision", cost=5.00))
    monkeypatch.setattr(
        sys, "argv", ["run_spike.py", "--providers", "claude", "--budget-cap", "2.00"]
    )

    with pytest.raises(SystemExit) as exc_info:
        run_spike.main()

    assert exc_info.value.code == 2
    # The over-budget result must not be written — the cap check happens
    # before the file write, not after.
    assert not (results_dir / "claude" / "doc1.json").exists()


def test_available_providers_skips_missing_credentials_without_raising(monkeypatch):
    monkeypatch.delenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-key")

    available = run_spike._available_providers(["azure", "mistral"])

    assert available == ["mistral"]
