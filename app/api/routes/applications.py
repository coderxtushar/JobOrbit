"""Application endpoints.

Note what is absent: there is no submit endpoint. ``PATCH`` can *record* that the user
submitted an application elsewhere, which requires naming who did it, and recording a
confirmation requires evidence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import Authorized, DbSession, Llm, Profile
from app.api.errors import ApiError
from app.db.models import Application, ApplicationEvent, ApplicationStatus, Outcome
from app.db.repositories import (
    ApplicationQuery,
    ApplicationRepository,
    AuditRepository,
    JobRepository,
)
from app.schemas.application import (
    AnswerRead,
    ApplicationDetail,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationUpdate,
    PrepareRequest,
)
from app.schemas.common import Page
from app.services.application_prep import ApplicationPreparationService
from app.services.tracking import (
    OPENED_EVENT_DETAIL,
    ApplicationTracker,
    TransitionRequest,
    blocking_questions,
    next_action,
    was_opened,
)
from app.services.url_safety import inspect_url

router = APIRouter(prefix="/api/applications", tags=["applications"], dependencies=[Authorized])


def _to_read(application: Application, session, *, detail: bool = False):
    job = JobRepository(session).get(application.job_id)
    model_class = ApplicationDetail if detail else ApplicationRead
    model = model_class.model_validate(application)
    safe_url = ""
    if job is not None and job.url:
        verdict = inspect_url(job.url)
        safe_url = job.url if verdict.safe else ""
    updates: dict[str, object] = {
        "answers": [AnswerRead.model_validate(answer) for answer in application.answers],
        "job_title": job.title if job else "",
        "job_company": job.company if job else "",
        "job_url": safe_url,
        "blocking_questions": blocking_questions(application),
        "next_action": next_action(application),
        "employer_page_opened": was_opened(application),
    }
    if detail:
        updates["events"] = [
            ApplicationEventRead.model_validate(event)
            for event in sorted(application.events, key=lambda item: item.created_at)
        ]
    return model.model_copy(update=updates)


@router.post(
    "/prepare",
    response_model=ApplicationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare a review-ready application for a job",
)
def prepare_application(
    payload: PrepareRequest, session: DbSession, profile: Profile, llm: Llm
) -> ApplicationDetail:
    """Build the resume variant, cover letter and answer set, then stop.

    The application reaches ``READY_FOR_REVIEW``. It is never submitted here; the user
    reviews it, approves it, and submits it on the employer's own site.
    """
    job = JobRepository(session).get(payload.job_id)
    if job is None:
        raise ApiError(
            "not_found", f"job {payload.job_id} was not found", status.HTTP_404_NOT_FOUND
        )

    prepared = ApplicationPreparationService(session, llm).prepare(
        job,
        profile,
        include_cover_letter=payload.include_cover_letter,
        extra_questions=payload.extra_questions,
    )
    result = _to_read(prepared.application, session, detail=True)
    return result


@router.get("", response_model=Page[ApplicationRead], summary="List applications")
def list_applications(
    session: DbSession,
    profile: Profile,
    application_status: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    outcome: Annotated[list[Outcome] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ApplicationRead]:
    query = ApplicationQuery(
        statuses=application_status or [],
        outcomes=outcome or [],
        profile_id=profile.id,
        limit=limit,
        offset=offset,
    )
    repository = ApplicationRepository(session)
    return Page(
        items=[_to_read(application, session) for application in repository.list(query)],
        total=repository.count(query),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{application_id}",
    response_model=ApplicationDetail,
    summary="Read one application with its answers and event history",
)
def read_application(
    application_id: int, session: DbSession, profile: Profile
) -> ApplicationDetail:
    application = ApplicationRepository(session).get(application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found", f"application {application_id} was not found", status.HTTP_404_NOT_FOUND
        )
    return _to_read(application, session, detail=True)


@router.post(
    "/{application_id}/record-opened",
    response_model=ApplicationDetail,
    summary="Record that you opened the employer's application page",
)
def record_opened(application_id: int, session: DbSession, profile: Profile) -> ApplicationDetail:
    """Append an event noting the page was opened. The status is deliberately unchanged.

    Opening a page is not submitting a form. Recording it separately lets the next-action
    line distinguish "not started" from "opened but not yet recorded as submitted" without
    ever implying an application was sent.
    """
    application = ApplicationRepository(session).get(application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found", f"application {application_id} was not found", status.HTTP_404_NOT_FOUND
        )
    if not was_opened(application):
        application.events.append(
            ApplicationEvent(
                from_status=application.status,
                to_status=application.status,
                actor="user",
                detail=OPENED_EVENT_DETAIL,
            )
        )
        AuditRepository(session).record(
            "application.page_opened",
            entity_type="application",
            entity_id=application.id,
            detail={"status": application.status.value},
        )
        session.flush()
    return _to_read(application, session, detail=True)


@router.patch(
    "/{application_id}",
    response_model=ApplicationDetail,
    summary="Edit answers, record a user-performed submission, or update the outcome",
)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    session: DbSession,
    profile: Profile,
    llm: Llm,
) -> ApplicationDetail:
    repository = ApplicationRepository(session)
    application = repository.get(application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found", f"application {application_id} was not found", status.HTTP_404_NOT_FOUND
        )

    service = ApplicationPreparationService(session, llm)
    tracker = ApplicationTracker(session)
    changed: list[str] = []

    if payload.answers:
        known = {answer.id for answer in application.answers}
        unknown = sorted({edit.id for edit in payload.answers} - known)
        if unknown:
            raise ApiError(
                "unknown_answer",
                f"these answer ids do not belong to application {application_id}: {unknown}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        service.apply_answer_edits(application, {edit.id: edit.answer for edit in payload.answers})
        changed.append("answers")

    for field in ("cover_letter", "notes", "follow_up_date", "interview_status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(application, field, value)
            changed.append(field)

    if payload.cover_letter is not None:
        application.cover_letter_version += 1
        application.cover_letter_generated_by = "user_entered"

    if payload.outcome is not None:
        application.outcome = payload.outcome
        changed.append("outcome")

    if payload.user_approved is not None:
        application.user_approved = payload.user_approved
        changed.append("user_approved")

    if payload.confirmation_evidence is not None:
        application.confirmation_evidence = payload.confirmation_evidence
        changed.append("confirmation_evidence")

    if payload.status is not None:
        tracker.transition(
            application,
            TransitionRequest(
                target=payload.status,
                actor="user",
                detail="updated through the API",
                submitted_by=payload.submitted_by or "",
                confirmation_evidence=payload.confirmation_evidence or "",
            ),
        )
        changed.append("status")

    AuditRepository(session).record(
        "application.updated",
        entity_type="application",
        entity_id=application.id,
        detail={"fields": sorted(set(changed))},
    )
    session.flush()
    session.refresh(application)
    return _to_read(application, session, detail=True)


@router.get(
    "/{application_id}/artifacts",
    summary="Every version of the material prepared for an application",
)
def list_artifacts(application_id: int, session: DbSession, profile: Profile) -> list[dict]:
    """Newest first. ``locked`` versions were part of a dispatched submission and are the
    record of what the employer received; they can no longer change."""
    from sqlalchemy import select

    from app.db.models import ApplicationArtifact

    application = session.get(Application, application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found", f"application {application_id} was not found", status.HTTP_404_NOT_FOUND
        )
    rows = session.scalars(
        select(ApplicationArtifact)
        .where(ApplicationArtifact.application_id == application_id)
        .order_by(ApplicationArtifact.id.desc())
    ).all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "label": row.label,
            "content_sha256": row.content_sha256,
            "byte_size": row.byte_size,
            "created_at": row.created_at.isoformat(),
            "locked": row.locked_at is not None,
            "locked_at": row.locked_at.isoformat() if row.locked_at else None,
            "preview": row.content[:600],
        }
        for row in rows
    ]


@router.post(
    "/{application_id}/regenerate",
    response_model=ApplicationDetail,
    summary="Regenerate the drafts (resume variant, letter, answers) before submission",
)
def regenerate_application(
    application_id: int, session: DbSession, profile: Profile, llm: Llm
) -> ApplicationDetail:
    """Re-run preparation. Earlier versions are kept, so a regenerated draft never
    overwrites one that was sent; once an application may have reached the employer
    this refuses, because its drafts are then the record of what was submitted."""
    from app.db.repositories import DuplicateApplicationError

    application = session.get(Application, application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found", f"application {application_id} was not found", status.HTTP_404_NOT_FOUND
        )
    job = JobRepository(session).get(application.job_id)
    if job is None:
        raise ApiError("not_found", "the job was deleted", status.HTTP_404_NOT_FOUND)
    try:
        prepared = ApplicationPreparationService(session, llm).prepare(
            job, profile, include_cover_letter=True
        )
    except DuplicateApplicationError as error:
        raise ApiError(
            "already_submitted",
            "This application may already be with the employer, so its drafts are kept as "
            "the record of what was sent and cannot be regenerated.",
            status.HTTP_409_CONFLICT,
        ) from error
    return _to_read(prepared.application, session, detail=True)
