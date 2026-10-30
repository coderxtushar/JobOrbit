"""Application questions.

Two jobs live here: deciding *which* questions an application needs, and deciding whether
the profile actually contains a verified answer.

The deny-list in :data:`SENSITIVE_KEYS` is the mechanism that keeps generated content
truthful. A question on that list can only ever be answered from a verified profile field
or by the user typing it. No generator may fill one, so the application preview cannot
present a fabricated statement about salary, authorization, notice period, experience,
education or a legal declaration.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.db.models import AnswerProvenance, CandidateProfile, Job


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    key: str
    question: str
    sensitive: bool
    profile_field: str = ""
    formatter: Callable[[CandidateProfile], str | None] | None = None
    help_text: str = ""


def _salary(profile: CandidateProfile) -> str | None:
    low, high = profile.salary_expectation_min, profile.salary_expectation_max
    if low is None and high is None:
        return None
    currency = profile.salary_currency or "INR"
    if low is not None and high is not None:
        return f"{currency} {low:,} - {high:,} per annum"
    value = low if low is not None else high
    return f"{currency} {value:,} per annum"


def _notice(profile: CandidateProfile) -> str | None:
    days = profile.notice_period_days
    if days is None:
        return None
    if days == 0:
        return "Immediately available"
    return f"{days} days"


def _experience(profile: CandidateProfile) -> str | None:
    years = profile.years_experience
    if years is None:
        return None
    if years == 0:
        return "0 years (fresher)"
    return f"{years:g} years"


def _sponsorship(profile: CandidateProfile) -> str | None:
    if profile.requires_sponsorship is None:
        return None
    return "Yes" if profile.requires_sponsorship else "No"


def _relocation(profile: CandidateProfile) -> str | None:
    if profile.open_to_relocation is None:
        return None
    return "Yes" if profile.open_to_relocation else "No"


def _locations(profile: CandidateProfile) -> str | None:
    return ", ".join(profile.preferred_locations) or None


def _education(profile: CandidateProfile) -> str | None:
    entries = [entry for entry in profile.education if isinstance(entry, dict)]
    if not entries:
        return None
    parts = []
    for entry in entries[:3]:
        degree = str(entry.get("degree", "")).strip()
        institution = str(entry.get("institution", "")).strip()
        year = str(entry.get("end_year", "")).strip()
        piece = " ".join(
            filter(
                None,
                [degree, f"- {institution}" if institution else "", f"({year})" if year else ""],
            )
        )
        if piece.strip():
            parts.append(piece.strip())
    return "; ".join(parts) or None


STANDARD_QUESTIONS: tuple[QuestionSpec, ...] = (
    QuestionSpec("full_name", "Full name", False, "full_name"),
    QuestionSpec("email", "Email address", False, "email"),
    QuestionSpec("phone", "Phone number", False, "phone"),
    QuestionSpec(
        "years_experience",
        "How many years of relevant experience do you have?",
        True,
        formatter=_experience,
        help_text="Taken from your profile. Edit the profile rather than this answer.",
    ),
    QuestionSpec(
        "work_authorization",
        "Are you legally authorised to work in the job's country?",
        True,
        formatter=lambda profile: profile.work_authorization or None,
        help_text="A legal declaration. It is never drafted for you.",
    ),
    QuestionSpec(
        "requires_sponsorship",
        "Will you now or in the future require visa sponsorship?",
        True,
        formatter=_sponsorship,
        help_text="A legal declaration. It is never drafted for you.",
    ),
    QuestionSpec(
        "salary_expectation",
        "What is your expected salary?",
        True,
        formatter=_salary,
        help_text="Only shown if you recorded an expectation in your profile.",
    ),
    QuestionSpec("notice_period", "What is your notice period?", True, formatter=_notice),
    QuestionSpec(
        "graduation_date",
        "What is your graduation date?",
        True,
        formatter=lambda profile: profile.graduation_date or None,
    ),
    QuestionSpec("education", "Highest education qualification", True, formatter=_education),
    QuestionSpec("relocation", "Are you willing to relocate?", True, formatter=_relocation),
    QuestionSpec("preferred_locations", "Preferred work locations", False, formatter=_locations),
    QuestionSpec(
        "links",
        "Portfolio, GitHub or LinkedIn links",
        False,
        formatter=lambda profile: ", ".join(profile.links) or None,
    ),
)

SENSITIVE_KEYS: frozenset[str] = frozenset(
    spec.key for spec in STANDARD_QUESTIONS if spec.sensitive
) | frozenset(
    {
        "criminal_record",
        "disability",
        "gender",
        "ethnicity",
        "veteran_status",
        "date_of_birth",
        "age",
        "marital_status",
        "references",
        "current_salary",
        "notice_period",
        "background_check",
        "drug_test",
    }
)

_SENSITIVE_PHRASES: tuple[tuple[str, str], ...] = (
    (
        r"\b(visa|sponsorship|work permit|h-?1b|authori[sz]ed to work|right to work)\b",
        "work_authorization",
    ),
    (r"\b(current|expected)\s+(ctc|salary|compensation)\b", "salary_expectation"),
    (r"\bnotice period\b", "notice_period"),
    (r"\b(years?|yrs?)\s+of\s+experience\b", "years_experience"),
    (r"\b(criminal|conviction|felony|background check)\b", "criminal_record"),
    (r"\b(disab(?:led|ility)|accommodation)\b", "disability"),
    (r"\b(gender|sex|ethnicit|race|veteran|caste)\b", "ethnicity"),
    (r"\b(date of birth|dob|how old are you|your age)\b", "date_of_birth"),
    (r"\b(graduat(?:ion|e)\s+(?:date|year)|passing year|batch)\b", "graduation_date"),
    (r"\b(reference|referee)s?\b", "references"),
    (r"\b(relocat)\w*\b", "relocation"),
    (r"\b(certif(?:ication|icate))s?\b", "certifications"),
    (r"\b(degree|qualification|highest education)\b", "education"),
    (r"\b(drug|medical)\s+test\b", "drug_test"),
    (r"\b(declare|declaration|certify|consent|agree to the terms)\b", "legal_declaration"),
)

_QUESTION_LINE = re.compile(
    r"^\s*(?:[-*\u2022\d.)\s]*)((?:why|what|how|when|where|which|are|do|did|have|can|will|would|describe|tell|explain|rate|list)\b[^?\n]{8,200}\?)",
    re.IGNORECASE | re.MULTILINE,
)


def classify_question(question: str) -> tuple[str, bool]:
    """Return (question_key, is_sensitive) for a free-text question."""
    text = question.lower()
    for pattern, key in _SENSITIVE_PHRASES:
        if re.search(pattern, text):
            return key, key in SENSITIVE_KEYS or key == "legal_declaration"
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:60]
    return normalized or "freeform", False


def extract_questions_from_description(description: str, limit: int = 15) -> list[str]:
    """Pull explicit questions out of a job description.

    The description is untrusted input, so matches are length-capped and only the question
    text itself is kept; nothing from the description is ever executed or interpreted.
    """
    if not description:
        return []
    found: list[str] = []
    for match in _QUESTION_LINE.finditer(description):
        question = " ".join(match.group(1).split())
        if question.lower() not in {item.lower() for item in found}:
            found.append(question)
        if len(found) >= limit:
            break
    return found


@dataclass(slots=True)
class PreparedAnswer:
    question: str
    question_key: str
    answer: str
    provenance: AnswerProvenance
    is_sensitive: bool
    requires_user_input: bool
    flag_reason: str
    source_field: str


def answer_from_profile(spec: QuestionSpec, profile: CandidateProfile) -> PreparedAnswer:
    """Resolve one standard question against the profile, flagging it when unknown."""
    value: str | None
    if spec.formatter is not None:
        value = spec.formatter(profile)
    else:
        raw = getattr(profile, spec.profile_field, None) if spec.profile_field else None
        value = str(raw).strip() if raw not in (None, "") else None

    if value:
        return PreparedAnswer(
            question=spec.question,
            question_key=spec.key,
            answer=value,
            provenance=AnswerProvenance.PROFILE_VERIFIED,
            is_sensitive=spec.sensitive,
            requires_user_input=False,
            flag_reason="",
            source_field=spec.profile_field or spec.key,
        )

    reason = f"Your profile has no verified value for '{spec.key}'. " + (
        spec.help_text or "Enter it yourself; it will not be drafted for you."
    )
    return PreparedAnswer(
        question=spec.question,
        question_key=spec.key,
        answer="",
        provenance=AnswerProvenance.NEEDS_USER_INPUT,
        is_sensitive=spec.sensitive,
        requires_user_input=True,
        flag_reason=reason,
        source_field=spec.profile_field or spec.key,
    )


def build_question_set(
    job: Job, profile: CandidateProfile, extra_questions: list[str] | None = None
) -> list[PreparedAnswer]:
    """Assemble every answer for an application, with provenance on each one."""
    answers = [answer_from_profile(spec, profile) for spec in STANDARD_QUESTIONS]
    seen_keys = {answer.question_key for answer in answers}

    discovered = extract_questions_from_description(job.description)
    for question in discovered + list(extra_questions or []):
        key, sensitive = classify_question(question)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        answers.append(
            PreparedAnswer(
                question=question,
                question_key=key,
                answer="",
                provenance=AnswerProvenance.NEEDS_USER_INPUT,
                is_sensitive=sensitive,
                requires_user_input=True,
                flag_reason=(
                    "This question was found in the listing and has no verified answer in "
                    "your profile."
                    + (
                        " It is sensitive or legal in nature, so it is never drafted for you."
                        if sensitive
                        else " Answer it yourself, or ask for an AI draft and then review it."
                    )
                ),
                source_field="",
            )
        )
    return answers


def to_dict(answer: PreparedAnswer) -> dict[str, Any]:
    return {
        "question": answer.question,
        "question_key": answer.question_key,
        "answer": answer.answer,
        "provenance": answer.provenance,
        "is_sensitive": answer.is_sensitive,
        "requires_user_input": answer.requires_user_input,
        "flag_reason": answer.flag_reason,
        "source_field": answer.source_field,
    }
