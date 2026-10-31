"""What a job description actually says, as opposed to which words it contains.

The matcher used to treat a description as a bag of words: any known skill appearing
anywhere earned the same credit. Measured on the benchmark, that let a sales role score 50
on skills because Python and SQL were named as tools its customers use, and it let roles
demanding five to seven years rank in the high band because the bar was written in prose
rather than in a structured field.

This module reads the structure instead. A description is split into sections by its own
headings, and a skill is credited according to *where* it appears:

``REQUIRED``
    under a requirements, qualifications or must-have heading
``PREFERRED``
    under a nice-to-have, preferred or bonus heading
``INCIDENTAL``
    everywhere else - company blurb, benefits, a passing mention of a tool

Nothing here decides a score. It reports evidence, and :mod:`app.services.matching` decides
what that evidence is worth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

#: ``KNOWN_SKILL_VOCABULARY`` is shared with the normalizer on purpose, so inference during
#: scoring and inference during import cannot disagree about what counts as a skill.
from app.services.normalization import KNOWN_SKILL_VOCABULARY
from app.services.text import canonical_skill


class EvidenceClass(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    INCIDENTAL = "incidental"


#: Checked before the required cues, because "Preferred Qualifications" contains the word
#: "qualifications" and must not be read as a hard requirement.
_PREFERRED_CUES = (
    "nice to have",
    "nice-to-have",
    "preferred qualification",
    "preferred skill",
    "preferred experience",
    "bonus point",
    "bonus if",
    "good to have",
    "desirable",
    "plus if you",
    "it's a plus",
    "its a plus",
    "a plus:",
    "extra credit",
    "pluses",
    "would be great",
    "beneficial",
)

_REQUIRED_CUES = (
    "requirement",
    "required",
    "must have",
    "must-have",
    "qualification",
    "what you'll need",
    "what you will need",
    "what you need",
    "what we're looking for",
    "what we are looking for",
    "who you are",
    "you have",
    "you should have",
    "skills needed",
    "skills and experience",
    "essential",
    "eligibility",
    "minimum",
    "basic qualification",
    "technical skills",
    "we expect",
    "about you",
)

#: Headings that end a requirements block. Without these, a "Requirements" heading would
#: capture every skill named in the benefits and company sections that follow it.
_NEUTRAL_CUES = (
    "responsibilit",
    "what you'll do",
    "what you will do",
    "what you'll be doing",
    "day to day",
    "about us",
    "about the role",
    "about the team",
    "about the company",
    "who we are",
    "our culture",
    "benefit",
    "perks",
    "compensation",
    "salary",
    "why join",
    "how to apply",
    "equal opportunity",
    "equal employment",
    "diversity",
    "privacy",
    "interview process",
    "hiring process",
    "our mission",
    "the opportunity",
)

#: "5+ years", "5-8 years", "at least 3 years", "minimum of 2 years".
_YEARS = re.compile(
    r"(?:(?:at\s+least|minimum\s+of|min\.?|over)\s*)?"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*"
    r"(?:years?|yrs?)(?:\s*(?:of|\sof)?\s*(?:relevant\s+|professional\s+|hands[- ]on\s+)?"
    r"(?:experience|exp\b))?",
    re.IGNORECASE,
)

#: Phrases that mean the listing is explicitly open to someone with no track record. They
#: override a years figure, because "0-2 years" and "freshers welcome" both appear in
#: listings that also mention "3 years" somewhere in boilerplate.
_FRESHER_CUES = (
    "fresher",
    "freshers welcome",
    "new grad",
    "new graduate",
    "recent graduate",
    "entry level",
    "entry-level",
    "no prior experience",
    "no experience required",
    "0-1 year",
    "0-2 year",
    "internship",
    "intern programme",
    "intern program",
)

#: A description shorter than this cannot support a confident judgement. Remote OK returns
#: a truncated teaser and SmartRecruiters sometimes returns nothing at all, so this is a
#: real condition rather than a theoretical one.
SPARSE_DESCRIPTION_WORDS = 60


@dataclass(slots=True)
class DescriptionEvidence:
    """Where each skill was found, and what the prose says about the experience bar."""

    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    incidental: list[str] = field(default_factory=list)
    has_requirements_section: bool = False
    word_count: int = 0
    stated_min_years: float | None = None
    mentions_fresher_opening: bool = False

    @property
    def is_sparse(self) -> bool:
        return self.word_count < SPARSE_DESCRIPTION_WORDS

    def classify(self, skill: str) -> EvidenceClass:
        if skill in self.required:
            return EvidenceClass.REQUIRED
        if skill in self.preferred:
            return EvidenceClass.PREFERRED
        return EvidenceClass.INCIDENTAL


def _section_for(line: str, current: EvidenceClass) -> EvidenceClass:
    lowered = line.lower()
    if any(cue in lowered for cue in _PREFERRED_CUES):
        return EvidenceClass.PREFERRED
    if any(cue in lowered for cue in _REQUIRED_CUES):
        return EvidenceClass.REQUIRED
    if any(cue in lowered for cue in _NEUTRAL_CUES):
        return EvidenceClass.INCIDENTAL
    return current


def _skills_in(text: str) -> list[str]:
    haystack = f" {re.sub(r'[^a-z0-9+#. ]+', ' ', text.lower())} "
    return [skill for skill in KNOWN_SKILL_VOCABULARY if f" {skill} " in haystack]


def _stated_min_years(description: str) -> float | None:
    """The smallest experience bar the prose states, or ``None`` if it states none.

    The *smallest* figure is taken deliberately: a listing saying "3+ years required, 5+
    years preferred" has a bar of three, and reading the larger number would reject a
    candidate the employer would consider.
    """
    found: list[float] = []
    for match in _YEARS.finditer(description):
        low = match.group(1)
        if low is None:
            continue
        try:
            value = float(low)
        except ValueError:
            continue
        if 0 <= value <= 40:
            found.append(value)
    return min(found) if found else None


def analyse_description(description: str) -> DescriptionEvidence:
    """Split a description into sections and record where each skill appears."""
    evidence = DescriptionEvidence()
    if not description or not description.strip():
        return evidence

    evidence.word_count = len(description.split())
    lowered = description.lower()
    evidence.mentions_fresher_opening = any(cue in lowered for cue in _FRESHER_CUES)
    evidence.stated_min_years = _stated_min_years(description)

    buckets: dict[EvidenceClass, dict[str, None]] = {
        EvidenceClass.REQUIRED: {},
        EvidenceClass.PREFERRED: {},
        EvidenceClass.INCIDENTAL: {},
    }
    current = EvidenceClass.INCIDENTAL
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        current = _section_for(line, current)
        if current is EvidenceClass.REQUIRED:
            evidence.has_requirements_section = True
        for skill in _skills_in(line):
            buckets[current].setdefault(skill, None)

    required = list(buckets[EvidenceClass.REQUIRED])
    preferred = [skill for skill in buckets[EvidenceClass.PREFERRED] if skill not in required]
    stronger = set(required) | set(preferred)
    incidental = [skill for skill in buckets[EvidenceClass.INCIDENTAL] if skill not in stronger]

    evidence.required = [canonical_skill(skill) or skill for skill in required]
    evidence.preferred = [canonical_skill(skill) or skill for skill in preferred]
    evidence.incidental = [canonical_skill(skill) or skill for skill in incidental]
    return evidence


#: Role families outside software engineering. A title carrying one of these markers is a
#: different job from the ones this candidate is looking for, however many generic words it
#: shares. Measured on the benchmark, this is what separated "Sales Engineer", "Field
#: Engineer" and "AI Agent Support Specialist" from the roles they superficially resembled.
#: Software-adjacent specialisations (backend, frontend, data, ML, platform, SRE) are
#: deliberately absent: penalising those would punish genuine adjacency.
FOREIGN_ROLE_FAMILIES: dict[str, frozenset[str]] = {
    "support": frozenset({"support", "helpdesk", "servicedesk", "troubleshooting", "deskside"}),
    "sales": frozenset({"sales", "account", "revenue", "quota", "prospecting", "presales", "demo"}),
    "customer_success": frozenset({"renewals", "onboarding", "success"}),
    "marketing": frozenset({"marketing", "brand", "seo", "content", "copywriter", "growth"}),
    "people": frozenset(
        {"recruiting", "recruiter", "talent", "hr", "people", "rewards", "payroll"}
    ),
    "finance": frozenset(
        {"finance", "financial", "accounting", "accountant", "audit", "treasury", "tax", "credit"}
    ),
    "legal": frozenset({"legal", "counsel", "paralegal", "compliance"}),
    "design": frozenset({"designer", "ux", "ui", "graphic", "illustrator"}),
    "product": frozenset({"product"}),
    "hardware": frozenset(
        {
            "pcb",
            "asic",
            "soc",
            "semiconductor",
            "electronics",
            "electrical",
            "mechanical",
            "hardware",
            "circuit",
            "automotive",
            "vehicle",
            "thermal",
            "radar",
            "ultrasonic",
            "signal",
            "acoustic",
            "audio",
            "rf",
            "bms",
            "pump",
            "pumps",
            "hvac",
            "refrigeration",
        }
    ),
    "field": frozenset({"field", "implementation", "installation", "deployment"}),
    "operations": frozenset(
        {
            "logistics",
            "warehouse",
            "procurement",
            "manufacturing",
            "shift",
            # "Cost Engineering & Benchmarking" is industrial engineering. Measured on a live
            # India discovery run, it and "Application Engineer - Heat Pumps" both reached the
            # review band at 74-76 because a large engineering employer's titles share the
            # generic role noun. "operations" itself is deliberately absent: DevOps and
            # platform-operations roles are software work.
            "cost",
            "benchmarking",
        }
    ),
    "clinical": frozenset({"nurse", "nursing", "clinical", "medical", "pharmacy"}),
    "education": frozenset({"teacher", "tutor", "lecturer", "faculty", "instructor"}),
}
