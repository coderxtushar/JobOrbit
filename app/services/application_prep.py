"""Application preparation.

Assembles everything the user needs to complete an application by hand: the most relevant
truthful resume variant, a cover letter, and the question set with provenance on each
answer. It deliberately stops at "ready for review" — opening and submitting the form is
the user's action.

Cover-letter generation has two implementations with the same guarantee. The rule-based
one assembles sentences from profile and resume facts. The LLM one, when configured,
receives *only* a fact list plus the job description fenced as untrusted data, and its
output is scanned for forbidden sensitive claims before it is accepted; if the scan trips,
the rule-based letter is used instead.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationAnswer,
    ApplicationArtifact,
    ApplicationStatus,
    CandidateProfile,
    Job,
    Resume,
    ResumeVariant,
    SourceName,
    WorkArrangement,
    utcnow,
)
from app.db.repositories import (
    ApplicationRepository,
    AuditRepository,
    DuplicateApplicationError,
    JobRepository,
    ResumeRepository,
    ResumeVariantRepository,
    SavedAnswerRepository,
)
from app.llm.base import LLMProvider, LLMUnavailable, wrap_untrusted
from app.llm.null_provider import NullProvider
from app.logging_conf import get_logger
from app.services import questions as question_service
from app.services import resume_variants
from app.services.answer_bank import apply_saved_answer
from app.services.text import canonical_skills
from app.services.tracking import ApplicationTracker, TransitionRequest

logger = get_logger(__name__)

_COVER_LETTER_SYSTEM = (
    "You write short, plain, factual cover letters for a job applicant. "
    "You may ONLY use facts from the FACTS list the user supplies. "
    "You must NOT state or imply years of experience, salary, notice period, work "
    "authorization, visa status, education or certifications unless that exact fact "
    "appears in the FACTS list. "
    "You must NOT invent projects, employers, metrics, numbers or achievements. "
    "Write 150-200 words, no greeting placeholders like [Name], no bullet points."
)

_FORBIDDEN_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b\d+\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b", "an experience duration"),
    (r"\b(?:salary|ctc|compensation)\b", "a salary statement"),
    (r"\b(?:visa|sponsorship|work permit|authori[sz]ed to work)\b", "a work-authorization claim"),
    (r"\bnotice period\b", "a notice-period claim"),
    (r"\b(?:certified|certification)\b", "a certification claim"),
)


@dataclass(slots=True)
class PreparedApplication:
    application: Application
    variant: ResumeVariant | None
    blocking_questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cover_letter_generated_by: str = ""
    reused_answers: int = 0


def _facts_for_letter(job: Job, profile: CandidateProfile, matched_skills: list[str]) -> list[str]:
    """The complete, closed set of facts a cover letter may use."""
    facts = [f"Applying for: {job.title} at {job.company}"]
    if profile.full_name:
        facts.append(f"Applicant name: {profile.full_name}")
    if matched_skills:
        facts.append(
            "Skills the applicant has that this role lists: " + ", ".join(matched_skills[:12])
        )
    for project in list(profile.projects)[:2]:
        if isinstance(project, dict) and project.get("name"):
            description = str(project.get("description", ""))[:180]
            facts.append(f"Project the applicant built: {project['name']} - {description}")
    for entry in list(profile.education)[:1]:
        if isinstance(entry, dict) and entry.get("degree"):
            facts.append(
                f"Education: {entry.get('degree')} "
                f"{entry.get('institution', '')} {entry.get('end_year', '')}".strip()
            )
    if profile.headline:
        facts.append(f"Applicant's own headline: {profile.headline}")
    return facts


def _rule_based_cover_letter(job: Job, profile: CandidateProfile, matched_skills: list[str]) -> str:
    name = profile.full_name or "the applicant"
    opening = (
        f"I am writing to apply for the {job.title} role at {job.company}."
        if job.company
        else f"I am writing to apply for the {job.title} role."
    )

    if matched_skills:
        skills_sentence = (
            "The role lists "
            + ", ".join(matched_skills[:6])
            + ", which are the areas I have worked in directly."
        )
    else:
        skills_sentence = (
            "My profile does not yet list skills overlapping this posting, so please read "
            "the attached resume for the full picture."
        )

    project_sentence = ""
    for project in list(profile.projects)[:1]:
        if isinstance(project, dict) and project.get("name"):
            description = str(project.get("description", "")).strip().rstrip(".")
            project_sentence = f"Most recently I built {project['name']}" + (
                f", {description[:160]}." if description else "."
            )
            break

    education_sentence = ""
    for entry in list(profile.education)[:1]:
        if isinstance(entry, dict) and entry.get("degree"):
            institution = str(entry.get("institution", "")).strip()
            education_sentence = (
                f"I hold a {entry['degree']}"
                + (f" from {institution}" if institution else "")
                + "."
            )
            break

    location_sentence = ""
    if job.work_arrangement is WorkArrangement.REMOTE:
        if "remote" in {place.strip().lower() for place in profile.preferred_locations}:
            location_sentence = "I am looking for remote roles, which matches this posting."
    elif job.location and profile.preferred_locations:
        if any(
            place.strip().lower() in job.location.lower() for place in profile.preferred_locations
        ):
            location_sentence = f"I am looking for roles in {job.location}."

    closing = (
        "I would welcome the chance to talk about how I can contribute. "
        f"Thank you for your time.\n\n{name}"
    )
    body = " ".join(
        part
        for part in (
            opening,
            skills_sentence,
            project_sentence,
            education_sentence,
            location_sentence,
        )
        if part
    )
    return f"{body}\n\n{closing}"


def _scan_for_forbidden_claims(text: str, facts: list[str]) -> list[str]:
    """Reject generated text that asserts a sensitive fact not present in ``facts``."""
    fact_blob = " ".join(facts).lower()
    problems: list[str] = []
    for pattern, label in _FORBIDDEN_CLAIM_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.group(0).lower() not in fact_blob:
            problems.append(f"the draft contained {label} that is not in your verified facts")
    return problems


def generate_cover_letter(
    job: Job,
    profile: CandidateProfile,
    matched_skills: list[str],
    provider: LLMProvider | None = None,
) -> tuple[str, str, list[str]]:
    """Return (letter, generated_by, warnings).

    Falls back to the rule-based letter whenever the LLM is absent, fails, or produces a
    draft that asserts something outside the supplied facts.
    """
    facts = _facts_for_letter(job, profile, matched_skills)
    rule_based = _rule_based_cover_letter(job, profile, matched_skills)
    provider = provider or NullProvider()

    if not provider.available:
        return rule_based, "rule_based", []

    prompt = (
        "FACTS (the only facts you may use):\n"
        + "\n".join(f"- {fact}" for fact in facts)
        + "\n\n"
        + wrap_untrusted("job_description", job.description, limit=3000)
        + "\n\nWrite the cover letter now."
    )
    try:
        response = provider.complete(_COVER_LETTER_SYSTEM, prompt, max_tokens=500)
    except LLMUnavailable as exc:
        logger.warning(
            "cover letter llm call failed; using rule-based letter", extra={"reason": str(exc)}
        )
        return rule_based, "rule_based", ["The AI draft failed, so a rule-based letter was used."]

    problems = _scan_for_forbidden_claims(response.text, facts)
    if problems:
        logger.warning("llm cover letter rejected", extra={"problems": problems})
        return (
            rule_based,
            "rule_based",
            problems + ["The AI draft was discarded and a rule-based letter was used instead."],
        )
    return (
        response.text,
        f"ai_draft:{response.provider}",
        ["This letter was drafted by an AI model from your verified facts. Read it before use."],
    )


class ApplicationPreparationService:
    """Builds a review-ready application for a shortlisted job."""

    def __init__(self, session: Session, provider: LLMProvider | None = None) -> None:
        self._session = session
        self._jobs = JobRepository(session)
        self._applications = ApplicationRepository(session)
        self._resumes = ResumeRepository(session)
        self._variants = ResumeVariantRepository(session)
        self._saved_answers = SavedAnswerRepository(session)
        self._audit = AuditRepository(session)
        self._tracker = ApplicationTracker(session)
        self._provider = provider or NullProvider()

    def _select_variant(
        self, resume: Resume | None, profile: CandidateProfile, job: Job
    ) -> tuple[ResumeVariant | None, list[str]]:
        if resume is None:
            return None, [
                "No resume has been uploaded, so no resume variant could be selected. "
                "Upload a resume on the Resume page."
            ]

        family = resume_variants.infer_job_family(job.title, list(job.required_skills))
        existing = self._variants.latest_for_family(resume.id, family)
        if existing is not None:
            return existing, []

        draft = resume_variants.build_variant(resume, profile, family)
        audit_problems = resume_variants.audit_variant(draft, resume, profile)
        if audit_problems:
            return None, audit_problems

        variant = self._variants.add(
            ResumeVariant(
                resume_id=resume.id,
                name=draft.name,
                job_family=draft.job_family,
                version=self._variants.next_version(resume.id, family),
                emphasised_skills=draft.emphasised_skills,
                included_items=draft.included_items,
                content=draft.content,
                generated_by=draft.generated_by,
            )
        )
        return variant, draft.warnings

    def prepare(
        self,
        job: Job,
        profile: CandidateProfile,
        *,
        include_cover_letter: bool = True,
        extra_questions: list[str] | None = None,
    ) -> PreparedApplication:
        """Create or refresh an application and move it to ``READY_FOR_REVIEW``."""
        warnings: list[str] = []

        existing = self._applications.find_for_job(job.id, profile.id)
        if existing is not None and existing.status in (
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.CONFIRMED,
        ):
            raise DuplicateApplicationError(existing.id, job.id)

        resume = self._resumes.get_primary(profile.id)
        variant, variant_warnings = self._select_variant(resume, profile, job)
        warnings.extend(variant_warnings)

        user_skills = set(canonical_skills(list(profile.technical_skills)))
        matched = [
            skill
            for skill in canonical_skills(list(job.required_skills) + list(job.preferred_skills))
            if skill in user_skills
        ]

        cover_letter: str = ""
        generated_by: str = ""
        letter_warnings: list[str] = []
        if include_cover_letter:
            cover_letter, generated_by, letter_warnings = generate_cover_letter(
                job, profile, matched, self._provider
            )
            warnings.extend(letter_warnings)

        platform = job.source_references[0].source if job.source_references else SourceName.MANUAL

        if existing is None:
            application = self._applications.create(
                Application(
                    job_id=job.id,
                    profile_id=profile.id,
                    platform=platform,
                    status=ApplicationStatus.SHORTLISTED,
                )
            )
        else:
            application = existing

        application.resume_id = resume.id if resume else None
        application.resume_variant_id = variant.id if variant else None
        application.resume_version_label = (
            f"{resume.label} / {variant.name} v{variant.version}"
            if resume and variant
            else (resume.label if resume else "")
        )
        if include_cover_letter:
            application.cover_letter = cover_letter
            application.cover_letter_version = application.cover_letter_version + 1
            application.cover_letter_generated_by = generated_by
        application.prepared_at = utcnow()

        prepared_answers = question_service.build_question_set(job, profile, extra_questions)
        answer_rows = [
            ApplicationAnswer(**question_service.to_dict(answer)) for answer in prepared_answers
        ]
        reused = self._fill_from_answer_bank(profile, answer_rows)
        self._applications.replace_answers(application, answer_rows)

        if application.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SCORED):
            self._tracker.transition(
                application,
                TransitionRequest(ApplicationStatus.SHORTLISTED, detail="prepared for review"),
            )
        if application.status is ApplicationStatus.SHORTLISTED:
            self._tracker.transition(
                application,
                TransitionRequest(
                    ApplicationStatus.READY_FOR_REVIEW,
                    detail=f"prepared with {len(prepared_answers)} questions",
                ),
            )

        blocking = [answer.question for answer in application.answers if answer.requires_user_input]
        self._snapshot_artifacts(application, variant)
        self._audit.record(
            "application.prepared",
            entity_type="application",
            entity_id=application.id,
            detail={
                "job_id": job.id,
                "questions": len(prepared_answers),
                "blocking": len(blocking),
                "reused_from_answer_bank": reused,
                "cover_letter_generated_by": generated_by,
                "resume_variant_id": variant.id if variant else None,
            },
        )
        self._session.flush()
        return PreparedApplication(
            application=application,
            variant=variant,
            blocking_questions=blocking,
            warnings=warnings,
            cover_letter_generated_by=generated_by,
            reused_answers=reused,
        )

    def _fill_from_answer_bank(
        self, profile: CandidateProfile, rows: list[ApplicationAnswer]
    ) -> int:
        """Fill unanswered questions from previously verified answers."""
        bank = self._saved_answers.as_map(profile.id)
        if not bank:
            return 0
        filled = 0
        for row in rows:
            if not row.requires_user_input:
                continue
            saved = bank.get(row.question_key)
            if saved is None or not saved.answer.strip():
                continue
            apply_saved_answer(row, saved)
            self._saved_answers.record_use(saved)
            filled += 1
        return filled

    def _snapshot_artifacts(
        self, application: Application, variant: ResumeVariant | None
    ) -> list[ApplicationArtifact]:
        """Store the exact material prepared for this application.

        Snapshots are content-addressed and deduplicated by hash, so re-preparing an
        application that produced identical text adds no row, while a changed resume
        variant or letter is kept alongside the earlier version rather than replacing it.
        """
        candidates: list[tuple[str, str, str]] = []
        if variant is not None and variant.content:
            candidates.append(
                ("resume_variant", f"{variant.name} v{variant.version}", variant.content)
            )
        if application.cover_letter:
            candidates.append(
                (
                    "cover_letter",
                    f"v{application.cover_letter_version}",
                    application.cover_letter,
                )
            )

        stored: list[ApplicationArtifact] = []
        for kind, label, content in candidates:
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            existing = self._session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.application_id == application.id,
                    ApplicationArtifact.kind == kind,
                    ApplicationArtifact.content_sha256 == digest,
                )
            ).first()
            if existing is not None:
                continue
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=kind,
                label=label,
                content=content,
                content_sha256=digest,
                byte_size=len(content.encode("utf-8")),
            )
            self._session.add(artifact)
            stored.append(artifact)
        self._session.flush()
        return stored

    def apply_answer_edits(
        self, application: Application, edits: dict[int, str]
    ) -> list[ApplicationAnswer]:
        """Record user edits. Any edited answer becomes ``user_entered``."""
        updated: list[ApplicationAnswer] = []
        for answer in application.answers:
            if answer.id not in edits:
                continue
            answer.answer = edits[answer.id]
            answer.provenance = AnswerProvenance.USER_ENTERED
            answer.requires_user_input = not bool(edits[answer.id].strip())
            if not answer.requires_user_input:
                answer.flag_reason = ""
            updated.append(answer)
        self._session.flush()
        return updated
