"""Static bearer token check for mutating endpoints. See
docs/adr/0008-api-authentication.md for why this is enough for now and
what it deliberately doesn't solve yet (per-actor attribution).
"""

from fastapi import Header, HTTPException

from app.config import get_settings


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
