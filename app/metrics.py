"""Phase 16 — Observability & Business Metrics. Pure aggregation over
plain data — no I/O, no DB session; app/routers/dashboard.py owns the
queries. See docs/cost-strategy.md, "What is measured vs. what is
estimated": straight-through rate, review rate, correction rate, and
average processing time are all genuinely measured from state_history
timestamps — no assumption baked in. Estimated time saved is the one
number here that's explicitly an *estimate*, built from a stated,
adjustable assumption, never presented as measured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class DashboardMetrics:
    total_processed: int
    straight_through_count: int
    straight_through_rate: float
    needs_review_count: int
    review_rate: float
    corrected_count: int
    correction_rate: float
    average_processing_time_seconds: float | None
    estimated_manual_minutes_per_document: float
    estimated_minutes_saved: float


def compute_dashboard_metrics(
    *,
    total_processed: int,
    needs_review_document_ids: set[uuid.UUID],
    corrected_document_ids: set[uuid.UUID],
    processing_durations_seconds: list[float],
    estimated_manual_minutes_per_document: float,
) -> DashboardMetrics:
    """`total_processed` excludes documents still actively in flight
    (RECEIVED/EXTRACTING/VALIDATING) — everything else, including a
    document currently sitting unresolved in NEEDS_REVIEW, already
    represents a real, measured outcome ("did this need a person"),
    per docs/workflow.md.

    `needs_review_document_ids` is every document that has ever had a
    NEEDS_REVIEW transition (state_history), regardless of whether it
    was later corrected — a document can only reach NEEDS_REVIEW once,
    since the state machine has no path back into it.

    `corrected_document_ids` is every document with at least one
    review_events row — always a subset of `needs_review_document_ids`.

    `processing_durations_seconds` covers only documents that have
    reached a terminal state (COMPLETED/REJECTED/DUPLICATE/FAILED) —
    a document still in progress has no complete duration to measure
    yet, and including a partial one would silently understate it.
    """
    needs_review_count = len(needs_review_document_ids)
    straight_through_count = total_processed - needs_review_count
    corrected_count = len(corrected_document_ids)

    straight_through_rate = straight_through_count / total_processed if total_processed else 0.0
    review_rate = needs_review_count / total_processed if total_processed else 0.0
    correction_rate = corrected_count / needs_review_count if needs_review_count else 0.0
    average_processing_time_seconds = (
        sum(processing_durations_seconds) / len(processing_durations_seconds)
        if processing_durations_seconds
        else None
    )
    estimated_minutes_saved = straight_through_count * estimated_manual_minutes_per_document

    return DashboardMetrics(
        total_processed=total_processed,
        straight_through_count=straight_through_count,
        straight_through_rate=straight_through_rate,
        needs_review_count=needs_review_count,
        review_rate=review_rate,
        corrected_count=corrected_count,
        correction_rate=correction_rate,
        average_processing_time_seconds=average_processing_time_seconds,
        estimated_manual_minutes_per_document=estimated_manual_minutes_per_document,
        estimated_minutes_saved=estimated_minutes_saved,
    )
