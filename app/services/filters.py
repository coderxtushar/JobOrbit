"""Hard eligibility filters.

Filters answer "should this listing be excluded outright?" and are kept strictly apart from
scoring, which answers "how well does it fit?". Mixing them is what makes a job vanish with
no explanation.

Two design rules follow from the requirement not to reject promising roles over wording:

* Every filter needs *positive* evidence of ineligibility. Unknown location, unknown
  employment type and absent posting date never trigger a rejection.
* A seniority mismatch only fires on an explicit marker in the title ("Senior", "Principal")
  or a stated minimum experience that exceeds the user's by a configurable margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.db.models import CandidateProfile, EmploymentType, Job, JobStatus, WorkArrangement, utcnow
from app.services.evidence import DescriptionEvidence, analyse_description
from app.services.text import normalize_company, normalize_location, seniority_level

SENIORITY_BY_LEVEL: dict[str, int] = {
    "fresher": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
}

SENIORITY_TOLERANCE = 2
EXPERIENCE_TOLERANCE_YEARS = 2.0


@dataclass(slots=True)
class FilterOutcome:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.eligible = False
        self.reasons.append(reason)


@dataclass(frozen=True, slots=True)
class FilterContext:
    """Facts the filters need that do not live on the job or the profile."""

    already_applied: bool = False
    now: datetime | None = None
    #: Parsed description, supplied by the scorer so the same text is not analysed twice
    #: per job. Left as ``None`` by other callers, which makes ``evaluate`` compute it.
    description_evidence: DescriptionEvidence | None = None

    @property
    def reference_time(self) -> datetime:
        return self.now or utcnow()


def _location_is_acceptable(job: Job, profile: CandidateProfile) -> bool:
    """Decide location acceptability, treating silence as acceptance."""
    preferred = [normalize_location(item) for item in profile.preferred_locations if item.strip()]
    arrangements = set(profile.work_arrangements or [])

    if job.work_arrangement is WorkArrangement.REMOTE and (
        not arrangements or "remote" in arrangements
    ):
        return True
    if not preferred:
        return True
    if not job.location_normalized:
        return True

    job_parts = {part.strip() for part in job.location_normalized.split(",") if part.strip()}
    for wanted in preferred:
        wanted_parts = {part.strip() for part in wanted.split(",") if part.strip()}
        if job_parts & wanted_parts:
            return True
        if any(wanted in part or part in wanted for part in job_parts for wanted in wanted_parts):
            return True

    return bool(profile.open_to_relocation)


def _seniority_reasons(
    job: Job, profile: CandidateProfile, evidence: DescriptionEvidence
) -> list[str]:
    """Every independent reason the seniority is incompatible, not just the first.

    A role can be out of reach on both its title and its stated minimum experience, and
    reporting only one leaves the user guessing whether fixing it would help.
    """
    user_level = SENIORITY_BY_LEVEL.get(profile.experience_level, 0)
    job_level = seniority_level(job.title)
    reasons: list[str] = []

    if job_level is not None and job_level - user_level > SENIORITY_TOLERANCE:
        reasons.append(
            f"the title indicates a seniority well above '{profile.experience_level}' "
            f"(title level {job_level} vs yours {user_level})"
        )

    required = job.experience_min_years
    source = "requires"
    if required is None and not evidence.mentions_fresher_opening:
        # The bar exists only in the prose. "At least 7+ years of relevant professional
        # experience" is as binding as a structured field, and ignoring it let roles
        # demanding five to seven years stay eligible and score in the high band for a
        # candidate with months. A listing that also says it welcomes freshers is trusted
        # over a years figure, because that figure is usually boilerplate.
        required = evidence.stated_min_years
        source = "states in its description that it requires"

    if (
        required is not None
        and required - (profile.years_experience or 0.0) > EXPERIENCE_TOLERANCE_YEARS
    ):
        reasons.append(
            f"{source} at least {required:g} years of experience; your profile records "
            f"{profile.years_experience:g}"
        )
    return reasons


def evaluate(
    job: Job, profile: CandidateProfile, context: FilterContext | None = None
) -> FilterOutcome:
    """Apply every hard filter and return the verdict with human-readable reasons."""
    context = context or FilterContext()
    outcome = FilterOutcome(eligible=True)
    evidence = context.description_evidence or analyse_description(job.description or "")

    if context.already_applied:
        outcome.reject("you have already applied to this job")

    if job.status is JobStatus.EXPIRED or job.closed_at is not None:
        outcome.reject("the listing is closed or expired")

    if job.duplicate_of_id is not None:
        outcome.reject(f"duplicate of job {job.duplicate_of_id}")

    company_key = job.company_normalized or normalize_company(job.company)
    for excluded in profile.excluded_companies:
        excluded_key = normalize_company(excluded)
        if excluded_key and excluded_key in company_key:
            outcome.reject(f"'{job.company}' matches your excluded company '{excluded}'")
            break

    haystack = f"{job.title}\n{job.description[:5000]}".lower()
    for keyword in profile.excluded_keywords:
        token = keyword.strip().lower()
        if token and token in haystack:
            outcome.reject(f"contains your excluded keyword '{keyword}'")
            break

    if not _location_is_acceptable(job, profile):
        outcome.reject(
            f"location '{job.location or 'unspecified'}' is outside your preferred locations "
            "and you are not marked open to relocation"
        )

    for reason in _seniority_reasons(job, profile, evidence):
        outcome.reject(reason)

    wanted_types = set(profile.employment_types or [])
    if wanted_types and job.employment_type is not EmploymentType.UNKNOWN:
        if job.employment_type.value not in wanted_types:
            outcome.reject(
                f"employment type '{job.employment_type.value}' is not in your preferences "
                f"({sorted(wanted_types)})"
            )

    max_age = profile.max_job_age_days
    if job.posted_at is not None and max_age:
        cutoff = context.reference_time - timedelta(days=max_age)
        if job.posted_at < cutoff:
            age_days = (context.reference_time - job.posted_at).days
            outcome.reject(f"posted {age_days} days ago, older than your {max_age}-day limit")
    elif job.posted_at is None:
        outcome.notes.append(
            "no posting date, so the age limit was not applied; this listing may be stale"
        )

    if job.employment_type is EmploymentType.UNKNOWN:
        outcome.notes.append("employment type could not be determined from the listing")
    if not job.location_normalized:
        outcome.notes.append("the listing did not state a location")

    return outcome
