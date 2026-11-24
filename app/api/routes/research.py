"""Company research, salary normalisation and interview preparation.

Every response here is built from data JobOrbit already holds — listings, the user's
profile, and the user's own interview records — plus, only on explicit request with the
setting enabled, the title and meta description of a company page the user supplied.
Nothing is looked up or generated that a source does not support.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AppSettings, Authorized, DbSession, Profile, refuse_in_demo_mode
from app.api.errors import ApiError
from app.db.models import Application, CandidateProfile, InterviewPrep, Job
from app.db.repositories import ApplicationRepository, JobRepository
from app.schemas.research import (
    CompanyRefreshRequest,
    CompanyResearchRead,
    CompensationRead,
    ConversionRead,
    InterviewPrepGenerate,
    InterviewPrepRead,
    InterviewRoundCreate,
    InterviewRoundRead,
    InterviewRoundUpdate,
    JobSalaryRead,
    NextQuestionRead,
    PracticeRequest,
    PracticeResult,
    SalaryComparison,
    SalaryParseRead,
)
from app.services import interview_prep
from app.services.company_research import ExternalResearchRefused, build_company_profile
from app.services.salary import (
    QUESTION_UNITS,
    Compensation,
    compensation_from_amounts,
    format_for_unit,
    parse_compensation,
)

router = APIRouter(prefix="/api/research", tags=["research"], dependencies=[Authorized])


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _job_or_404(session: DbSession, job_id: int) -> Job:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise ApiError("not_found", f"Job {job_id} does not exist.", status.HTTP_404_NOT_FOUND)
    return job


def _application_or_404(
    session: DbSession, profile: CandidateProfile, application_id: int
) -> Application:
    application = ApplicationRepository(session).get(application_id)
    if application is None or application.profile_id != profile.id:
        raise ApiError(
            "not_found",
            f"Application {application_id} does not exist.",
            status.HTTP_404_NOT_FOUND,
        )
    return application


def _refused(exc: ExternalResearchRefused) -> ApiError:
    http_status = (
        status.HTTP_403_FORBIDDEN
        if exc.code == "external_research_disabled"
        else status.HTTP_400_BAD_REQUEST
    )
    return ApiError(exc.code, exc.message, http_status)


def _comp_read(comp: Compensation) -> CompensationRead:
    return CompensationRead(**comp.to_dict())


def _prep_read(prep: InterviewPrep, application: Application) -> InterviewPrepRead:
    model = InterviewPrepRead.model_validate(prep)
    return model.model_copy(
        update={
            "interview_stage": interview_prep.is_interview_stage(application),
            "next_question": interview_prep.next_practice_question(prep),
        }
    )


def _listing_compensation(job: Job, rate: float | None) -> tuple[Compensation, str]:
    if job.salary_raw.strip():
        parsed = parse_compensation(job.salary_raw, usd_inr_rate=rate)
        if parsed.disclosed or (job.salary_min is None and job.salary_max is None):
            return parsed, "the listing's salary text"
    if job.salary_min is not None or job.salary_max is not None:
        return (
            compensation_from_amounts(
                job.salary_min,
                job.salary_max,
                job.salary_currency,
                note="From the listing's structured salary fields, which carry no period; "
                "read as annual.",
                usd_inr_rate=rate,
            ),
            "the listing's structured salary fields",
        )
    return parse_compensation(job.salary_raw, usd_inr_rate=rate), "the listing"


def _compare(listing: Compensation, expectation: Compensation) -> SalaryComparison:
    if not listing.disclosed:
        return SalaryComparison(comparable=False, statement="The listing does not state a salary.")
    if not expectation.disclosed:
        return SalaryComparison(
            comparable=False,
            statement="Your profile has no salary expectation, so there is nothing to compare.",
        )
    list_low, list_high = listing.inr_annual_minimum, listing.inr_annual_maximum
    exp_low, exp_high = expectation.inr_annual_minimum, expectation.inr_annual_maximum
    if (list_low is None and list_high is None) or (exp_low is None and exp_high is None):
        return SalaryComparison(
            comparable=False,
            statement="The two figures cannot be put in annual INR without an assumption "
            "this app will not make (see the assumptions on each side).",
        )
    top = list_high if list_high is not None else list_low
    bottom = list_low if list_low is not None else list_high
    want = exp_low if exp_low is not None else exp_high
    assert top is not None and bottom is not None and want is not None
    if top < want:
        statement = (
            f"The listing's upper figure (INR {top:,.0f} a year) is below your minimum "
            f"expectation (INR {want:,.0f})."
        )
    elif bottom >= want:
        statement = (
            f"The listing's lower figure (INR {bottom:,.0f} a year) meets your minimum "
            f"expectation (INR {want:,.0f})."
        )
    else:
        statement = (
            f"Your minimum expectation (INR {want:,.0f} a year) falls inside the listing's "
            f"range (INR {bottom:,.0f} - {top:,.0f})."
        )
    return SalaryComparison(comparable=True, statement=statement)


def _research(session: DbSession, profile: CandidateProfile, name: str, **kwargs: Any) -> Any:
    try:
        return build_company_profile(session, name, profile=profile, **kwargs)
    except ExternalResearchRefused as exc:
        raise _refused(exc) from exc
    except ValueError as exc:
        raise ApiError("invalid_company", str(exc)) from exc


# --------------------------------------------------------------------------------------
# Salary
# --------------------------------------------------------------------------------------


@router.get("/salary/parse", response_model=SalaryParseRead, summary="Parse salary text")
def parse_salary_text(
    settings: AppSettings,
    text: Annotated[str, Query(max_length=500)] = "",
    default_currency: Annotated[str, Query(pattern="^[A-Za-z]{3}$")] = "INR",
) -> SalaryParseRead:
    """Pure: parses the text and proposes it in each form unit. Writes nothing."""
    comp = parse_compensation(
        text, default_currency=default_currency, usd_inr_rate=settings.usd_inr_rate
    )
    proposals = {
        unit: ConversionRead(
            **format_for_unit(comp, unit, usd_inr_rate=settings.usd_inr_rate).to_dict()
        )
        for unit in QUESTION_UNITS
    }
    return SalaryParseRead(compensation=_comp_read(comp), proposals=proposals)


@router.get(
    "/jobs/{job_id}/salary",
    response_model=JobSalaryRead,
    summary="A listing's salary next to your expectation",
)
def read_job_salary(
    job_id: int, session: DbSession, profile: Profile, settings: AppSettings
) -> JobSalaryRead:
    job = _job_or_404(session, job_id)
    rate = settings.usd_inr_rate
    listing, listing_source = _listing_compensation(job, rate)
    expectation = compensation_from_amounts(
        profile.salary_expectation_min,
        profile.salary_expectation_max,
        profile.salary_currency,
        note="Your profile stores the expectation as an annual figure.",
        usd_inr_rate=rate,
    )
    return JobSalaryRead(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        listing=_comp_read(listing),
        listing_source=listing_source,
        expectation=_comp_read(expectation),
        comparison=_compare(listing, expectation),
    )


# --------------------------------------------------------------------------------------
# Company research
# --------------------------------------------------------------------------------------


@router.get(
    "/companies/{name}",
    response_model=CompanyResearchRead,
    summary="Cited company profile (built from held listings; cached)",
)
def read_company_research(name: str, session: DbSession, profile: Profile) -> CompanyResearchRead:
    """Returns the cached profile, rebuilding it when a newer listing has arrived."""
    return CompanyResearchRead(**_research(session, profile, name).to_dict())


@router.post(
    "/companies/{name}/refresh",
    response_model=CompanyResearchRead,
    summary="Rebuild a company profile, optionally fetching its website",
)
def refresh_company_research(
    name: str,
    session: DbSession,
    profile: Profile,
    settings: AppSettings,
    payload: CompanyRefreshRequest | None = None,
) -> CompanyResearchRead:
    payload = payload or CompanyRefreshRequest()
    if payload.fetch_website:
        refuse_in_demo_mode(settings, "external_research")
    research = _research(
        session,
        profile,
        name,
        refresh=True,
        fetch_website=payload.fetch_website,
        website=payload.website,
        settings=settings,
    )
    return CompanyResearchRead(**research.to_dict())


@router.get(
    "/jobs/{job_id}/company",
    response_model=CompanyResearchRead,
    summary="Company profile plus this job's requirements and your relevant projects",
)
def read_job_company_research(
    job_id: int, session: DbSession, profile: Profile
) -> CompanyResearchRead:
    job = _job_or_404(session, job_id)
    return CompanyResearchRead(**_research(session, profile, job.company, job=job).to_dict())


# --------------------------------------------------------------------------------------
# Interview preparation
# --------------------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/interview-prep",
    response_model=InterviewPrepRead,
    summary="Read the stored interview preparation",
)
def read_interview_prep(
    application_id: int, session: DbSession, profile: Profile
) -> InterviewPrepRead:
    application = _application_or_404(session, profile, application_id)
    prep = interview_prep.get_prep(session, application.id)
    if prep is None:
        raise ApiError(
            "interview_prep_not_generated",
            "No preparation has been generated for this application yet.",
            status.HTTP_404_NOT_FOUND,
        )
    return _prep_read(prep, application)


@router.post(
    "/applications/{application_id}/interview-prep",
    response_model=InterviewPrepRead,
    summary="Generate (or regenerate) interview preparation",
)
def generate_interview_prep(
    application_id: int,
    session: DbSession,
    profile: Profile,
    payload: InterviewPrepGenerate | None = None,
) -> InterviewPrepRead:
    application = _application_or_404(session, profile, application_id)
    regenerate = bool(payload and payload.regenerate)
    prep = interview_prep.build_prep(session, application, regenerate=regenerate)
    return _prep_read(prep, application)


@router.get(
    "/applications/{application_id}/interview-prep/next-question",
    response_model=NextQuestionRead,
    summary="The next mock-interview question",
)
def read_next_practice_question(
    application_id: int,
    session: DbSession,
    profile: Profile,
    kind: Annotated[str | None, Query(max_length=30)] = None,
    after: Annotated[str | None, Query(max_length=64)] = None,
) -> NextQuestionRead:
    application = _application_or_404(session, profile, application_id)
    prep = interview_prep.get_prep(session, application.id)
    if prep is None:
        return NextQuestionRead(question=None)
    return NextQuestionRead(
        question=interview_prep.next_practice_question(prep, kind=kind, after=after)
    )


@router.post(
    "/applications/{application_id}/interview-prep/practice",
    response_model=PracticeResult,
    summary="Answer one practice question and get rule-based feedback",
)
def record_practice_answer(
    application_id: int, payload: PracticeRequest, session: DbSession, profile: Profile
) -> PracticeResult:
    application = _application_or_404(session, profile, application_id)
    prep = interview_prep.get_prep(session, application.id)
    if prep is None:
        raise ApiError(
            "interview_prep_not_generated",
            "Generate the preparation before practising.",
            status.HTTP_409_CONFLICT,
        )
    item = interview_prep.find_item(prep, payload.question_id)
    if item is None:
        raise ApiError(
            "not_found",
            "That question is not part of this preparation.",
            status.HTTP_404_NOT_FOUND,
        )
    feedback = interview_prep.record_practice(session, prep, item, payload.answer)
    return PracticeResult(
        question=item,
        feedback=feedback,
        practice_count=len(prep.practice or []),
        next_question=interview_prep.next_practice_question(prep, after=item["id"]),
    )


# --------------------------------------------------------------------------------------
# Interview rounds (the user's own records)
# --------------------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/rounds",
    response_model=list[InterviewRoundRead],
    summary="Interview rounds you recorded",
)
def list_interview_rounds(
    application_id: int, session: DbSession, profile: Profile
) -> list[InterviewRoundRead]:
    application = _application_or_404(session, profile, application_id)
    return [
        InterviewRoundRead.model_validate(record)
        for record in interview_prep.list_rounds(session, application.id)
    ]


@router.post(
    "/applications/{application_id}/rounds",
    response_model=InterviewRoundRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record an interview round",
)
def create_interview_round(
    application_id: int, payload: InterviewRoundCreate, session: DbSession, profile: Profile
) -> InterviewRoundRead:
    application = _application_or_404(session, profile, application_id)
    record = interview_prep.create_round(session, application, payload.model_dump())
    return InterviewRoundRead.model_validate(record)


def _round_or_404(session: DbSession, profile: CandidateProfile, round_id: int) -> Any:
    record = interview_prep.get_round(session, round_id)
    if record is not None:
        application = ApplicationRepository(session).get(record.application_id)
        if application is not None and application.profile_id == profile.id:
            return record
    raise ApiError("not_found", f"Round {round_id} does not exist.", status.HTTP_404_NOT_FOUND)


@router.patch(
    "/rounds/{round_id}",
    response_model=InterviewRoundRead,
    summary="Edit a recorded interview round",
)
def update_interview_round(
    round_id: int, payload: InterviewRoundUpdate, session: DbSession, profile: Profile
) -> InterviewRoundRead:
    record = _round_or_404(session, profile, round_id)
    changes = payload.model_dump(exclude_unset=True)
    record = interview_prep.update_round(session, record, changes)
    return InterviewRoundRead.model_validate(record)


@router.delete(
    "/rounds/{round_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a recorded interview round",
)
def delete_interview_round(round_id: int, session: DbSession, profile: Profile) -> Response:
    record = _round_or_404(session, profile, round_id)
    interview_prep.delete_round(session, record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
