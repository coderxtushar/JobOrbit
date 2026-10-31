"""Resume endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import AppSettings, Authorized, DbSession, Profile
from app.api.errors import ApiError
from app.db.models import Resume, ResumeVariant
from app.db.repositories import AuditRepository, ResumeRepository, ResumeVariantRepository
from app.schemas.common import Page
from app.schemas.resume import (
    ParsedResumeFields,
    ResumeRead,
    ResumeUploadResponse,
    VariantRead,
    VariantRequest,
)
from app.services import resume_variants
from app.services.resume_parser import parse_resume_bytes
from app.services.storage import store_resume

router = APIRouter(prefix="/api/resumes", tags=["resumes"], dependencies=[Authorized])


def _to_read(resume: Resume) -> ResumeRead:
    model = ResumeRead.model_validate(resume)
    return model.model_copy(
        update={
            "text_character_count": len(resume.extracted_text or ""),
            "variant_count": len(resume.variants),
        }
    )


@router.post(
    "",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF or DOCX resume and extract its fields",
)
def upload_resume(
    session: DbSession,
    profile: Profile,
    settings: AppSettings,
    file: UploadFile = File(..., description="A .pdf or .docx resume"),
    label: str = Form("base"),
    is_primary: bool = Form(True),
) -> ResumeUploadResponse:
    """Store the file and return the extracted fields for the user to confirm.

    Extraction is a *proposal*: nothing is written to the candidate profile here. The
    client shows the result on an editable screen and then calls ``PUT /api/profile``.
    """
    if settings.demo_mode:
        raise ApiError(
            "demo_mode_upload_blocked",
            "This is a shared public demo, so resume upload is disabled. A deployment "
            "like this has no per-user login, which means one visitor's resume would be "
            "readable by the next. Run the app locally to use your own resume: the "
            "README has the two commands.",
            status.HTTP_403_FORBIDDEN,
        )

    payload = file.file.read()
    stored = store_resume(file.filename or "resume", payload, settings)

    existing = ResumeRepository(session).find_by_hash(profile.id, stored.sha256)
    if existing is not None:
        raise ApiError(
            "duplicate_resume",
            f"This exact file is already stored as resume {existing.id} "
            f"('{existing.original_filename}').",
            status.HTTP_409_CONFLICT,
        )

    text, parsed = parse_resume_bytes(payload, stored.extension)

    resume = ResumeRepository(session).add(
        Resume(
            profile_id=profile.id,
            label=label.strip()[:200] or "base",
            original_filename=stored.original_filename,
            stored_path=str(stored.path),
            content_type=stored.content_type,
            file_size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            extracted_text=text,
            extracted_fields=parsed.fields.model_dump(),
            parse_warnings=parsed.warnings,
            is_primary=is_primary,
        )
    )
    AuditRepository(session).record(
        "resume.uploaded",
        entity_type="resume",
        entity_id=resume.id,
        detail={
            "filename": stored.original_filename,
            "size_bytes": stored.size_bytes,
            "text_chars": len(text),
            "warnings": len(parsed.warnings),
            "skills_found": len(parsed.fields.skills),
        },
    )
    return ResumeUploadResponse(
        resume=_to_read(resume),
        parsed=parsed.fields,
        applied_to_profile=False,
        review_required=True,
    )


@router.get("", response_model=Page[ResumeRead], summary="List stored resumes")
def list_resumes(
    session: DbSession, profile: Profile, limit: int = 25, offset: int = 0
) -> Page[ResumeRead]:
    resumes = ResumeRepository(session).list_for_profile(profile.id)
    window = resumes[offset : offset + limit]
    return Page(
        items=[_to_read(resume) for resume in window],
        total=len(resumes),
        limit=limit,
        offset=offset,
    )


@router.get("/{resume_id}", response_model=ResumeRead, summary="Read one resume")
def read_resume(resume_id: int, session: DbSession, profile: Profile) -> ResumeRead:
    resume = ResumeRepository(session).get(resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise ApiError("not_found", f"resume {resume_id} was not found", status.HTTP_404_NOT_FOUND)
    return _to_read(resume)


@router.get(
    "/{resume_id}/parsed",
    response_model=ParsedResumeFields,
    summary="Read the fields extracted from a resume",
)
def read_parsed(resume_id: int, session: DbSession, profile: Profile) -> ParsedResumeFields:
    resume = ResumeRepository(session).get(resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise ApiError("not_found", f"resume {resume_id} was not found", status.HTTP_404_NOT_FOUND)
    return ParsedResumeFields.model_validate(resume.extracted_fields or {})


@router.post(
    "/{resume_id}/primary",
    response_model=ResumeRead,
    summary="Mark a resume as the primary one",
)
def set_primary(resume_id: int, session: DbSession, profile: Profile) -> ResumeRead:
    repository = ResumeRepository(session)
    resume = repository.get(resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise ApiError("not_found", f"resume {resume_id} was not found", status.HTTP_404_NOT_FOUND)
    return _to_read(repository.set_primary(resume))


@router.get(
    "/{resume_id}/variants",
    response_model=Page[VariantRead],
    summary="List a resume's variants",
)
def list_variants(resume_id: int, session: DbSession, profile: Profile) -> Page[VariantRead]:
    resume = ResumeRepository(session).get(resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise ApiError("not_found", f"resume {resume_id} was not found", status.HTTP_404_NOT_FOUND)
    variants = ResumeVariantRepository(session).list_for_resume(resume_id)
    return Page(
        items=[VariantRead.model_validate(variant) for variant in variants],
        total=len(variants),
        limit=max(len(variants), 1),
        offset=0,
    )


@router.post(
    "/variants",
    response_model=VariantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Build a truthful resume variant for a job family",
)
def create_variant(payload: VariantRequest, session: DbSession, profile: Profile) -> VariantRead:
    """Generate a variant.

    The generator may only reorder facts already present in the resume and profile. If the
    rendered variant would claim a skill absent from both, the request is rejected rather
    than stored.
    """
    repository = ResumeRepository(session)
    resume = (
        repository.get(payload.resume_id)
        if payload.resume_id is not None
        else repository.get_primary(profile.id)
    )
    if resume is None or resume.profile_id != profile.id:
        raise ApiError(
            "not_found",
            "No resume was found. Upload a resume before building a variant.",
            status.HTTP_404_NOT_FOUND,
        )

    draft = resume_variants.build_variant(
        resume,
        profile,
        payload.job_family,
        emphasise=payload.emphasised_skills,
        name=payload.name,
    )
    problems = resume_variants.audit_variant(draft, resume, profile)
    if problems:
        raise ApiError(
            "variant_unsourced_claim", "; ".join(problems), status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    variants = ResumeVariantRepository(session)
    variant = variants.add(
        ResumeVariant(
            resume_id=resume.id,
            name=draft.name,
            job_family=draft.job_family,
            version=variants.next_version(resume.id, draft.job_family),
            emphasised_skills=draft.emphasised_skills,
            included_items=draft.included_items,
            content=draft.content,
            generated_by=draft.generated_by,
        )
    )
    AuditRepository(session).record(
        "resume_variant.created",
        entity_type="resume_variant",
        entity_id=variant.id,
        detail={
            "resume_id": resume.id,
            "job_family": draft.job_family,
            "version": variant.version,
            "omitted_requested_skills": draft.included_items.get("omitted_requested_skills", []),
        },
    )
    return VariantRead.model_validate(variant)
