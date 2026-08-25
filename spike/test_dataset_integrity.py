"""Guards the approved 18-document synthetic dataset against silent
drift. spike/ground_truth/*.json is committed (see spike/README.md) —
these tests catch someone editing spike/invoice_specs.py without
regenerating it, or a spec's numbers quietly becoming internally
inconsistent.
"""

import json
from pathlib import Path

from spike.evaluate import CRITICAL_FIELDS
from spike.invoice_specs import INVOICE_SPECS
from spike.schema import EVALUATED_FIELDS

GROUND_TRUTH_DIR = Path(__file__).parent / "ground_truth"


def test_dataset_size_is_within_the_approved_range():
    assert 15 <= len(INVOICE_SPECS) <= 20


def test_doc_ids_are_unique():
    doc_ids = [spec.doc_id for spec in INVOICE_SPECS]
    assert len(set(doc_ids)) == len(doc_ids)


def test_difficulty_is_one_of_the_three_approved_tiers():
    for spec in INVOICE_SPECS:
        assert spec.difficulty in {"easy", "medium", "hard"}, spec.doc_id


def test_every_spec_has_a_committed_ground_truth_file_matching_its_data():
    for spec in INVOICE_SPECS:
        gt_path = GROUND_TRUTH_DIR / f"{spec.doc_id}.json"
        assert gt_path.exists(), f"missing committed ground truth for {spec.doc_id}"
        on_disk = json.loads(gt_path.read_text())
        # Catches the case where invoice_specs.py was edited but
        # `python -m spike.generate_samples` was never rerun to refresh
        # the committed ground truth — a real, easy-to-make mistake.
        assert on_disk == spec.ground_truth_json(), (
            f"{spec.doc_id}: committed ground truth is out of sync with invoice_specs.py "
            "— rerun `python -m spike.generate_samples`"
        )


def test_no_ground_truth_file_is_orphaned():
    spec_ids = {spec.doc_id for spec in INVOICE_SPECS}
    on_disk_ids = {p.stem for p in GROUND_TRUTH_DIR.glob("*.json")}
    assert on_disk_ids == spec_ids


def test_arithmetic_is_internally_consistent():
    # These are synthetic test documents, not real invoices — but they
    # should still add up, since Phase 7's deterministic validation will
    # expect that of a well-formed invoice, and an inconsistent fixture
    # would be confusing evidence, not a useful test case.
    for spec in INVOICE_SPECS:
        expected_total = round(spec.subtotal + spec.tax, 2)
        assert abs(expected_total - round(spec.total, 2)) < 0.02, (
            f"{spec.doc_id}: subtotal ({spec.subtotal}) + tax ({spec.tax}) "
            f"!= total ({spec.total})"
        )


def test_line_item_totals_sum_to_subtotal_where_a_table_exists():
    # Only meaningful for specs with an actual line-item table — inv_04
    # (lump sum) and inv_17 (narrative) have none by design.
    for spec in INVOICE_SPECS:
        if not spec.line_items:
            continue
        summed = round(sum(li.line_total for li in spec.line_items), 2)
        # inv_07 deliberately shows discounted line totals that sum to
        # the post-discount subtotal, which is exactly what's being
        # tested — still must hold arithmetically.
        assert abs(summed - round(spec.subtotal, 2)) < 0.02, (
            f"{spec.doc_id}: line items sum to {summed}, subtotal is {spec.subtotal}"
        )


def test_critical_fields_are_a_subset_of_evaluated_fields():
    # A drift check between spike/evaluate.py and spike/schema.py — if
    # someone renames a field in one but not the other, this fails loudly
    # instead of CRITICAL_FIELDS silently scoring nothing.
    assert set(CRITICAL_FIELDS) <= set(EVALUATED_FIELDS)


def test_at_least_two_documents_force_real_ocr():
    # The approved methodology's minority-of-cases OCR stress test — see
    # spike/README.md. A regression here would mean every document has a
    # text layer and nothing is actually testing OCR quality.
    ocr_forced = [spec for spec in INVOICE_SPECS if spec.degrade is not None]
    assert len(ocr_forced) == 2


def test_currencies_cover_at_least_five_distinct_codes():
    currencies = {spec.currency for spec in INVOICE_SPECS}
    assert len(currencies) >= 5
