"""Generates the 18-document synthetic evaluation set: renders each
InvoiceSpec to a document (spike/samples/) and writes its authoritative
ground truth (spike/ground_truth/) from the same spec data — never
transcribed from the rendered document. See spike/README.md and
PLAN.md Phase 5.

Usage:
    python -m spike.generate_samples
"""

from __future__ import annotations

import json
from pathlib import Path

from spike.degrade import degrade_low_quality_scan, degrade_stamp_scan, rotate_pdf_page
from spike.invoice_specs import INVOICE_SPECS, InvoiceSpec
from spike.render import render_invoice_pdf

SPIKE_DIR = Path(__file__).parent
SAMPLES_DIR = SPIKE_DIR / "samples"
GROUND_TRUTH_DIR = SPIKE_DIR / "ground_truth"


def _generate_one(spec: InvoiceSpec) -> Path:
    pdf_bytes = render_invoice_pdf(spec)

    if spec.degrade == "stamp_scan":
        content, suffix = degrade_stamp_scan(pdf_bytes), ".png"
    elif spec.degrade == "low_quality_scan":
        content, suffix = degrade_low_quality_scan(pdf_bytes), ".png"
    elif spec.rotate_page_degrees:
        content, suffix = rotate_pdf_page(pdf_bytes, spec.rotate_page_degrees), ".pdf"
    else:
        content, suffix = pdf_bytes, ".pdf"

    out_path = SAMPLES_DIR / f"{spec.doc_id}{suffix}"
    out_path.write_bytes(content)
    return out_path


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(INVOICE_SPECS)} synthetic invoices...\n")
    for spec in INVOICE_SPECS:
        out_path = _generate_one(spec)

        gt_path = GROUND_TRUTH_DIR / f"{spec.doc_id}.json"
        gt_path.write_text(json.dumps(spec.ground_truth_json(), indent=2))

        summary = f"{spec.notes[:60]}..."
        print(f"  {spec.doc_id:28s} [{spec.difficulty:6s}] -> {out_path.name:28s}  ({summary})")

    print(f"\nDone. Documents in {SAMPLES_DIR}, ground truth in {GROUND_TRUTH_DIR}.")
    print("Next: set provider credentials and run `python -m spike.run_spike`.")


if __name__ == "__main__":
    main()
