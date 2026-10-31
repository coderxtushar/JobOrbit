"""Health check."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import AppSettings, DbSession

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness and dependency check")
def health(session: DbSession, settings: AppSettings) -> dict[str, object]:
    """Report service health. Never includes secrets or personal data."""
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "version": __version__,
        "database": "ok" if database_ok else "unreachable",
        "database_dialect": session.get_bind().dialect.name,
        "llm_provider": settings.llm_provider,
        "llm_enabled": settings.llm_enabled,
        "scheduler_enabled": settings.scheduler_enabled,
        "loopback_only": settings.is_loopback_only,
        "demo_mode": settings.demo_mode,
        "automated_submission_supported": False,
    }
