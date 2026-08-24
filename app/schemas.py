"""API request/response shapes. See docs/api.md."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import DocumentState


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: DocumentState
    original_filename: str
    mime_type: str
    content_hash: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
