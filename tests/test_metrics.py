"""Tier 1 (docs/testing-strategy.md): pure metrics-aggregation logic,
no I/O, no DB session.
"""

import uuid

from app.metrics import compute_dashboard_metrics

D1, D2, D3, D4 = (uuid.uuid4() for _ in range(4))


def test_no_documents_processed_yields_zeroed_metrics():
    metrics = compute_dashboard_metrics(
        total_processed=0,
        needs_review_document_ids=set(),
        corrected_document_ids=set(),
        processing_durations_seconds=[],
        estimated_manual_minutes_per_document=8.0,
    )
    assert metrics.total_processed == 0
    assert metrics.straight_through_rate == 0.0
    assert metrics.review_rate == 0.0
    assert metrics.correction_rate == 0.0
    assert metrics.average_processing_time_seconds is None
    assert metrics.estimated_minutes_saved == 0.0


def test_all_straight_through():
    metrics = compute_dashboard_metrics(
        total_processed=4,
        needs_review_document_ids=set(),
        corrected_document_ids=set(),
        processing_durations_seconds=[10.0, 20.0],
        estimated_manual_minutes_per_document=8.0,
    )
    assert metrics.straight_through_count == 4
    assert metrics.straight_through_rate == 1.0
    assert metrics.needs_review_count == 0
    assert metrics.review_rate == 0.0
    assert metrics.correction_rate == 0.0  # 0/0 -> 0.0, not a ZeroDivisionError
    assert metrics.average_processing_time_seconds == 15.0
    assert metrics.estimated_minutes_saved == 4 * 8.0


def test_mixed_review_and_correction_rates():
    metrics = compute_dashboard_metrics(
        total_processed=4,
        needs_review_document_ids={D1, D2},
        corrected_document_ids={D1},  # D2 was rejected, not corrected
        processing_durations_seconds=[],
        estimated_manual_minutes_per_document=8.0,
    )
    assert metrics.total_processed == 4
    assert metrics.needs_review_count == 2
    assert metrics.review_rate == 0.5
    assert metrics.straight_through_count == 2
    assert metrics.straight_through_rate == 0.5
    assert metrics.corrected_count == 1
    assert metrics.correction_rate == 0.5


def test_estimated_minutes_saved_only_counts_straight_through_documents():
    # 5 processed, 2 needed review -> only the 3 untouched ones count
    # toward the estimate, per app/metrics.py's stated definition.
    metrics = compute_dashboard_metrics(
        total_processed=5,
        needs_review_document_ids={D1, D2},
        corrected_document_ids={D1, D2},
        processing_durations_seconds=[],
        estimated_manual_minutes_per_document=10.0,
    )
    assert metrics.straight_through_count == 3
    assert metrics.estimated_minutes_saved == 30.0


def test_average_processing_time_ignores_nothing_it_is_given():
    metrics = compute_dashboard_metrics(
        total_processed=3,
        needs_review_document_ids=set(),
        corrected_document_ids=set(),
        processing_durations_seconds=[5.0, 15.0, 100.0],
        estimated_manual_minutes_per_document=8.0,
    )
    assert metrics.average_processing_time_seconds == 40.0
