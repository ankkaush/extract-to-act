"""Scores each provider's spike/results/ against spike/ground_truth/ and
writes spike/report.md — the evidence docs/extraction-strategy.md's final
provider decision should be based on. See spike/README.md for the ground
truth file format.

Per the approved evaluation methodology, this deliberately does NOT stop
at an aggregate accuracy number: every business-critical field (total,
currency, invoice_number, invoice_date, due_date, tax — the ones where a
wrong answer is a real financial/compliance risk, not just an
inconvenience) gets its own accuracy rollup AND a named, itemized list of
every miss, so a reviewer can see exactly which document/field/provider
combination failed rather than inferring it from a percentage.

Usage:
    python -m spike.evaluate
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from spike.invoice_specs import INVOICE_SPECS
from spike.schema import EVALUATED_FIELDS

SPIKE_DIR = Path(__file__).parent
RESULTS_DIR = SPIKE_DIR / "results"
GROUND_TRUTH_DIR = SPIKE_DIR / "ground_truth"
REPORT_PATH = SPIKE_DIR / "report.md"

# The fields where an extraction error is a business-critical mistake,
# not just noise — matches the project owner's explicit evaluation
# requirement. Everything in EVALUATED_FIELDS but not here (currently:
# vendor_name, subtotal) still gets scored, just not singled out.
CRITICAL_FIELDS = ["total", "currency", "invoice_number", "invoice_date", "due_date", "tax"]

_DIFFICULTY_BY_DOC = {spec.doc_id: spec.difficulty for spec in INVOICE_SPECS}


def _normalize(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return f"{float(value):.2f}"
    return str(value).strip().lower()


def _values_match(extracted, expected) -> bool:
    return _normalize(extracted) == _normalize(expected)


def _load_ground_truth() -> dict[str, dict]:
    truth = {}
    for path in GROUND_TRUTH_DIR.glob("*.json"):
        truth[path.stem] = json.loads(path.read_text())
    return truth


def _load_results(provider_name: str) -> dict[str, dict]:
    provider_dir = RESULTS_DIR / provider_name
    if not provider_dir.exists():
        return {}
    return {p.stem: json.loads(p.read_text()) for p in provider_dir.glob("*.json")}


def evaluate_provider(provider_name: str, ground_truth: dict[str, dict]) -> dict:
    results = _load_results(provider_name)
    if not results:
        return {"provider": provider_name, "documents_evaluated": 0, "critical_errors": []}

    field_correct = dict.fromkeys(EVALUATED_FIELDS, 0)
    field_total = dict.fromkeys(EVALUATED_FIELDS, 0)
    confidences_when_correct: list[float] = []
    confidences_when_wrong: list[float] = []
    latencies: list[float] = []
    costs: list[float] = []
    errors = 0
    line_item_count_matches = 0
    line_item_count_total = 0
    critical_errors: list[dict] = []
    critical_correct = 0
    critical_total = 0

    for doc_id, expected in ground_truth.items():
        result = results.get(doc_id)
        if result is None:
            continue  # this provider wasn't run against this doc
        if result.get("error"):
            errors += 1
            continue

        if result.get("latency_seconds") is not None:
            latencies.append(result["latency_seconds"])
        if result.get("estimated_cost_usd") is not None:
            costs.append(result["estimated_cost_usd"])

        for field_name in EVALUATED_FIELDS:
            expected_value = expected.get("fields", {}).get(field_name)
            got = result.get("fields", {}).get(field_name, {})
            got_value = got.get("value")
            confidence = got.get("confidence")

            field_total[field_name] += 1
            correct = _values_match(got_value, expected_value)
            if correct:
                field_correct[field_name] += 1
                if confidence is not None:
                    confidences_when_correct.append(confidence)
            elif confidence is not None:
                confidences_when_wrong.append(confidence)

            if field_name in CRITICAL_FIELDS:
                critical_total += 1
                if correct:
                    critical_correct += 1
                else:
                    critical_errors.append(
                        {
                            "doc_id": doc_id,
                            "difficulty": _DIFFICULTY_BY_DOC.get(doc_id, "?"),
                            "field": field_name,
                            "expected": expected_value,
                            "got": got_value,
                            "confidence": confidence,
                        }
                    )

        expected_items = expected.get("line_items", [])
        got_items = result.get("line_items", [])
        line_item_count_total += 1
        if len(expected_items) == len(got_items):
            line_item_count_matches += 1

    per_field_accuracy = {
        name: (field_correct[name] / field_total[name] if field_total[name] else None)
        for name in EVALUATED_FIELDS
    }
    total_correct = sum(field_correct.values())
    total_fields = sum(field_total.values())

    return {
        "provider": provider_name,
        "documents_evaluated": len(results),
        "errors": errors,
        "overall_field_accuracy": total_correct / total_fields if total_fields else None,
        "per_field_accuracy": per_field_accuracy,
        "critical_field_accuracy": critical_correct / critical_total if critical_total else None,
        "critical_errors": sorted(critical_errors, key=lambda e: (e["field"], e["doc_id"])),
        "avg_confidence_when_correct": statistics.mean(confidences_when_correct)
        if confidences_when_correct
        else None,
        "avg_confidence_when_wrong": statistics.mean(confidences_when_wrong)
        if confidences_when_wrong
        else None,
        "avg_latency_seconds": statistics.mean(latencies) if latencies else None,
        "total_estimated_cost_usd": sum(costs) if costs else 0.0,
        "line_item_count_match_rate": line_item_count_matches / line_item_count_total
        if line_item_count_total
        else None,
    }


def render_report(evaluations: list[dict]) -> str:
    lines = ["# Extraction provider spike — results", ""]
    lines.append(
        "Generated by `spike/evaluate.py`. Feeds the provider decision in "
        "`docs/extraction-strategy.md` and `docs/adr/0006-extraction-provider.md`.\n\n"
        "**This report is deliberately not just an aggregate score.** Per the approved "
        "evaluation methodology, business-critical fields (total, currency, invoice number, "
        "invoice date, due date, tax) are broken out separately from the overall figure, and "
        "every critical-field miss is listed individually below — see "
        "\"Business-critical field accuracy\" and \"Critical errors\", not just the summary table."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Provider | Docs | Errors | Overall field accuracy | Critical-field accuracy | "
        "Avg confidence (correct) | Avg confidence (wrong) | Avg latency (s) | Total cost | "
        "Line-item count match |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for ev in evaluations:
        if ev.get("documents_evaluated", 0) == 0:
            lines.append(f"| {ev['provider']} | 0 | — | not run | — | — | — | — | — | — |")
            continue
        latency = f"{ev['avg_latency_seconds']:.2f}" if ev["avg_latency_seconds"] else "—"
        cells = [
            ev["provider"],
            str(ev["documents_evaluated"]),
            str(ev["errors"]),
            _pct(ev["overall_field_accuracy"]),
            _pct(ev["critical_field_accuracy"]),
            _pct(ev["avg_confidence_when_correct"]),
            _pct(ev["avg_confidence_when_wrong"]),
            latency,
            f"${ev['total_estimated_cost_usd']:.4f}",
            _pct(ev["line_item_count_match_rate"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("## Business-critical field accuracy")
    lines.append("")
    lines.append(
        "Critical fields: " + ", ".join(CRITICAL_FIELDS) + ". Scored separately from the "
        "overall figure above because a miss here is a financial/compliance risk, not just "
        "an inconvenience — see `docs/extraction-strategy.md`."
    )
    lines.append("")
    lines.append("| Provider | " + " | ".join(CRITICAL_FIELDS) + " | **All critical fields** |")
    lines.append("|---|" + "---|" * (len(CRITICAL_FIELDS) + 1))
    for ev in evaluations:
        if ev.get("documents_evaluated", 0) == 0:
            continue
        cells = [_pct(ev["per_field_accuracy"].get(f)) for f in CRITICAL_FIELDS]
        overall_critical = _pct(ev["critical_field_accuracy"])
        row = f"| {ev['provider']} | " + " | ".join(cells) + f" | **{overall_critical}** |"
        lines.append(row)

    lines.append("")
    lines.append("## Critical errors (every miss, named)")
    lines.append("")
    any_errors = any(ev.get("critical_errors") for ev in evaluations)
    if not any_errors:
        lines.append("None recorded yet — no results to evaluate, or every critical field matched.")
    else:
        lines.append("| Provider | Document | Difficulty | Field | Expected | Got | Confidence |")
        lines.append("|---|---|---|---|---|---|---|")
        for ev in evaluations:
            for err in ev.get("critical_errors", []):
                confidence = f"{err['confidence']:.2f}" if err["confidence"] is not None else "—"
                row = (
                    f"| {ev['provider']} | {err['doc_id']} | {err['difficulty']} | "
                    f"{err['field']} | `{err['expected']}` | `{err['got']}` | {confidence} |"
                )
                lines.append(row)

    lines.append("")
    lines.append("## Per-field accuracy (all evaluated fields)")
    lines.append("")
    lines.append("| Provider | " + " | ".join(EVALUATED_FIELDS) + " |")
    lines.append("|---|" + "---|" * len(EVALUATED_FIELDS))
    for ev in evaluations:
        if ev.get("documents_evaluated", 0) == 0:
            continue
        cells = [_pct(ev["per_field_accuracy"].get(f)) for f in EVALUATED_FIELDS]
        lines.append(f"| {ev['provider']} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(
        "## Reading this\n\n"
        "- **A high overall accuracy with a lower critical-field accuracy is a real warning "
        "sign, not a rounding error** — it means a provider is getting the easy/cosmetic "
        "fields right (vendor name, subtotal) while missing the fields that actually cause a "
        "duplicate payment, a compliance problem, or a wrong currency transfer. Decide from "
        "the critical-field numbers first, the overall number second.\n"
        "- **Avg confidence (correct) vs (wrong)** is the confidence-calibration check from "
        "`docs/extraction-strategy.md`: if a provider's wrong answers carry confidence nearly "
        "as high as its correct ones, its confidence score is not a reliable review-routing "
        "signal on its own, regardless of what its documentation claims.\n"
        "- **Line-item count match** is a coarse proxy (does the provider find the right number "
        "of line items at all) — a real per-line accuracy pass is worth doing by hand on a few "
        "documents before trusting this number.\n"
        "- Cross-reference the **Critical errors** table's `difficulty` column against "
        "`spike/invoice_specs.py`'s `notes` for that document — a miss on an `easy` document is "
        "a much stronger signal than a miss on a `hard` one deliberately designed to be "
        "ambiguous.\n"
        "- These results are only as good as the ground truth they're checked against — see "
        "`spike/README.md` for how it was built (generated first, authoritative by "
        "construction, not transcribed from the rendered document)."
    )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else "—"


def main() -> None:
    ground_truth = _load_ground_truth()
    if not ground_truth:
        print(f"No ground truth files found in {GROUND_TRUTH_DIR}. See spike/README.md.")
        return

    evaluations = [evaluate_provider(name, ground_truth) for name in ("azure", "mistral", "claude")]
    report = render_report(evaluations)
    REPORT_PATH.write_text(report)
    print(report)
    print(f"\nWritten to {REPORT_PATH}")


if __name__ == "__main__":
    main()
