"""FastAPI application entrypoint.

Phase 2 scope only: an empty, runnable application with configuration
wired up. No business logic, no database access, no routes beyond a
health check — those arrive in later phases per PLAN.md.
"""

from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="Extract to Act", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": "extract-to-act", "env": settings.app_env}
