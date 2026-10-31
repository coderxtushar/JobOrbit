"""Job endpoints.

There is deliberately no endpoint that submits an application. The most that happens here
is shortlisting a job, which is what makes it eligible for preparation.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AppSettings, Authorized, DbSession, Profile, refuse_in_demo_mode
from app.api.errors import ApiError
from app.db.models import ImportRun, ImportStatus, JobStatus, SourceName, utcnow
from app.db.repositories import (
    ApplicationRepository,
    AuditRepository,
    ImportRunRepository,
    JobQuery,
    JobRepository,
    MatchRepository,
    SourceConfigRepository,
)
from app.schemas.common import ActionResult, Page
from app.schemas.job import (
    DiscoverRequest,
    ImportSummary,
    JobDetail,
    JobImportRequest,
    JobRead,
    MatchRead,
    ScoreRequest,
    ScoreSummary,
    SourceReferenceRead,
)
from app.services.ingest import JobIngestService
from app.services.scoring import ScoringService
from app.services.storage import store_import_payload
from app.sources import get_adapter
from app.sources.base import CapabilityNotAvailable, SourceUnavailable
from app.sources.manual_import import ImportParseError, parse_payload

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Authorized])

MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024


def to_job_read(job, session, profile_id: int, *, detail: bool = False) -> JobRead:
    match = MatchRepository(session).get_for_job(job.id, profile_id)
    has_application = ApplicationRepository(session).find_for_job(job.id, profile_id) is not None
    model_class = JobDetail if detail else JobRead
    model = model_class.model_validate(job)
    return model.model_copy(
        update={
            "source_references": [
                SourceReferenceRead.model_validate(reference) for reference in job.source_references
            ],
            "match": MatchRead.model_validate(match) if match is not None else None,
            "duplicate_count": len(JobRepository(session).duplicates_of(job.id)),
            "has_application": has_application,
        }
    )


def _summary(report) -> ImportSummary:
    return ImportSummary(
        import_run_id=report.import_run_id,
        source=report.source,
        status=report.status.value,
        records_received=report.records_received,
        records_invalid=report.records_invalid,
        jobs_created=report.jobs_created,
        jobs_updated=report.jobs_updated,
        duplicates_detected=report.duplicates_detected,
        message=report.message,
        errors=report.errors[:25],
        warnings=report.warnings[:10],
    )


@router.post(
    "/import",
    response_model=ImportSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Import job records as JSON",
)
def import_jobs(
    payload: JobImportRequest, session: DbSession, profile: Profile, settings: AppSettings
) -> ImportSummary:
    refuse_in_demo_mode(settings, "job_import")
    grouped: dict[SourceName, list] = {}
    for record in payload.records:
        grouped.setdefault(record.source, []).append(record)

    primary_source = max(grouped, key=lambda key: len(grouped[key]))
    report = JobIngestService(session).ingest(
        payload.records,
        source=primary_source,
        trigger=payload.trigger,
        run_metadata={"sources": {key.value: len(value) for key, value in grouped.items()}},
    )
    return _summary(report)


@router.post(
    "/import-csv",
    response_model=ImportSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Import job records from a CSV, TSV or JSON file",
)
def import_jobs_csv(
    session: DbSession,
    profile: Profile,
    settings: AppSettings,
    file: UploadFile = File(..., description="CSV, TSV or JSON export of job listings"),
    source: SourceName = Form(SourceName.CSV),
) -> ImportSummary:
    refuse_in_demo_mode(settings, "job_import")
    """Parse an uploaded export file and ingest it.

    Column names are matched case-insensitively against a synonym table, so exports from
    different boards import without hand-editing. Invalid rows are counted and reported
    with their row number rather than dropped.
    """
    payload = file.file.read()
    if len(payload) > MAX_IMPORT_FILE_BYTES:
        raise ApiError(
            "file_too_large",
            f"the import file is {len(payload) // 1024} KB; the limit is "
            f"{MAX_IMPORT_FILE_BYTES // (1024 * 1024)} MB",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        result = parse_payload(
            payload, filename=file.filename or "import.csv", default_source=source
        )
    except ImportParseError as exc:
        raise ApiError(
            "import_parse_error", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc

    stored_path = store_import_payload(file.filename or "import", payload, settings)
    report = JobIngestService(session).ingest(
        result.records,
        source=source,
        trigger="csv_upload",
        invalid_count=result.invalid_count,
        adapter_errors=result.errors,
        run_metadata={
            "filename": file.filename,
            "stored_payload": str(stored_path),
            **{key: value for key, value in result.metadata.items() if key != "filename"},
        },
    )
    return _summary(report)


@router.post(
    "/discover",
    response_model=list[ImportSummary],
    summary="Run discovery for the sources that permit it",
)
def discover_jobs(
    payload: DiscoverRequest, session: DbSession, profile: Profile, settings: AppSettings
) -> list[ImportSummary]:
    """Run each requested source's authorized discovery.

    A source that has no authorized discovery interface records a
    ``SKIPPED_UNSUPPORTED`` import run carrying the policy reason, so the Diagnostics page
    can explain exactly why nothing was fetched. Nothing is scraped and nothing is faked.
    """
    refuse_in_demo_mode(settings, "discovery")
    requested = payload.sources or list(SourceName)
    configs = {config.source: config for config in SourceConfigRepository(session).list_all()}
    runs = ImportRunRepository(session)
    summaries: list[ImportSummary] = []

    for source in requested:
        try:
            adapter = get_adapter(source, settings)
        except KeyError:
            continue

        config = configs.get(source)
        if config is not None and not config.enabled:
            continue

        run = runs.create(
            ImportRun(source=source, trigger=payload.trigger, status=ImportStatus.RUNNING)
        )
        try:
            result = adapter.discover()
        except CapabilityNotAvailable as exc:
            run.status = ImportStatus.SKIPPED_UNSUPPORTED
            run.finished_at = utcnow()
            run.message = exc.reason
            run.errors = [exc.reason]
            summaries.append(
                ImportSummary(
                    import_run_id=run.id,
                    source=source,
                    status=run.status.value,
                    records_received=0,
                    records_invalid=0,
                    jobs_created=0,
                    jobs_updated=0,
                    duplicates_detected=0,
                    message=exc.reason,
                    errors=[exc.reason],
                )
            )
            continue
        except SourceUnavailable as exc:
            run.status = ImportStatus.FAILED
            run.finished_at = utcnow()
            run.message = exc.reason
            run.errors = [exc.reason]
            if config is not None:
                config.last_error = exc.reason
                config.consecutive_failures += 1
                config.last_run_at = utcnow()
            summaries.append(
                ImportSummary(
                    import_run_id=run.id,
                    source=source,
                    status=run.status.value,
                    records_received=0,
                    records_invalid=0,
                    jobs_created=0,
                    jobs_updated=0,
                    duplicates_detected=0,
                    message=exc.reason,
                    errors=[exc.reason],
                )
            )
            continue

        report = JobIngestService(session).ingest(
            result.records,
            source=source,
            trigger=payload.trigger,
            invalid_count=result.invalid_count,
            adapter_errors=result.errors,
            import_run=run,
            run_metadata=dict(result.metadata),
        )
        if config is not None:
            config.last_run_at = utcnow()
            config.last_error = ""
            config.consecutive_failures = 0
        summaries.append(_summary(report))

    return summaries


@router.post("/score", response_model=ScoreSummary, summary="Score jobs against the profile")
def score_jobs(payload: ScoreRequest, session: DbSession, profile: Profile) -> ScoreSummary:
    report = ScoringService(session).score_many(
        profile, job_ids=payload.job_ids, rescore_all=payload.rescore_all, offset=payload.offset
    )
    return ScoreSummary(
        scored=report.scored,
        filtered_out=report.filtered_out,
        high=report.high,
        review=report.review,
        low=report.low,
        remaining=report.remaining,
        scorer=report.scorer,
        failures=report.failures[:25],
    )


@router.get("", response_model=Page[JobRead], summary="List and filter jobs")
def list_jobs(
    session: DbSession,
    profile: Profile,
    search: Annotated[str | None, Query(max_length=200)] = None,
    job_status: Annotated[list[JobStatus] | None, Query(alias="status")] = None,
    source: Annotated[list[SourceName] | None, Query()] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_age_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
    include_duplicates: bool = False,
    sort_by: Annotated[
        str, Query(pattern="^(score|posted_at|discovered_at|company|title)$")
    ] = "score",
    descending: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[JobRead]:
    query = JobQuery(
        search=search,
        statuses=job_status or [],
        sources=source or [],
        company=company,
        min_score=min_score,
        max_age_days=max_age_days,
        include_duplicates=include_duplicates,
        profile_id=profile.id,
        sort_by=sort_by,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    repository = JobRepository(session)
    return Page(
        items=[to_job_read(job, session, profile.id) for job in repository.list(query)],
        total=repository.count(query),
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetail, summary="Read one job with its full description")
def read_job(job_id: int, session: DbSession, profile: Profile) -> JobDetail:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise ApiError("not_found", f"job {job_id} was not found", status.HTTP_404_NOT_FOUND)
    result = to_job_read(job, session, profile.id, detail=True)
    assert isinstance(result, JobDetail)
    return result


@router.post("/{job_id}/shortlist", response_model=ActionResult, summary="Shortlist a job")
def shortlist_job(job_id: int, session: DbSession, profile: Profile) -> ActionResult:
    repository = JobRepository(session)
    job = repository.get(job_id)
    if job is None:
        raise ApiError("not_found", f"job {job_id} was not found", status.HTTP_404_NOT_FOUND)
    if job.duplicate_of_id is not None:
        raise ApiError(
            "duplicate_job",
            f"job {job_id} is a duplicate of job {job.duplicate_of_id}; shortlist that one",
            status.HTTP_409_CONFLICT,
        )

    repository.set_status(job, JobStatus.SHORTLISTED)
    AuditRepository(session).record(
        "job.shortlisted", entity_type="job", entity_id=job.id, detail={"title": job.title[:120]}
    )
    return ActionResult(message=f"'{job.title}' was shortlisted.", detail={"job_id": job.id})


@router.post("/{job_id}/skip", response_model=ActionResult, summary="Skip a job")
def skip_job(
    job_id: int,
    session: DbSession,
    profile: Profile,
    reason: Annotated[str, Query(max_length=300)] = "",
) -> ActionResult:
    repository = JobRepository(session)
    job = repository.get(job_id)
    if job is None:
        raise ApiError("not_found", f"job {job_id} was not found", status.HTTP_404_NOT_FOUND)

    repository.set_status(job, JobStatus.SKIPPED)
    AuditRepository(session).record(
        "job.skipped", entity_type="job", entity_id=job.id, detail={"reason": reason[:300]}
    )
    return ActionResult(message=f"'{job.title}' was skipped.", detail={"job_id": job.id})
