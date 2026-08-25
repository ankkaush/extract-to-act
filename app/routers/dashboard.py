"""Phase 16 — Observability & Business Metrics. See docs/workflow.md
step 10 and docs/api.md. Everything here is computed live from
existing tables via aggregation queries — no separate metrics-writing
system, per docs/data-model.md's design note; there's no volume at
this project's scale that would justify one.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.metrics import compute_dashboard_metrics
from app.models import Document, DocumentState, ReviewEvent, StateHistory
from app.schemas import DashboardMetricsOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_api_key)])

# Still actively working toward an outcome — excluded from the
# denominator so the rates below aren't diluted by documents that
# haven't reached one yet. Everything else, including a document
# currently sitting unresolved in NEEDS_REVIEW, already represents a
# real, measured outcome — see app/metrics.py.
IN_FLIGHT_STATES = (DocumentState.RECEIVED, DocumentState.EXTRACTING, DocumentState.VALIDATING)
TERMINAL_STATES = (
    DocumentState.COMPLETED,
    DocumentState.REJECTED,
    DocumentState.DUPLICATE,
    DocumentState.FAILED,
)


@router.get("", response_model=DashboardMetricsOut)
def get_dashboard(session: Session = Depends(get_session)):
    total_processed = session.scalar(
        select(func.count()).select_from(Document).where(Document.state.notin_(IN_FLIGHT_STATES))
    )

    needs_review_document_ids = set(
        session.scalars(
            select(StateHistory.document_id)
            .where(StateHistory.to_state == DocumentState.NEEDS_REVIEW)
            .distinct()
        ).all()
    )

    corrected_document_ids = set(
        session.scalars(select(ReviewEvent.document_id).distinct()).all()
    )

    duration_rows = session.execute(
        select(
            StateHistory.document_id,
            func.max(StateHistory.created_at) - func.min(StateHistory.created_at),
        )
        .join(Document, Document.id == StateHistory.document_id)
        .where(Document.state.in_(TERMINAL_STATES))
        .group_by(StateHistory.document_id)
    ).all()
    processing_durations_seconds = [duration.total_seconds() for _, duration in duration_rows]

    metrics = compute_dashboard_metrics(
        total_processed=total_processed or 0,
        needs_review_document_ids=needs_review_document_ids,
        corrected_document_ids=corrected_document_ids,
        processing_durations_seconds=processing_durations_seconds,
        estimated_manual_minutes_per_document=get_settings().estimated_manual_minutes_per_document,
    )
    return metrics
