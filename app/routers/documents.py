"""Phase 4 — Document Ingestion & Storage. See docs/workflow.md step 1 and
docs/api.md. No extraction, validation, or business logic beyond storing
the file and recording RECEIVED — that starts in Phase 5 onward.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.ingestion import (
    FileTooLarge,
    UnsupportedFileType,
    check_size,
    content_hash,
    sniff_mime_type,
)
from app.models import Document, DocumentState, StateHistory
from app.schemas import DocumentOut
from app.storage import LocalStorageProvider, StorageProvider

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_api_key)])


def get_storage_provider() -> StorageProvider:
    return LocalStorageProvider(base_dir=Path(get_settings().storage_local_dir))


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
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
