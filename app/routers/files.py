"""Phase 10 — serves a document's original file via a short-lived,
HMAC-signed URL (StorageProvider.sign_url), not the bearer-token auth
every other router requires. A signed link is meant to be dropped
straight into a reviewer's browser or an <img>/<iframe> src for the
side-by-side review UI; the signature and its expiry ARE the
authorization here — see docs/security.md, "Unauthorized document
access", and app/storage.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Document
from app.routers.documents import get_storage_provider
from app.storage import StorageProvider, verify_signed_url

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{storage_path:path}")
def get_file(
    storage_path: str,
    expires: int,
    signature: str,
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
):
    if not verify_signed_url(
        storage_path=storage_path,
        expires=expires,
        signature=signature,
        secret_key=get_settings().app_secret_key,
    ):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")

    document = session.scalar(select(Document).where(Document.storage_path == storage_path))
    if document is None:
        raise HTTPException(status_code=404, detail="File not found")

    content = storage.get(storage_path=storage_path)
    return Response(content=content, media_type=document.mime_type)
