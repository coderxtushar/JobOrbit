"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__, scheduler
from app.api.errors import register_error_handlers
from app.api.routes import (
    answers,
    applications,
    autoapply,
    batches,
    health,
    jobs,
    platforms,
    profile,
    resumes,
    searches,
    sources,
)
from app.config import Settings, get_settings
from app.db.base import create_all, get_engine, session_scope
from app.db.repositories import BatchRunRepository
from app.logging_conf import configure_logging, get_logger

logger = get_logger(__name__)

DESCRIPTION = """
A local-first job search and application assistant.

**Compliance.** This API has no endpoint that submits a job application, and no source
adapter scrapes a job platform's website. Discovery works through files you supply,
job-alert emails in your own mailbox, and the public job-board APIs that Greenhouse, Lever
and Workable publish for a company's own board. `POST /api/batches` prepares many
applications at once and still stops at review. See `GET /api/sources` for
each source's capabilities and the policy basis for them, and `GET /api/diagnostics` for
why a source is or is not returning jobs.

**Without an API key.** Every endpoint here works with no LLM configured. Scoring is
rule-based and fully explained in each job's match object.
"""


def _require_current_schema() -> None:
    """Refuse to start against a database missing columns the models declare.

    ``create_all`` adds missing *tables* but never missing *columns*, so an existing
    database that skipped a migration would otherwise fail later, mid-run, with an
    unhelpful SQL error. The fix is one command, so say it.
    """
    from sqlalchemy import inspect

    from app.db.models import Base

    inspector = inspect(get_engine())
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        missing.extend(
            f"{table.name}.{column.name}" for column in table.columns if column.name not in present
        )
    if missing:
        raise RuntimeError(
            "The database is older than this version of JobOrbit (missing "
            + ", ".join(missing[:6])
            + (" …" if len(missing) > 6 else "")
            + "). Back it up, then run: .venv/bin/alembic upgrade head"
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.ensure_directories()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        create_all(get_engine())
        _require_current_schema()
        # A batch run left RUNNING belongs to a process that no longer exists. Reconcile
        # it to INTERRUPTED now so its remaining items become resumable instead of
        # appearing active forever.
        with session_scope() as session:
            interrupted = BatchRunRepository(session).mark_interrupted()
        if interrupted:
            logger.warning("reconciled interrupted batch runs", extra={"runs": interrupted})
        # The same for auto-apply runs, with one difference that matters: an attempt the
        # dead worker left mid-dispatch is settled from its checkpoint, so one that may
        # have pressed Submit becomes an unknown outcome and is never re-sent.
        from app.services.autoapply_control import cleanup_evidence, recover_interrupted_runs

        with session_scope() as session:
            recover_interrupted_runs(session, stale_after_s=settings.run_stale_after_s)
            cleanup_evidence(
                session,
                data_dir=settings.data_dir,
                retention_days=settings.evidence_retention_days,
            )
        scheduler.start(settings)
        logger.info(
            "application started",
            extra={
                "version": __version__,
                "loopback_only": settings.is_loopback_only,
                "llm_enabled": settings.llm_enabled,
                "scheduler_enabled": settings.scheduler_enabled,
            },
        )
        try:
            yield
        finally:
            scheduler.shutdown()
            from app.browser.session import shutdown_browser

            shutdown_browser()
            logger.info("application stopped")

    app = FastAPI(
        title="Job Search Assistant",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(profile.router)
    app.include_router(resumes.router)
    app.include_router(jobs.router)
    app.include_router(applications.router)
    app.include_router(batches.router)
    app.include_router(autoapply.router)
    app.include_router(answers.router)
    app.include_router(platforms.router)
    app.include_router(searches.router)
    app.include_router(sources.router)
    return app


app = create_app()


def main() -> None:
    """Entry point for ``python -m app.main``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        reload=False,
    )


if __name__ == "__main__":
    main()
