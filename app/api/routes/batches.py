"""Bulk preparation endpoints.

These endpoints prepare applications in bulk and nothing more. There is no submit route
here any more than there is one on ``/api/applications``: a batch ends with jobs sitting in
the review queue and unanswered questions sitting in the action inbox.

A run started with ``run_in_background`` executes on a worker thread so a hundred-job run
does not hold an HTTP request open. Progress is readable from ``GET /api/batches/{id}``
while it runs, because every item is committed as it completes.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import Authorized, DbSession, Llm, Profile
from app.api.errors import ApiError
from app.db.models import BatchRun, BatchStatus
from app.db.repositories import BatchRunRepository, JobRepository
from app.logging_conf import get_logger
from app.schemas.batch import (
    BatchItemRead,
    BatchPreview,
    BatchRunDetail,
    BatchRunRead,
    BatchStartRequest,
)
from app.schemas.common import Page
from app.services.batch import (
    BatchOptions,
    BatchPreparationService,
    BatchSelection,
    select_job_ids,
)

router = APIRouter(prefix="/api/batches", tags=["batches"], dependencies=[Authorized])

logger = get_logger(__name__)


def _selection(request: BatchStartRequest) -> BatchSelection:
    data = request.selection
    return BatchSelection(
        min_score=data.min_score,
        bands=list(data.bands),
        max_age_days=data.max_age_days,
        titles=list(data.titles),
        sources=list(data.sources),
        include_filtered=data.include_filtered,
        include_unscored=data.include_unscored,
        limit=data.limit,
    )


def _detail(session, run: BatchRun) -> BatchRunDetail:
    runs = BatchRunRepository(session)
    jobs = JobRepository(session)
    items: list[BatchItemRead] = []
    for item in runs.items(run.id):
        job = jobs.get(item.job_id)
        items.append(
            BatchItemRead.model_validate(item).model_copy(
                update={
                    "job_title": job.title if job else "",
                    "job_company": job.company if job else "",
                }
            )
        )
    return BatchRunDetail.model_validate(run).model_copy(
        update={"items": items, "status_counts": runs.item_status_counts(run.id)}
    )


@router.post("/preview", response_model=BatchPreview, summary="Count the jobs a run would cover")
def preview_batch(request: BatchStartRequest, session: DbSession, profile: Profile) -> BatchPreview:
    job_ids = select_job_ids(session, profile, _selection(request))
    return BatchPreview(job_ids=job_ids, total=len(job_ids))


@router.post(
    "",
    response_model=BatchRunDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare applications for many jobs at once",
)
def start_batch(
    request: BatchStartRequest,
    session: DbSession,
    profile: Profile,
    provider: Llm,
) -> BatchRunDetail:
    runs = BatchRunRepository(session)
    active = runs.active()
    if active is not None:
        raise ApiError(
            "batch_already_running",
            f"Batch run {active.id} is still running. Wait for it to finish or cancel it.",
            status.HTTP_409_CONFLICT,
        )

    service = BatchPreparationService(provider=provider)
    run = service.create_run(
        session,
        profile,
        _selection(request),
        BatchOptions(
            concurrency=request.concurrency,
            max_attempts=request.max_attempts,
            dry_run=request.dry_run,
            include_cover_letter=request.include_cover_letter,
        ),
    )
    if run.total_items == 0:
        runs.finish(
            run,
            BatchStatus.COMPLETED,
            "no job matched this selection, so there was nothing to prepare",
        )
        return _detail(session, run)

    run_id = run.id
    include_letter = request.include_cover_letter
    session.commit()

    if request.run_in_background:
        thread = threading.Thread(
            target=_execute_quietly,
            args=(run_id, include_letter),
            name=f"batch-run-{run_id}",
            daemon=True,
        )
        thread.start()
    else:
        service.execute(run_id, include_cover_letter=include_letter)

    refreshed = runs.get(run_id)
    assert refreshed is not None
    session.refresh(refreshed)
    return _detail(session, refreshed)


def _execute_quietly(run_id: int, include_cover_letter: bool) -> None:
    """Run a batch on a worker thread, logging instead of raising into nothing."""
    try:
        BatchPreparationService().execute(run_id, include_cover_letter=include_cover_letter)
    except Exception as exc:  # noqa: BLE001 - a thread must not die silently
        logger.error("background batch run failed", extra={"run_id": run_id, "reason": str(exc)})


@router.get("", response_model=Page[BatchRunRead], summary="List batch runs")
def list_batches(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BatchRunRead]:
    runs = BatchRunRepository(session)
    return Page(
        items=[BatchRunRead.model_validate(run) for run in runs.list(limit=limit, offset=offset)],
        total=runs.count(),
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=BatchRunDetail, summary="One batch run with its items")
def get_batch(run_id: int, session: DbSession) -> BatchRunDetail:
    run = BatchRunRepository(session).get(run_id)
    if run is None:
        raise ApiError("not_found", f"No batch run with id {run_id}.", status.HTTP_404_NOT_FOUND)
    return _detail(session, run)


@router.post("/{run_id}/cancel", response_model=BatchRunDetail, summary="Stop a running batch")
def cancel_batch(run_id: int, session: DbSession, provider: Llm) -> BatchRunDetail:
    runs = BatchRunRepository(session)
    run = runs.get(run_id)
    if run is None:
        raise ApiError("not_found", f"No batch run with id {run_id}.", status.HTTP_404_NOT_FOUND)
    if run.finished_at is not None:
        raise ApiError(
            "batch_already_finished",
            f"Batch run {run_id} finished at {run.finished_at.isoformat()}.",
            status.HTTP_409_CONFLICT,
        )
    BatchPreparationService(provider=provider).request_cancel(session, run)
    return _detail(session, run)


@router.post(
    "/{run_id}/resume",
    response_model=BatchRunDetail,
    summary="Continue an interrupted or cancelled batch",
)
def resume_batch(
    run_id: int,
    session: DbSession,
    provider: Llm,
    run_in_background: Annotated[bool, Query()] = True,
) -> BatchRunDetail:
    runs = BatchRunRepository(session)
    run = runs.get(run_id)
    if run is None:
        raise ApiError("not_found", f"No batch run with id {run_id}.", status.HTTP_404_NOT_FOUND)
    if run.status in (BatchStatus.RUNNING, BatchStatus.CANCELLING):
        raise ApiError(
            "batch_already_running",
            f"Batch run {run_id} is already running.",
            status.HTTP_409_CONFLICT,
        )
    pending = runs.pending_items(run_id)
    if not pending:
        raise ApiError(
            "nothing_to_resume",
            f"Every item in batch run {run_id} already reached a final state.",
            status.HTTP_409_CONFLICT,
        )

    runs.clear_cancel(run)
    include_letter = True
    session.commit()
    if run_in_background:
        threading.Thread(
            target=_execute_quietly,
            args=(run_id, include_letter),
            name=f"batch-resume-{run_id}",
            daemon=True,
        ).start()
    else:
        BatchPreparationService(provider=provider).execute(
            run_id, include_cover_letter=include_letter
        )
    refreshed = runs.get(run_id)
    assert refreshed is not None
    session.refresh(refreshed)
    return _detail(session, refreshed)
