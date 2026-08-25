"""Phase 4 — Document Ingestion & Storage; Phase 6 — Extraction Integration
& Normalization; Phase 7 — Deterministic Validation. See
docs/workflow.md steps 1-3 and docs/api.md.

Extraction and validation both run synchronously, inline in the upload
request, rather than being handed off to a background worker —
deliberately, because no worker exists yet (that's Phase 13's job:
retries, crash recovery, decoupling from the HTTP request lifecycle).
This is the honest minimal scope for each phase as it's built: wire the
logic and the state transitions, not build reliability infrastructure
ahead of its own named phase.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.duplicate_detection import find_content_duplicate, find_exact_hash_duplicate
from app.extraction import ExtractionProvider, MistralExtractionProvider, build_extraction_result
from app.ingestion import (
    FileTooLarge,
    UnsupportedFileType,
    check_size,
    content_hash,
    sniff_mime_type,
)
from app.models import (
    Document,
    DocumentState,
    ExtractionResult,
    StateHistory,
    ValidationResult,
    Vendor,
)
from app.schemas import DocumentOut, ExtractionResultOut
from app.storage import LocalStorageProvider, StorageProvider
from app.validation import run_validation
from app.vendor_matching import check_vendor_known

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_api_key)])


def get_storage_provider() -> StorageProvider:
    settings = get_settings()
    return LocalStorageProvider(
        base_dir=Path(settings.storage_local_dir), secret_key=settings.app_secret_key
    )


def get_extraction_provider() -> ExtractionProvider:
    return MistralExtractionProvider(api_key=get_settings().mistral_api_key)


def _check_exact_hash_duplicate(session: Session, document: Document) -> bool:
    """RECEIVED -> DUPLICATE, before extraction ever runs — see
    docs/state-machine.md's discovered RECEIVED -> DUPLICATE transition
    and app/duplicate_detection.py. Returns True if the document was
    marked DUPLICATE (caller should stop processing it further).
    """
    candidates = session.execute(
        select(Document.id, Document.content_hash)
        .where(Document.content_hash == document.content_hash)
        .where(Document.id != document.id)
        .where(Document.state != DocumentState.FAILED)
    ).all()

    match = find_exact_hash_duplicate(document.content_hash, [tuple(row) for row in candidates])
    if not match.is_duplicate:
        return False

    document.state = DocumentState.DUPLICATE
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.RECEIVED,
            to_state=DocumentState.DUPLICATE,
            reason=match.reason,
        )
    )
    session.commit()
    return True


def _check_content_duplicate(
    session: Session, document: Document, extraction_result: ExtractionResult
) -> bool:
    """VALIDATING -> DUPLICATE, for the same invoice arriving as a
    different file. Returns True if the document was marked DUPLICATE
    (caller should skip the remaining validation rules — there's no
    point checking required fields on a document about to be discarded).
    """
    candidates = session.execute(
        select(
            ExtractionResult.document_id,
            ExtractionResult.vendor_name,
            ExtractionResult.invoice_number,
            ExtractionResult.total,
            ExtractionResult.invoice_date,
        )
        .join(Document, Document.id == ExtractionResult.document_id)
        .where(ExtractionResult.document_id != document.id)
        .where(Document.state != DocumentState.FAILED)
    ).all()

    match = find_content_duplicate(
        vendor_name=extraction_result.vendor_name,
        invoice_number=extraction_result.invoice_number,
        total=extraction_result.total,
        invoice_date=extraction_result.invoice_date,
        candidates=[tuple(row) for row in candidates],
    )
    if not match.is_duplicate:
        return False

    document.state = DocumentState.DUPLICATE
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.VALIDATING,
            to_state=DocumentState.DUPLICATE,
            reason=match.reason,
        )
    )
    session.commit()
    return True


def _run_extraction(
    session: Session, document: Document, *, content: bytes, provider: ExtractionProvider
) -> ExtractionResult | None:
    """Advances a RECEIVED document through EXTRACTING to EXTRACTED, or to
    FAILED on any error. Writes the state_history audit trail either way.
    Returns the persisted ExtractionResult on success, None on failure.
    See docs/state-machine.md and docs/reliability.md — this is a
    technical failure path (FAILED), not a business exception
    (NEEDS_REVIEW), since extraction itself either worked or didn't.
    """
    document.state = DocumentState.EXTRACTING
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.RECEIVED,
            to_state=DocumentState.EXTRACTING,
            reason="extraction started",
        )
    )
    session.commit()

    try:
        output = provider.extract(content=content, filename=document.original_filename)
    except Exception as exc:  # noqa: BLE001 — recorded as a dead-lettered failure, not re-raised
        document.state = DocumentState.FAILED
        session.add(
            StateHistory(
                document_id=document.id,
                from_state=DocumentState.EXTRACTING,
                to_state=DocumentState.FAILED,
                # Exception type + message only — never raw provider
                # request/response content, which could carry sensitive
                # document data. See docs/security.md.
                reason=f"extraction failed: {type(exc).__name__}: {exc}",
            )
        )
        session.commit()
        return None

    extraction_result = build_extraction_result(document.id, output)
    session.add(extraction_result)
    document.state = DocumentState.EXTRACTED
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.EXTRACTING,
            to_state=DocumentState.EXTRACTED,
            reason="extraction succeeded",
        )
    )
    session.commit()
    return extraction_result


def _run_validation_step(
    session: Session, document: Document, extraction_result: ExtractionResult
) -> None:
    """Advances an EXTRACTED document through VALIDATING to either
    VALIDATED (every rule passed) or NEEDS_REVIEW (at least one failed).
    Never FAILED — a validation failure is a business exception, not a
    technical one; see docs/reliability.md's business-exception vs.
    technical-failure distinction. Every rule's individual result is
    persisted to validation_results, not just the summary reason on
    state_history — see docs/data-model.md.

    Vendor matching (Phase 8) is folded into this same step rather than
    a separate state — docs/workflow.md lists it as its own conceptual
    step, but the state machine has no dedicated "matching" state; both
    are deterministic checks feeding the same VALIDATED/NEEDS_REVIEW
    decision.
    """
    document.state = DocumentState.VALIDATING
    session.add(
        StateHistory(
            document_id=document.id,
            from_state=DocumentState.EXTRACTED,
            to_state=DocumentState.VALIDATING,
            reason="validation started",
        )
    )
    session.commit()

    if _check_content_duplicate(session, document, extraction_result):
        # Already transitioned to DUPLICATE — no point running the other
        # rules on a document about to be discarded either way.
        return

    rule_results = run_validation(extraction_result)

    known_vendors = session.execute(select(Vendor.id, Vendor.name)).all()
    rule_results.append(check_vendor_known(extraction_result.vendor_name, list(known_vendors)))

    failed_rule_names = []
    for rule in rule_results:
        session.add(
            ValidationResult(
                document_id=document.id,
                rule_name=rule.rule_name,
                passed=rule.passed,
                reason=rule.reason,
            )
        )
        if not rule.passed:
            failed_rule_names.append(rule.rule_name)

    if failed_rule_names:
        document.state = DocumentState.NEEDS_REVIEW
        session.add(
            StateHistory(
                document_id=document.id,
                from_state=DocumentState.VALIDATING,
                to_state=DocumentState.NEEDS_REVIEW,
                reason=f"{len(failed_rule_names)} validation rule(s) failed: "
                + ", ".join(failed_rule_names),
            )
        )
    else:
        document.state = DocumentState.VALIDATED
        session.add(
            StateHistory(
                document_id=document.id,
                from_state=DocumentState.VALIDATING,
                to_state=DocumentState.VALIDATED,
                reason="all validation rules passed",
            )
        )
    session.commit()


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
    extraction_provider: ExtractionProvider = Depends(get_extraction_provider),
):
    key = idempotency_key or str(uuid.uuid4())

    existing = session.scalar(select(Document).where(Document.idempotency_key == key))
    if existing is not None:
        # Same request retried — return the existing record rather than
        # creating a second one. See docs/reliability.md, idempotency
        # scenario 1.
        return existing

    raw = await file.read()

    try:
        check_size(raw, max_bytes=get_settings().max_upload_size_bytes)
    except FileTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    try:
        mime_type = sniff_mime_type(raw)
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    storage_path = storage.put(content=raw, suggested_name=file.filename or "upload")

    document = Document(
        content_hash=content_hash(raw),
        idempotency_key=key,
        storage_path=storage_path,
        original_filename=file.filename or "upload",
        mime_type=mime_type,
        state=DocumentState.RECEIVED,
    )
    session.add(document)
    session.flush()

    session.add(
        StateHistory(
            document_id=document.id,
            from_state=None,
            to_state=DocumentState.RECEIVED,
            reason="uploaded",
        )
    )
    session.commit()

    if _check_exact_hash_duplicate(session, document):
        # Already transitioned to DUPLICATE — never spend a paid
        # extraction call on a file we already know is a re-upload of
        # something already submitted. See PLAN.md Phase 9's stated
        # completion criteria.
        session.refresh(document)
        return document

    extraction_result = _run_extraction(
        session, document, content=raw, provider=extraction_provider
    )
    if extraction_result is not None:
        _run_validation_step(session, document, extraction_result)

    session.refresh(document)
    return document


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, session: Session = Depends(get_session)):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(state: DocumentState | None = None, session: Session = Depends(get_session)):
    query = select(Document).order_by(Document.created_at.desc())
    if state is not None:
        query = query.where(Document.state == state)
    return session.scalars(query).all()


@router.get("/{document_id}/extraction", response_model=ExtractionResultOut)
def get_extraction(document_id: uuid.UUID, session: Session = Depends(get_session)):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    result = session.scalar(
        select(ExtractionResult).where(ExtractionResult.document_id == document_id)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No extraction result for this document yet")
    return result
