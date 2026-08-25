"""Phase 4 — Document Ingestion & Storage; Phase 6 — Extraction Integration
& Normalization. See docs/workflow.md steps 1-2 and docs/api.md.

Extraction runs synchronously, inline in the upload request, rather than
being handed off to a background worker — deliberately, because no
worker exists yet (that's Phase 13's job: retries, crash recovery,
decoupling from the HTTP request lifecycle). This is the honest minimal
scope for Phase 6: wire the provider and the state transitions, not
build reliability infrastructure ahead of its own named phase.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.extraction import ExtractionProvider, MistralExtractionProvider, build_extraction_result
from app.ingestion import (
    FileTooLarge,
    UnsupportedFileType,
    check_size,
    content_hash,
    sniff_mime_type,
)
from app.models import Document, DocumentState, ExtractionResult, StateHistory
from app.schemas import DocumentOut, ExtractionResultOut
from app.storage import LocalStorageProvider, StorageProvider

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_api_key)])


def get_storage_provider() -> StorageProvider:
    return LocalStorageProvider(base_dir=Path(get_settings().storage_local_dir))


def get_extraction_provider() -> ExtractionProvider:
    return MistralExtractionProvider(api_key=get_settings().mistral_api_key)


def _run_extraction(
    session: Session, document: Document, *, content: bytes, provider: ExtractionProvider
) -> None:
    """Advances a RECEIVED document through EXTRACTING to EXTRACTED, or to
    FAILED on any error. Writes the state_history audit trail either way.
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
        return

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

    _run_extraction(session, document, content=raw, provider=extraction_provider)

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
