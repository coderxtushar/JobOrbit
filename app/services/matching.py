"""Matching and scoring.

A transparent weighted model over six categories, each scored 0-100, combined with
normalized weights taken from the profile. The rule-based scorer is the only scorer that
can decide a score; an LLM, when configured, may add a prose rationale but never alters a
number. That separation is deliberate: a model's confidence is not evidence.

Honesty rules encoded here:

* A skill the user did not list is reported as "not found in your profile", never as
  "you lack it".
* Skills that the listing did not state explicitly are scored as *preferred* and are
  surfaced in ``uncertain_requirements`` so the user can judge them.
* A category that cannot be assessed (no posting date, no stated experience) scores a
  neutral 50 and says so, rather than scoring 0 and silently sinking the job.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from app.db.models import CandidateProfile, EmploymentType, Job, WorkArrangement, utcnow
from app.schemas.profile import ScoringWeights
from app.services.evidence import (
    FOREIGN_ROLE_FAMILIES,
    DescriptionEvidence,
    EvidenceClass,
    analyse_description,
)
from app.services.filters import (
    SENIORITY_BY_LEVEL,
    FilterContext,
    FilterOutcome,
)
from app.services.filters import (
    evaluate as evaluate_filters,
)
from app.services.text import (
    canonical_skills,
    jaccard,
    normalize_location,
    seniority_level,
    title_tokens,
    tokens,
)

HIGH_BAND_MINIMUM = 80.0
REVIEW_BAND_MINIMUM = 65.0

NEUTRAL_SCORE = 50.0
_FRESHNESS_FULL_DAYS = 3
_FRESHNESS_ZERO_DAYS = 60

#: Ceiling for the skills category when the employer published no requirement list and the
#: compared skills were inferred from the description instead.
INFERRED_SKILLS_CEILING = 75.0

#: Ceiling for the skills category when every matched skill was an *incidental* mention -
#: a tool named in a company blurb or a benefit, with no requirements section crediting it.
#: Measured on the benchmark, this is what stopped a sales role scoring 50 on skills
#: because Python and SQL were named as things its customers use.
INCIDENTAL_SKILLS_CEILING = 35.0

#: Credit a skill earns by where the description put it, relative to a stated requirement.
#: An incidental mention is evidence of the word, not of the requirement.
_EVIDENCE_CREDIT: dict[EvidenceClass, float] = {
    EvidenceClass.REQUIRED: 1.0,
    EvidenceClass.PREFERRED: 0.5,
    EvidenceClass.INCIDENTAL: 0.2,
}

#: Minimum share of the configured weighting that must be assessable before a score may be
#: called a "high" match. Below this the number stands, but the band is demoted, because a
#: near-perfect score on a minority of the signal is not a confident match.
MINIMUM_COVERAGE_FOR_HIGH = 0.70

#: Coverage below which the evidence is called weak outright, independent of the score.
_MEDIUM_COVERAGE = 0.85


@dataclass(slots=True)
class CategoryScore:
    name: str
    score: float
    weight: float
    detail: str
    assessable: bool = True

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass(slots=True)
class MatchResult:
    total_score: float
    band: str
    categories: list[CategoryScore]
    matched_skills: list[str] = field(default_factory=list)
    missing_required_skills: list[str] = field(default_factory=list)
    missing_preferred_skills: list[str] = field(default_factory=list)
    uncertain_requirements: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    filtered_out: bool = False
    filter_reasons: list[str] = field(default_factory=list)
    scorer: str = "rule_based"
    #: Share of the configured weighting that could actually be judged, 0.0-1.0. This is
    #: the strength of the evidence, which is a different question from relevance.
    evidence_coverage: float = 1.0
    confidence: str = "high"
    confidence_reasons: list[str] = field(default_factory=list)

    @property
    def category_scores(self) -> dict[str, dict[str, object]]:
        return {
            category.name: {
                "score": round(category.score, 1),
                "weight": round(category.weight, 4),
                "contribution": round(category.contribution, 2),
                "detail": category.detail,
                "assessable": category.assessable,
            }
            for category in self.categories
        }


def band_for(score: float) -> str:
    if score >= HIGH_BAND_MINIMUM:
        return "high"
    if score >= REVIEW_BAND_MINIMUM:
        return "review"
    return "low"


def weights_for(profile: CandidateProfile) -> ScoringWeights:
    """Read weights from the profile, falling back to the documented defaults."""
    stored = profile.scoring_weights or {}
    if not stored:
        return ScoringWeights()
    try:
        return ScoringWeights.model_validate(stored)
    except Exception:
        return ScoringWeights()


def _score_skills(
    job: Job, profile: CandidateProfile, evidence: DescriptionEvidence
) -> tuple[CategoryScore, dict[str, list[str]]]:
    user_skills = set(canonical_skills(list(profile.technical_skills)))
    required = canonical_skills(list(job.required_skills))
    preferred = canonical_skills(list(job.preferred_skills))

    matched_required = [skill for skill in required if skill in user_skills]
    missing_required = [skill for skill in required if skill not in user_skills]
    matched_preferred = [skill for skill in preferred if skill in user_skills]
    missing_preferred = [skill for skill in preferred if skill not in user_skills]

    breakdown = {
        "matched": sorted(set(matched_required + matched_preferred)),
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
    }

    if not required and not preferred:
        return (
            CategoryScore(
                "skills",
                NEUTRAL_SCORE,
                0.0,
                "the listing stated no skills, so this category could not be assessed",
                assessable=False,
            ),
            breakdown,
        )
    if not user_skills:
        return (
            CategoryScore(
                "skills",
                NEUTRAL_SCORE,
                0.0,
                "your profile lists no technical skills yet, so skills could not be compared",
                assessable=False,
            ),
            breakdown,
        )

    if required:
        # The employer published a requirement list, so it is taken at its word. Required
        # skills carry four times the weight of preferred ones: missing a stated
        # requirement matters far more than missing a nice-to-have.
        required_weight, preferred_weight = 4.0, 1.0
        earned = len(matched_required) * required_weight + len(matched_preferred) * preferred_weight
        available = len(required) * required_weight + len(preferred) * preferred_weight
        score = 100.0 * earned / available if available else NEUTRAL_SCORE
        detail = (
            f"{len(matched_required)}/{len(required)} stated requirements and "
            f"{len(matched_preferred)}/{len(preferred)} preferred skills are in your profile"
        )
        return CategoryScore("skills", round(score, 1), 0.0, detail), breakdown

    return _score_inferred_skills(preferred, user_skills, evidence, breakdown)


def _score_inferred_skills(
    preferred: list[str],
    user_skills: set[str],
    evidence: DescriptionEvidence,
    breakdown: dict[str, list[str]],
) -> tuple[CategoryScore, dict[str, list[str]]]:
    """Score skills the employer never published as requirements.

    Each skill is credited by *where* the description mentioned it, so a tool named once in
    a company blurb cannot earn what a stated requirement earns. The ceiling then depends
    on whether the listing had a requirements section at all: inference from a real
    requirements block is weak evidence, inference from passing mentions is barely evidence.
    """
    earned = 0.0
    available = 0.0
    matched_by_class: dict[EvidenceClass, list[str]] = {
        EvidenceClass.REQUIRED: [],
        EvidenceClass.PREFERRED: [],
        EvidenceClass.INCIDENTAL: [],
    }
    for skill in preferred:
        evidence_class = evidence.classify(skill)
        credit = _EVIDENCE_CREDIT[evidence_class]
        available += credit
        if skill in user_skills:
            earned += credit
            matched_by_class[evidence_class].append(skill)

    score = 100.0 * earned / available if available else NEUTRAL_SCORE
    matched_total = sum(len(items) for items in matched_by_class.values())
    only_incidental = matched_total > 0 and not (
        matched_by_class[EvidenceClass.REQUIRED] or matched_by_class[EvidenceClass.PREFERRED]
    )

    if only_incidental or not evidence.has_requirements_section:
        ceiling = INCIDENTAL_SKILLS_CEILING if only_incidental else INFERRED_SKILLS_CEILING
    else:
        ceiling = INFERRED_SKILLS_CEILING
    score = min(score, ceiling)

    where = (
        f"{len(matched_by_class[EvidenceClass.REQUIRED])} under a requirements heading, "
        f"{len(matched_by_class[EvidenceClass.PREFERRED])} under a nice-to-have heading, "
        f"{len(matched_by_class[EvidenceClass.INCIDENTAL])} mentioned only in passing"
    )
    detail = (
        f"{matched_total}/{len(preferred)} skills inferred from the description are in your "
        f"profile ({where}); the employer stated no requirements, so this category is "
        f"capped at {ceiling:g}"
    )
    if only_incidental:
        detail += " because every match was an incidental mention"
    return CategoryScore("skills", round(score, 1), 0.0, detail), breakdown


#: Role nouns that appear in almost every job title and therefore carry no information
#: about what the job actually is. "Technical Support Engineer" and "Mechanical Design
#: Engineer" each share exactly one word with "Software Engineer" — this one — and that
#: single generic overlap was enough to earn 41/100 on title fit, which is 10 points of
#: unearned credit at the default 25% weight.
_GENERIC_ROLE_TOKENS: frozenset[str] = frozenset(
    {
        "engineer",
        "engineering",
        "developer",
        "development",
        "programmer",
        "analyst",
        "specialist",
        "consultant",
        "associate",
        "executive",
        "officer",
        "manager",
        "lead",
        "head",
        "architect",
        "administrator",
        "technician",
        "operator",
        "assistant",
        "coordinator",
        "junior",
        "senior",
        "staff",
        "principal",
        "trainee",
        "graduate",
        "new",
        "grad",
        "entry",
        "level",
        "tier",
        "technical",
    }
)

#: What a title scores when the only shared word is a generic role noun. Not zero, because
#: the overlap is real, but far too little to carry a job into the shortlist on its own.
_GENERIC_ONLY_TITLE_CAP = 25.0

#: What a title scores when the role belongs to a discipline the candidate is not pursuing.
#: Lower than the generic cap because the mismatch is positive evidence of the wrong job,
#: not merely absence of evidence for the right one.
_ROLE_FAMILY_MISMATCH_CAP = 12.0


def _foreign_families(text: str) -> set[str]:
    """Non-software role families named in a title, e.g. {"sales"} for "Sales Engineer"."""
    words = tokens(text)
    return {family for family, markers in FOREIGN_ROLE_FAMILIES.items() if words & markers}


def _score_title(job: Job, profile: CandidateProfile) -> CategoryScore:
    targets = [title for title in profile.target_titles if title.strip()]
    if not targets:
        return CategoryScore(
            "title",
            NEUTRAL_SCORE,
            0.0,
            "you have not set any target job titles, so title fit could not be assessed",
            assessable=False,
        )

    job_tokens = title_tokens(job.title)
    if not job_tokens:
        return CategoryScore(
            "title",
            NEUTRAL_SCORE,
            0.0,
            "the job title carried no comparable words",
            assessable=False,
        )

    best_score = 0.0
    best_title = ""
    best_overlap: set[str] = set()
    for target in targets:
        target_tokens = title_tokens(target)
        if not target_tokens:
            continue
        shared = job_tokens & target_tokens
        overlap = len(shared) / len(target_tokens)
        similarity = jaccard(job_tokens, target_tokens)
        combined = 100.0 * (0.7 * overlap + 0.3 * similarity)
        if combined > best_score:
            best_score, best_title, best_overlap = combined, target, shared

    if best_score == 0.0:
        return CategoryScore(
            "title",
            0.0,
            0.0,
            f"'{job.title}' shares no significant words with any of your {len(targets)} "
            "target titles",
        )

    job_families = _foreign_families(job.title)
    wanted_families = {family for target in targets for family in _foreign_families(target)}
    mismatched = job_families - wanted_families
    if mismatched:
        family_names = ", ".join(sorted(name.replace("_", " ") for name in mismatched))
        return CategoryScore(
            "title",
            round(min(best_score, _ROLE_FAMILY_MISMATCH_CAP), 1),
            0.0,
            f"'{job.title}' is a {family_names} role, which is not among the kinds of work "
            f"your target titles describe, despite sharing words with '{best_title}'",
        )

    if best_overlap and best_overlap <= _GENERIC_ROLE_TOKENS:
        shared_words = ", ".join(sorted(best_overlap))
        return CategoryScore(
            "title",
            round(min(best_score, _GENERIC_ONLY_TITLE_CAP), 1),
            0.0,
            f"'{job.title}' shares only the generic word(s) '{shared_words}' with "
            f"'{best_title}', which says nothing about what the role does",
        )

    return CategoryScore(
        "title",
        round(min(best_score, 100.0), 1),
        0.0,
        f"closest target title is '{best_title}'",
    )


def _score_seniority_gap(job_level: int, profile: CandidateProfile, basis: str) -> CategoryScore:
    user_level = SENIORITY_BY_LEVEL.get(profile.experience_level, 0)
    gap = abs(job_level - user_level)
    return CategoryScore(
        "experience",
        round(max(0.0, 100.0 - gap * 25.0), 1),
        0.0,
        f"{basis} (level {job_level}) against your '{profile.experience_level}' level",
    )


def _score_shortfall(required_years: float, user_years: float, basis: str) -> CategoryScore:
    shortfall = required_years - user_years
    return CategoryScore(
        "experience",
        round(max(0.0, 100.0 - shortfall * 25.0), 1),
        0.0,
        f"{basis} asks for {required_years:g}+ years; your profile records {user_years:g}",
    )


def _score_experience(
    job: Job, profile: CandidateProfile, evidence: DescriptionEvidence
) -> CategoryScore:
    user_years = profile.years_experience or 0.0
    low, high = job.experience_min_years, job.experience_max_years

    if low is None and high is None:
        # The structured field said nothing, so fall back to what the listing itself says.
        # A bar written in prose ("At least 7+ years of relevant professional experience")
        # is as binding as one in a field, and before this was read, roles demanding five
        # to seven years ranked in the high band for a candidate with months.
        if evidence.stated_min_years is not None and not evidence.mentions_fresher_opening:
            if evidence.stated_min_years > user_years:
                return _score_shortfall(evidence.stated_min_years, user_years, "the description")
            return CategoryScore(
                "experience",
                100.0,
                0.0,
                f"the description asks for {evidence.stated_min_years:g} years; your "
                f"{user_years:g} meet it",
            )

        job_level = seniority_level(job.title)
        if job_level is None:
            return CategoryScore(
                "experience",
                NEUTRAL_SCORE,
                0.0,
                "the listing stated no experience requirement and the title implies no seniority",
                assessable=False,
            )
        return _score_seniority_gap(job_level, profile, "inferred from the title's seniority")

    if low is not None and user_years < low:
        return _score_shortfall(low, user_years, "the listing")
    if high is not None and user_years > high + 2:
        return CategoryScore(
            "experience",
            60.0,
            0.0,
            f"caps experience at {high:g} years; you record {user_years:g}, which may be over-qualified",
        )
    return CategoryScore(
        "experience",
        100.0,
        0.0,
        f"your {user_years:g} years fall within the stated range",
    )


def _score_location(job: Job, profile: CandidateProfile) -> CategoryScore:
    wanted_arrangements = set(profile.work_arrangements or [])
    preferred = [item.strip().lower() for item in profile.preferred_locations if item.strip()]

    if job.work_arrangement is WorkArrangement.REMOTE:
        if not wanted_arrangements or "remote" in wanted_arrangements:
            return CategoryScore("location", 100.0, 0.0, "remote, which you accept")
        return CategoryScore(
            "location", 40.0, 0.0, "remote, which is not among your preferred arrangements"
        )

    if job.work_arrangement is not WorkArrangement.UNKNOWN and wanted_arrangements:
        if job.work_arrangement.value not in wanted_arrangements:
            return CategoryScore(
                "location",
                35.0,
                0.0,
                f"'{job.work_arrangement.value}' is not among your preferred arrangements",
            )

    if not preferred:
        return CategoryScore(
            "location",
            NEUTRAL_SCORE,
            0.0,
            "you have set no preferred locations, so location fit could not be assessed",
            assessable=False,
        )
    if not job.location_normalized:
        return CategoryScore(
            "location", NEUTRAL_SCORE, 0.0, "the listing stated no location", assessable=False
        )

    job_parts = {part.strip() for part in job.location_normalized.split(",") if part.strip()}
    for wanted in preferred:
        wanted_parts = {
            part.strip() for part in normalize_location(wanted).split(",") if part.strip()
        }
        if job_parts & wanted_parts:
            return CategoryScore("location", 100.0, 0.0, f"matches your preference '{wanted}'")

    if profile.open_to_relocation:
        return CategoryScore(
            "location",
            65.0,
            0.0,
            f"'{job.location}' is outside your preferences, but you are open to relocation",
        )
    return CategoryScore(
        "location", 20.0, 0.0, f"'{job.location}' does not match any preferred location"
    )


def _score_freshness(job: Job, now: datetime) -> CategoryScore:
    if job.posted_at is None:
        return CategoryScore(
            "freshness",
            NEUTRAL_SCORE,
            0.0,
            "the source gave no posting date; discovery time is not used as a substitute",
            assessable=False,
        )
    age_days = max((now - job.posted_at).total_seconds() / 86400.0, 0.0)
    if age_days <= _FRESHNESS_FULL_DAYS:
        score = 100.0
    elif age_days >= _FRESHNESS_ZERO_DAYS:
        score = 0.0
    else:
        span = _FRESHNESS_ZERO_DAYS - _FRESHNESS_FULL_DAYS
        score = 100.0 * (1.0 - (age_days - _FRESHNESS_FULL_DAYS) / span)
    qualifier = " (approximate)" if job.posted_at_is_approximate else ""
    return CategoryScore(
        "freshness", round(score, 1), 0.0, f"posted {age_days:.0f} days ago{qualifier}"
    )


def _score_preferences(job: Job, profile: CandidateProfile) -> CategoryScore:
    points: list[float] = []
    notes: list[str] = []

    wanted_types = set(profile.employment_types or [])
    if wanted_types and job.employment_type is not EmploymentType.UNKNOWN:
        hit = job.employment_type.value in wanted_types
        points.append(100.0 if hit else 0.0)
        notes.append(
            f"employment type '{job.employment_type.value}' "
            f"{'matches' if hit else 'does not match'} your preferences"
        )

    if profile.salary_expectation_min is not None and job.salary_max is not None:
        meets = job.salary_max >= profile.salary_expectation_min
        points.append(100.0 if meets else 25.0)
        notes.append(
            f"advertised upper salary {'meets' if meets else 'is below'} your stated minimum"
        )

    if job.education_requirements and profile.education:
        degrees = " ".join(
            str(entry.get("degree", "")) for entry in profile.education if isinstance(entry, dict)
        ).lower()
        overlap = any(
            requirement.lower().split()[0] in degrees
            for requirement in job.education_requirements
            if requirement.strip()
        )
        points.append(100.0 if overlap else 40.0)
        notes.append(
            "stated education requirement "
            f"{'appears in' if overlap else 'was not found in'} your education history"
        )

    if not points:
        return CategoryScore(
            "preferences",
            NEUTRAL_SCORE,
            0.0,
            "no comparable preference data on either side",
            assessable=False,
        )
    return CategoryScore("preferences", round(sum(points) / len(points), 1), 0.0, "; ".join(notes))


def _assess_confidence(
    *,
    coverage: float,
    evidence: DescriptionEvidence,
    skills_were_inferred: bool,
    skills_detail: str,
) -> tuple[str, list[str]]:
    """Judge how strong the evidence is, independently of how relevant the job looks.

    Relevance and confidence answer different questions, so they are reported separately:
    a listing can look like a perfect match *and* be impossible to judge. A short
    description only undermines confidence when the description was the evidence - if the
    employer published a requirements list, its brevity elsewhere does not matter.
    """
    reasons: list[str] = []
    if coverage < MINIMUM_COVERAGE_FOR_HIGH:
        reasons.append(
            f"only {coverage * 100:.0f}% of the scoring weight could be assessed from this listing"
        )
    elif coverage < _MEDIUM_COVERAGE:
        reasons.append(f"{coverage * 100:.0f}% of the scoring weight could be assessed")

    if skills_were_inferred:
        if evidence.is_sparse:
            reasons.append(
                f"the description is only {evidence.word_count} words, so the skills had to be "
                "inferred from very little text"
            )
        elif "incidental mention" in skills_detail:
            reasons.append(
                "every skill matched was mentioned only in passing, not under a requirements "
                "heading"
            )
        else:
            reasons.append("the employer published no requirements list, so skills were inferred")

    if coverage < MINIMUM_COVERAGE_FOR_HIGH or (skills_were_inferred and evidence.is_sparse):
        return "low", reasons
    if reasons:
        return "medium", reasons
    return "high", reasons


def score_job(
    job: Job,
    profile: CandidateProfile,
    *,
    filter_context: FilterContext | None = None,
    now: datetime | None = None,
) -> MatchResult:
    """Score one job against one profile.

    Weights of categories that could not be assessed are redistributed across the rest, so
    a missing posting date does not drag the total toward the neutral midpoint. The total
    is a *relevance* number; how much evidence stood behind it is reported separately as
    ``evidence_coverage`` and ``confidence``.
    """
    now = now or utcnow()
    evidence = analyse_description(job.description or "")
    context = filter_context or FilterContext()
    if context.description_evidence is None:
        context = replace(context, description_evidence=evidence)
    filter_outcome: FilterOutcome = evaluate_filters(job, profile, context)
    skills_were_inferred = not job.required_skills

    skills_category, skill_breakdown = _score_skills(job, profile, evidence)
    categories = [
        skills_category,
        _score_title(job, profile),
        _score_experience(job, profile, evidence),
        _score_location(job, profile),
        _score_freshness(job, now),
        _score_preferences(job, profile),
    ]

    configured = weights_for(profile).normalized()
    assessable_total = sum(configured[c.name] for c in categories if c.assessable)
    for category in categories:
        if not category.assessable or assessable_total == 0:
            category.weight = 0.0
        else:
            category.weight = configured[category.name] / assessable_total

    total = sum(category.contribution for category in categories)
    if assessable_total == 0:
        total = NEUTRAL_SCORE

    explanation = [
        f"{category.name}: {category.score:g}/100 "
        f"(weight {category.weight * 100:.0f}%) - {category.detail}"
        for category in categories
    ]
    unassessed = [category.name for category in categories if not category.assessable]
    if unassessed:
        explanation.append(
            "Not assessable from the available data, so excluded from the weighting: "
            + ", ".join(unassessed)
        )
    if filter_outcome.notes:
        explanation.extend(f"Note: {note}" for note in filter_outcome.notes)

    uncertain = list(job.preferred_skills) if not job.required_skills else []
    if uncertain:
        explanation.append(
            "The listing did not publish an explicit requirements list; the skills shown "
            "were inferred from its description and should be read as uncertain."
        )

    missing_required = skill_breakdown["missing_required"]
    if missing_required:
        explanation.append(
            "Skills the listing requires that are not in your profile: "
            + ", ".join(missing_required)
            + ". This reflects what your profile records, not a judgement that you lack them."
        )

    rounded = round(max(0.0, min(100.0, total)), 1)
    coverage = assessable_total
    confidence, confidence_reasons = _assess_confidence(
        coverage=coverage,
        evidence=evidence,
        skills_were_inferred=skills_were_inferred,
        skills_detail=skills_category.detail,
    )

    # The number is left untouched and auditable; only the band is demoted. A near-perfect
    # score computed from a minority of the signal, or from a 40-word teaser, is not a
    # confident match. Without this, a listing that published nothing but a title ranks
    # first.
    band = band_for(rounded)
    if band == "high" and confidence != "high":
        band = "review"
        explanation.append(
            f"Scored {rounded:g}, but only {coverage * 100:.0f}% of the scoring weight "
            "could be assessed from this listing, so it is shown as 'worth a look' rather "
            "than a high-confidence match."
        )
    if confidence_reasons:
        explanation.append(
            f"Evidence confidence: {confidence} - " + "; ".join(confidence_reasons) + "."
        )

    return MatchResult(
        total_score=rounded,
        band=band,
        categories=categories,
        matched_skills=skill_breakdown["matched"],
        missing_required_skills=missing_required,
        missing_preferred_skills=skill_breakdown["missing_preferred"],
        uncertain_requirements=uncertain,
        explanation=explanation,
        filtered_out=not filter_outcome.eligible,
        filter_reasons=filter_outcome.reasons,
        scorer="rule_based",
        evidence_coverage=round(coverage, 4),
        confidence=confidence,
        confidence_reasons=confidence_reasons,
    )
