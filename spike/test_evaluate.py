"""Tests spike/evaluate.py's scoring logic against hand-built fixtures —
no real provider results needed. Confirms per-field accuracy, the
critical-vs-overall accuracy split, and the itemized critical-error list
all compute correctly, independent of whether a real spike run has ever
happened.
"""

from spike.evaluate import CRITICAL_FIELDS, _values_match, evaluate_provider, render_report

GROUND_TRUTH = {
    "doc_correct": {
        "fields": {
            "vendor_name": "Acme Corp",
            "invoice_number": "INV-1",
            "invoice_date": "2026-01-01",
            "due_date": "2026-02-01",
            "currency": "USD",
            "subtotal": 100.0,
            "tax": 10.0,
            "total": 110.0,
        },
        "line_items": [{"description": "Widget"}],
    },
    "doc_wrong_currency": {
        "fields": {
            "vendor_name": "Beta Inc",
            "invoice_number": "INV-2",
            "invoice_date": "2026-01-05",
            "due_date": "2026-02-05",
            "currency": "CAD",
            "subtotal": 50.0,
            "tax": 5.0,
            "total": 55.0,
        },
        "line_items": [],
    },
}


def _result(fields: dict, *, line_items=None, error=None) -> dict:
    return {
        "fields": {k: {"value": v, "confidence": 0.9} for k, v in fields.items()},
        "line_items": line_items or [],
        "latency_seconds": 1.0,
        "estimated_cost_usd": 0.0,
        "error": error,
    }


def _write_result(tmp_path, provider: str, doc_id: str, payload: dict):
    import json

    provider_dir = tmp_path / provider
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / f"{doc_id}.json").write_text(json.dumps(payload))


def test_values_match_normalizes_whitespace_case_and_float_rounding():
    assert _values_match("Acme Corp", "Acme Corp")
    assert _values_match(" Acme Corp ", "acme corp")
    assert _values_match(100.0, 100.0)
    assert _values_match(100.004, 100.0)
    assert not _values_match("Acme Corp", "Other Corp")
    assert not _values_match(None, "Acme Corp")
    assert _values_match(None, None)


def test_evaluate_provider_computes_correct_and_critical_accuracy(tmp_path, monkeypatch):
    monkeypatch.setattr("spike.evaluate.RESULTS_DIR", tmp_path)

    correct_fields = GROUND_TRUTH["doc_correct"]["fields"]
    _write_result(tmp_path, "azure", "doc_correct", _result(correct_fields, line_items=[{"d": 1}]))

    wrong_fields = dict(GROUND_TRUTH["doc_wrong_currency"]["fields"])
    wrong_fields["currency"] = "USD"  # deliberately wrong — ground truth is CAD
    _write_result(tmp_path, "azure", "doc_wrong_currency", _result(wrong_fields))

    result = evaluate_provider("azure", GROUND_TRUTH)

    assert result["documents_evaluated"] == 2
    assert result["errors"] == 0
    assert result["per_field_accuracy"]["currency"] == 0.5
    assert result["per_field_accuracy"]["invoice_number"] == 1.0
    # Critical accuracy must reflect the currency miss, not be hidden by
    # the other critical fields all being correct.
    assert 0 < result["critical_field_accuracy"] < 1
    assert len(result["critical_errors"]) == 1
    error = result["critical_errors"][0]
    assert error["field"] == "currency"
    assert error["doc_id"] == "doc_wrong_currency"
    assert error["expected"] == "CAD"
    assert error["got"] == "USD"


def test_evaluate_provider_skips_documents_the_provider_wasnt_run_against(tmp_path, monkeypatch):
    monkeypatch.setattr("spike.evaluate.RESULTS_DIR", tmp_path)
    _write_result(tmp_path, "azure", "doc_correct", _result(GROUND_TRUTH["doc_correct"]["fields"]))
    # doc_wrong_currency has no azure result on disk at all.

    result = evaluate_provider("azure", GROUND_TRUTH)

    assert result["documents_evaluated"] == 1


def test_evaluate_provider_counts_errored_documents_separately(tmp_path, monkeypatch):
    monkeypatch.setattr("spike.evaluate.RESULTS_DIR", tmp_path)
    _write_result(tmp_path, "azure", "doc_correct", _result({}, error="provider timeout"))

    result = evaluate_provider("azure", {"doc_correct": GROUND_TRUTH["doc_correct"]})

    assert result["errors"] == 1
    assert result["overall_field_accuracy"] is None  # no fields scored — only an error


def test_evaluate_provider_with_no_results_returns_not_run_marker():
    result = evaluate_provider("mistral", GROUND_TRUTH)
    assert result["documents_evaluated"] == 0
    assert result["critical_errors"] == []


def test_render_report_includes_named_critical_errors_not_just_a_percentage():
    evaluation = {
        "provider": "azure",
        "documents_evaluated": 2,
        "errors": 0,
        "overall_field_accuracy": 0.9,
        "per_field_accuracy": {f: 0.9 for f in CRITICAL_FIELDS + ["vendor_name", "subtotal"]},
        "critical_field_accuracy": 0.83,
        "critical_errors": [
            {
                "doc_id": "inv_11_ambiguous_currency",
                "difficulty": "hard",
                "field": "currency",
                "expected": "CAD",
                "got": "USD",
                "confidence": 0.88,
            }
        ],
        "avg_confidence_when_correct": 0.95,
        "avg_confidence_when_wrong": 0.88,
        "avg_latency_seconds": 1.2,
        "total_estimated_cost_usd": 0.0,
        "line_item_count_match_rate": 1.0,
    }
    not_run = {"provider": "claude", "documents_evaluated": 0}

    report = render_report([evaluation, not_run])

    assert "inv_11_ambiguous_currency" in report
    assert "`CAD`" in report and "`USD`" in report
    assert "Business-critical field accuracy" in report
    assert "claude" in report  # not-run providers still listed, not silently dropped
