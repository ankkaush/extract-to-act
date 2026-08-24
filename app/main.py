"""FastAPI application entrypoint. See PLAN.md for what each router adds
and which phase introduced it.
"""

from fastapi import FastAPI

from app.config import get_settings
from app.routers import documents

app = FastAPI(title="Extract to Act", version="0.1.0")
app.include_router(documents.router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": "extract-to-act", "env": settings.app_env}
