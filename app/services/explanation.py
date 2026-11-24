"""Turns a score into an account a person can check.

:mod:`app.services.matching` already produces category scores, confidence and a list of
explanation lines, but reading those still requires knowing how the scorer works. This
module re-reads the same job, profile and match and groups the findings into the sections a
jobseeker actually asks about - what fits, what is missing, whether the seniority and
location work, how good the evidence is, and why anything was held back.

Two rules hold throughout:

* Nothing here computes or alters a score. It reports what the scorer already decided,
  which keeps a single source of truth for every number.
* A claim about the listing carries the listing's own words. ``quote`` is the exact span
  the finding was read from, so a user can disagree with the scorer on the evidence rather
  than on faith.

Anything the listing did not say is reported as unknown. Silence is never upgraded into a
fact in either direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.db.models import CandidateProfile, Job, JobMatch, WorkArrangement
from app.services.evidence import DescriptionEvidence, EvidenceClass, analyse_description
from app.services.text import canonical_skill, canonical_skills, remote_scope, tokens

#: Where a finding came from. ``listing`` findings carry a quote; ``profile`` and ``scoring``
#: findings do not, because there is no third-party text to quote.
SOURCE_LISTING = "listing"
SOURCE_PROFILE = "profile"
SOURCE_SCORING = "scoring"

Categories = Mapping[str, Mapping[str, object]]


class ScoredMatch(Protocol):
    """The parts of a score this module reads.

    Declared structurally so a freshly computed :class:`~app.services.matching.MatchResult`
    can be explained without being persisted first. A stored ``JobMatch`` row satisfies it
    at runtime but not under mypy, which sees SQLAlchemy's ``Mapped`` descriptors rather
    than the instance types, so rows go through :class:`StoredMatch`.
    """

    @property
    def total_score(self) -> float: ...

    @property
    def band(self) -> str: ...

    @property
    def evidence_coverage(self) -> float: ...

    @property
    def confidence(self) -> str: ...

    @property
    def confidence_reasons(self) -> list[str]: ...

    @property
    def filter_reasons(self) -> list[str]: ...

    @property
    def uncertain_requirements(self) -> list[str]: ...

    @property
    def category_scores(self) -> Categories: ...


@dataclass(frozen=True, slots=True)
class StoredMatch:
    """A persisted ``JobMatch`` row presented as a :class:`ScoredMatch`."""

    total_score: float
    band: str
    evidence_coverage: float
    confidence: str
    confidence_reasons: list[str]
    filter_reasons: list[str]
    uncertain_requirements: list[str]
    category_scores: Categories

    @classmethod
    def from_row(cls, row: JobMatch) -> StoredMatch:
        return cls(
            total_score=row.total_score,
            band=row.band,
            evidence_coverage=row.evidence_coverage,
            confidence=row.confidence,
            confidence_reasons=list(row.confidence_reasons or []),
            filter_reasons=list(row.filter_reasons or []),
            uncertain_requirements=list(row.uncertain_requirements or []),
            category_scores=dict(row.category_scores or {}),
        )


STATUS_IN_PROFILE = "in_profile"
STATUS_RELATED = "related_in_profile"
STATUS_NOT_IN_PROFILE = "not_in_profile"
STATUS_NOT_IN_LISTING = "not_in_listing"

_EVIDENCE_WORDING = {
    EvidenceClass.REQUIRED: "stated as a requirement",
    EvidenceClass.PREFERRED: "listed as preferred",
    EvidenceClass.INCIDENTAL: "mentioned only in passing",
}

#: Words that appear in so many skill names that sharing one proves no relationship.
#: Without this, "software testing" and "software architecture" would read as related.
_WEAK_SKILL_TOKENS = frozenset(
    {
        "software",
        "engineering",
        "development",
        "developer",
        "programming",
        "computer",
        "science",
        "data",
        "web",
        "cloud",
        "system",
        "systems",
        "tools",
        "framework",
        "frameworks",
        "api",
        "apis",
    }
)


@dataclass(slots=True)
class Finding:
    statement: str
    source: str = SOURCE_SCORING
    quote: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"statement": self.statement, "source": self.source, "quote": self.quote}


@dataclass(slots=True)
class Section:
    key: str
    title: str
    findings: list[Finding] = field(default_factory=list)
    empty_note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "findings": [finding.as_dict() for finding in self.findings],
            "empty_note": self.empty_note,
        }


@dataclass(slots=True)
class SkillFinding:
    skill: str
    status: str
    evidence_class: str
    note: str
    quote: str = ""
    related_to: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "skill": self.skill,
            "status": self.status,
            "evidence_class": self.evidence_class,
            "note": self.note,
            "quote": self.quote,
            "related_to": self.related_to,
        }


@dataclass(slots=True)
class JobExplanation:
    job_id: int
    sections: list[Section]
    skills: list[SkillFinding]

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "sections": [section.as_dict() for section in self.sections],
            "skills": [skill.as_dict() for skill in self.skills],
        }


def _meaningful_tokens(skill: str) -> set[str]:
    return tokens(skill) - _WEAK_SKILL_TOKENS


def _related_profile_skill(skill: str, profile_skills: list[str]) -> str:
    """A profile skill whose name genuinely overlaps ``skill``, or ''.

    Used only to say "you list React, which shares a name with React Native" - never to
    credit the candidate with the skill. Overlap of a name is not a demonstration, so this
    is reported as its own status rather than folded into a match.
    """
    wanted = _meaningful_tokens(skill)
    if not wanted:
        return ""
    for candidate in profile_skills:
        if candidate == skill:
            continue
        if wanted & _meaningful_tokens(candidate):
            return candidate
    return ""


def _skill_findings(
    job: Job, profile: CandidateProfile, evidence: DescriptionEvidence
) -> list[SkillFinding]:
    profile_skills = canonical_skills(list(profile.technical_skills))
    profile_set = set(profile_skills)
    stated = bool(job.required_skills)

    listing_skills: dict[str, EvidenceClass] = {}
    for skill in canonical_skills(list(job.required_skills)):
        listing_skills[skill] = EvidenceClass.REQUIRED
    for skill in canonical_skills(list(job.preferred_skills)):
        listing_skills.setdefault(
            skill, EvidenceClass.PREFERRED if stated else evidence.classify(skill)
        )

    findings: list[SkillFinding] = []
    for skill, evidence_class in listing_skills.items():
        quote = evidence.spans.get(skill, "")
        where = _EVIDENCE_WORDING[evidence_class]
        if skill in profile_set:
            findings.append(
                SkillFinding(
                    skill=skill,
                    status=STATUS_IN_PROFILE,
                    evidence_class=evidence_class.value,
                    note=f"{where}; present in your profile",
                    quote=quote,
                )
            )
            continue
        related = _related_profile_skill(skill, profile_skills)
        if related:
            findings.append(
                SkillFinding(
                    skill=skill,
                    status=STATUS_RELATED,
                    evidence_class=evidence_class.value,
                    note=(
                        f"{where}; your profile lists '{related}', which shares a name but is "
                        "not the same thing, so this is not counted as a match"
                    ),
                    quote=quote,
                    related_to=related,
                )
            )
            continue
        findings.append(
            SkillFinding(
                skill=skill,
                status=STATUS_NOT_IN_PROFILE,
                evidence_class=evidence_class.value,
                note=f"{where}; not found in your profile",
                quote=quote,
            )
        )

    for skill in profile_skills:
        if skill in listing_skills:
            continue
        findings.append(
            SkillFinding(
                skill=skill,
                status=STATUS_NOT_IN_LISTING,
                evidence_class="",
                note="in your profile; this listing does not ask about it",
            )
        )
    return findings


def _strong_matches(
    job: Job, match: ScoredMatch, skills: list[SkillFinding], categories: Categories
) -> Section:
    section = Section(
        "strong_matches",
        "Strong matches",
        empty_note="Nothing in this listing lines up clearly with your profile.",
    )
    for finding in skills:
        if finding.status != STATUS_IN_PROFILE:
            continue
        section.findings.append(
            Finding(
                f"{finding.skill} — {finding.note}",
                source=SOURCE_LISTING if finding.quote else SOURCE_PROFILE,
                quote=finding.quote,
            )
        )
    title = categories.get("title") or {}
    title_score = title.get("score")
    if isinstance(title_score, int | float) and title_score >= 70:
        section.findings.append(
            Finding(f"Title: {title.get('detail', '')}", source=SOURCE_SCORING, quote=job.title)
        )
    return section


def _missing_requirements(skills: list[SkillFinding]) -> Section:
    section = Section(
        "missing_requirements",
        "Missing or unproven requirements",
        empty_note="Every skill this listing names is already in your profile.",
    )
    for finding in skills:
        if finding.status not in (STATUS_NOT_IN_PROFILE, STATUS_RELATED):
            continue
        section.findings.append(
            Finding(
                f"{finding.skill} — {finding.note}",
                source=SOURCE_LISTING if finding.quote else SOURCE_SCORING,
                quote=finding.quote,
            )
        )
    return section


def _experience_fit(
    job: Job, profile: CandidateProfile, evidence: DescriptionEvidence, categories: Categories
) -> Section:
    section = Section("experience_fit", "Experience and seniority")
    years = profile.years_experience or 0.0
    section.findings.append(
        Finding(
            f"Your profile records {years:g} year(s) at '{profile.experience_level}' level.",
            source=SOURCE_PROFILE,
        )
    )
    if job.experience_min_years is not None or job.experience_max_years is not None:
        low = job.experience_min_years
        high = job.experience_max_years
        stated = (
            f"{low:g}–{high:g} years"
            if low is not None and high is not None
            else f"{low:g}+ years"
            if low is not None
            else f"up to {high:g} years"
        )
        section.findings.append(
            Finding(
                f"The listing states {stated} in its own experience field.",
                source=SOURCE_LISTING,
                quote=job.experience_raw or stated,
            )
        )
    elif evidence.stated_min_years is not None:
        section.findings.append(
            Finding(
                f"No structured experience field; the description asks for "
                f"{evidence.stated_min_years:g} years in prose.",
                source=SOURCE_LISTING,
                quote=evidence.years_phrase or "",
            )
        )
    else:
        section.findings.append(
            Finding(
                "The listing states no experience requirement, so this is unknown rather "
                "than assumed to be open.",
                source=SOURCE_LISTING,
            )
        )
    if evidence.mentions_fresher_opening:
        section.findings.append(
            Finding("The listing says it is open to entry-level candidates.", source=SOURCE_LISTING)
        )
    experience = categories.get("experience") or {}
    if experience:
        section.findings.append(
            Finding(
                f"Scored {experience.get('score')}/100 — {experience.get('detail', '')}",
                source=SOURCE_SCORING,
            )
        )
    return section


def _location_fit(job: Job, profile: CandidateProfile, categories: Categories) -> Section:
    section = Section("location_fit", "Location and work mode")
    section.findings.append(
        Finding(
            f"Listing location: {job.location or 'not stated'} · arrangement "
            f"'{job.work_arrangement.value}'.",
            source=SOURCE_LISTING,
            quote=job.location or "",
        )
    )
    if job.work_arrangement is WorkArrangement.REMOTE:
        scope = remote_scope(job.location or "", job.description or "")
        wording = {
            "india": "Remote, and the listing names India, so it is open to you.",
            "elsewhere": "Remote, but the listing fences it to another region.",
            "unstated": "Remote with no region stated, so eligibility is unknown rather "
            "than assumed.",
        }[scope]
        section.findings.append(Finding(wording, source=SOURCE_LISTING))
    preferred = [item for item in profile.preferred_locations if item.strip()]
    section.findings.append(
        Finding(
            "Your preferences: "
            + (", ".join(preferred) if preferred else "none set")
            + (" · open to relocation" if profile.open_to_relocation else ""),
            source=SOURCE_PROFILE,
        )
    )
    location = categories.get("location") or {}
    if location:
        section.findings.append(
            Finding(
                f"Scored {location.get('score')}/100 — {location.get('detail', '')}",
                source=SOURCE_SCORING,
            )
        )
    return section


def _evidence_quality(
    job: Job, match: ScoredMatch, evidence: DescriptionEvidence, categories: Categories
) -> Section:
    section = Section("evidence_quality", "How good the evidence is")
    section.findings.append(
        Finding(
            f"Confidence {match.confidence}, with "
            f"{match.evidence_coverage * 100:.0f}% of the scoring weight assessable.",
            source=SOURCE_SCORING,
        )
    )
    for reason in match.confidence_reasons:
        section.findings.append(Finding(reason, source=SOURCE_SCORING))
    if job.description:
        section.findings.append(
            Finding(
                f"The description is {evidence.word_count} words and "
                + (
                    "publishes a requirements section."
                    if evidence.has_requirements_section
                    else "publishes no requirements section, so skills had to be inferred "
                    "from its prose."
                ),
                source=SOURCE_LISTING,
            )
        )
    else:
        section.findings.append(
            Finding("The source supplied no description at all.", source=SOURCE_LISTING)
        )
    unassessable = [name for name, data in categories.items() if not data.get("assessable", True)]
    if unassessable:
        section.findings.append(
            Finding(
                "Could not be judged from this listing, so excluded from the weighting: "
                + ", ".join(unassessable),
                source=SOURCE_SCORING,
            )
        )
    if job.posted_at is None:
        section.findings.append(
            Finding(
                "The source gave no posting date. Discovery time is never used as a "
                "substitute, so freshness is excluded.",
                source=SOURCE_LISTING,
            )
        )
    return section


def _resume_relevance(profile: CandidateProfile, skills: list[SkillFinding]) -> Section:
    section = Section(
        "resume_relevance",
        "Your own experience that applies",
        empty_note="No project or skill in your profile overlaps what this listing names.",
    )
    wanted = {
        finding.skill for finding in skills if finding.status in (STATUS_IN_PROFILE, STATUS_RELATED)
    }
    if not wanted:
        return section
    for entry in profile.projects:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        blob = " ".join(
            str(entry.get(key) or "") for key in ("name", "description", "technologies")
        )
        if isinstance(entry.get("technologies"), list):
            blob += " " + " ".join(str(item) for item in entry["technologies"])
        present = {
            skill
            for skill in wanted
            if canonical_skill(skill) and skill in canonical_skills(blob.replace(",", " ").split())
        }
        if name and present:
            section.findings.append(
                Finding(
                    f"Your project '{name}' records: {', '.join(sorted(present))}.",
                    source=SOURCE_PROFILE,
                )
            )
    matched = sorted(finding.skill for finding in skills if finding.status == STATUS_IN_PROFILE)
    if matched:
        section.findings.append(
            Finding(
                "Skills your profile already records for this listing: " + ", ".join(matched),
                source=SOURCE_PROFILE,
            )
        )
    return section


def _downgrades(match: ScoredMatch, categories: Categories) -> Section:
    section = Section(
        "downgrades",
        "Why anything was held back",
        empty_note="Nothing was capped, demoted or filtered for this job.",
    )
    for reason in match.filter_reasons:
        section.findings.append(
            Finding(f"Excluded by your filters: {reason}", source=SOURCE_SCORING)
        )
    for name, data in categories.items():
        detail = str(data.get("detail") or "")
        if "capped at" in detail or "shares only the generic" in detail or " role, which" in detail:
            section.findings.append(Finding(f"{name} was capped — {detail}", source=SOURCE_SCORING))
    if match.band == "review" and match.total_score >= 80:
        section.findings.append(
            Finding(
                f"Scored {match.total_score:g}, which is in the high range, but the band was "
                "held at 'worth a look' because the evidence was too thin to be confident. "
                "The number itself was not changed.",
                source=SOURCE_SCORING,
            )
        )
    if match.uncertain_requirements:
        section.findings.append(
            Finding(
                "The listing published no requirements list, so these were inferred and are "
                "shown as uncertain: " + ", ".join(match.uncertain_requirements),
                source=SOURCE_SCORING,
            )
        )
    return section


def build_explanation(job: Job, profile: CandidateProfile, match: ScoredMatch) -> JobExplanation:
    """Group an already-computed match into grounded, quotable sections."""
    evidence = analyse_description(job.description or "")
    categories: Categories = match.category_scores
    skills = _skill_findings(job, profile, evidence)
    sections = [
        _strong_matches(job, match, skills, categories),
        _missing_requirements(skills),
        _experience_fit(job, profile, evidence, categories),
        _location_fit(job, profile, categories),
        _evidence_quality(job, match, evidence, categories),
        _resume_relevance(profile, skills),
        _downgrades(match, categories),
    ]
    return JobExplanation(job_id=job.id, sections=sections, skills=skills)
