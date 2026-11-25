"""Turn the label of a live form field into an answer-bank key.

Every field a browser adapter reads off an employer's form is classified here. The key
decides which stored answer fills the field, so the ordering of the rules below is the
whole point of this module:

* **Technology-specific experience before total experience.** "Years of experience with
  Java" must never be answered with the candidate's total experience. A label naming a
  technology gets its own ``years:<tech>`` key, answered once per technology.
* **Every consent or declaration is keyed by its exact wording.** Agreeing to one
  employer's background-check text is not agreement to another's, so a declaration is
  never filled from a generic "I agree".
* **Equal-opportunity questions are separated.** Gender, ethnicity, veteran status and
  disability are different questions; one answer must not leak into another.
* **Anything unrecognised gets a key derived from its own wording**, so the user answers it
  once in the Action inbox and the same question on a later form is filled from that.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.questions import SENSITIVE_KEYS, classify_question

#: Longest key the database column holds, with room to spare.
_MAX_KEY = 96


@dataclass(frozen=True, slots=True)
class LabelClass:
    """The answer-bank key for a form label, and whether it carries legal weight."""

    key: str
    sensitive: bool = False
    #: True when the value comes straight from the candidate's identity (name, email,
    #: phone, links) rather than from an answered question.
    identity: bool = False


def slugify(text: str, *, limit: int = 60) -> str:
    """A stable, readable slug with a short hash so near-identical labels stay distinct."""
    lowered = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    digest = hashlib.sha256(text.casefold().strip().encode("utf-8")).hexdigest()[:8]
    return f"{lowered[:limit].rstrip('-')}-{digest}" if lowered else digest


def _key(prefix: str, text: str) -> str:
    return f"{prefix}:{slugify(text)}"[:_MAX_KEY]


# Identity fields: filled from the profile, never asked. Checked in order; the first
# pattern that matches wins, so the narrow ones come first.
_IDENTITY: tuple[tuple[str, str], ...] = (
    (r"\bfirst\s*name\b|\bgiven\s*name\b", "first_name"),
    (r"\blast\s*name\b|\bsurname\b|\bfamily\s*name\b", "last_name"),
    (r"\b(preferred|nick)\s*name\b", "preferred_name"),
    (r"^\s*(full\s*)?name\s*$|\bfull\s*name\b|\byour\s*name\b|\blegal\s*name\b", "full_name"),
    (r"\be-?mail\b", "email"),
    (r"\b(phone|mobile|contact\s*number|whatsapp)\b", "phone"),
    (r"\blinked\s*in\b", "linkedin"),
    (r"\bgit\s*hub\b", "github"),
    (r"\b(portfolio|personal\s*(web)?site|website|blog)\b", "portfolio"),
    (r"\btwitter\b|\bx\.com\b", "twitter"),
)

#: Fields that are about the candidate but are not in the profile. Answered once.
_ABOUT_ME: tuple[tuple[str, str], ...] = (
    (
        r"\b(current|present|most\s+recent|latest|last)\s*(company|employer|organi[sz]ation)\b|^\s*org\s*$",
        "current_company",
    ),
    (r"\b(current|present)\s*(title|designation|role|position)\b", "current_title"),
    (r"\bcountry\b", "country"),
    (
        r"\b(current\s*)?(location|city)\b|\bwhere\s+are\s+you\s+(currently\s+|now\s+)?(based|located)\b",
        "current_location",
    ),
    (r"\bhow\s+did\s+you\s+(hear|find|learn)\b|\breferral\s*source\b|\bsource\b", "heard_about_us"),
    (r"\bpronouns?\b", "pronouns"),
)

_EEO: tuple[tuple[str, str], ...] = (
    (r"\bgender\b|\bsex\b", "gender"),
    (r"\b(race|ethnic\w*|hispanic|latino)\b", "ethnicity"),
    (r"\bveteran\b", "veteran_status"),
    (r"\bdisab\w*\b", "disability"),
)

_YES_NO_QUESTION = re.compile(
    r"^\s*(are|do|does|did|have|has|had|will|would|can|could|is|was|were|should)\b",
    re.IGNORECASE,
)

_CONSENT = re.compile(
    r"\b(i\s+(agree|consent|confirm|acknowledge|certify|understand|accept)|consent|"
    r"agree\s+to|terms\s*(and|&)\s*conditions|privacy\s*(policy|notice)|declar\w*|"
    r"background\s*(check|verification)|bgv|attest|"
    # Signing something: "indicate your agreement by typing your full name", an NDA, an
    # e-signature. A name typed here is a signature, so it is never filled from the
    # profile; only the user's own answer to that exact text is used.
    r"(indicate|confirm|signal)\s+your\s+(agreement|acceptance|consent)|"
    r"nda|non[-\s]?disclosure|(electronic|digital|e[-\s]?)\s*signature|"
    r"sign\s+(here|below|this))\b",
    re.IGNORECASE,
)

_YEARS = re.compile(r"\b(years?|yrs?)\b.*\bexperience\b|\bexperience\b.*\b(years?|yrs?)\b", re.I)
#: "with/in/using/of <technology>" after the experience phrase marks a per-skill question.
_YEARS_WITH = re.compile(
    r"\bexperience\b[^?]*?\b(?:with|in|using|on|working\s+with|of\s+working\s+with)\s+"
    r"(?:the\s+)?([a-z0-9+#./ -]{1,40}?)(?:\s*(?:\?|\(|,|:|$))",
    re.IGNORECASE,
)
_GENERIC_EXPERIENCE_WORDS = {
    "total",
    "relevant",
    "professional",
    "work",
    "industry",
    "overall",
    "full-time",
    "full time",
    "the industry",
    "a similar role",
    "similar roles",
}

#: Keys :func:`classify_question` returns when one of its phrases matched, as opposed to its
#: fallback of slugging the whole question. Questions handled above (sponsorship, salary,
#: experience, equal-opportunity, declarations) are deliberately absent.
_STANDARD_MATCHES: frozenset[str] = frozenset(
    {
        "notice_period",
        "criminal_record",
        "date_of_birth",
        "graduation_date",
        "references",
        "relocation",
        "certifications",
        "education",
        "drug_test",
    }
)

_RESUME = re.compile(r"\b(resume|résumé|cv|curriculum)\b", re.I)
_COVER = re.compile(r"\bcover\s*letter\b", re.I)


def classify_label(label: str, *, company: str = "", long_answer: bool = False) -> LabelClass:
    """Return the answer-bank key for one form label.

    ``long_answer`` marks a textarea. A free-text essay ("Why do you want to work
    here?") is keyed per company, because the answer to it names the company.
    """
    text = re.sub(r"\s+", " ", label or "").strip()
    lowered = text.casefold().rstrip("*✱ ").strip()
    if not lowered:
        return LabelClass(key="")

    if _COVER.search(lowered):
        return LabelClass(key="cover_letter")
    if _RESUME.search(lowered) and len(lowered) < 60:
        return LabelClass(key="resume")

    # Consent before anything else: a declaration mentioning "experience" or "location"
    # is still a declaration, and is keyed by its exact words.
    if _CONSENT.search(lowered):
        return LabelClass(key=_key("consent", text), sensitive=True)

    for pattern, key in _EEO:
        if re.search(pattern, lowered):
            return LabelClass(key=key, sensitive=True)

    if _YEARS.search(lowered):
        match = _YEARS_WITH.search(lowered)
        if match:
            tech = match.group(1).strip(" .-")
            if tech and tech not in _GENERIC_EXPERIENCE_WORDS:
                return LabelClass(key=_key("years", tech), sensitive=True)
        return LabelClass(key="years_experience", sensitive=True)

    # Sponsorship and work authorization are opposite questions. The shared question
    # classifier files both under one key, which would answer "Will you need visa
    # sponsorship?" with "Yes, authorised to work" — so they are separated here first.
    if re.search(r"\bsponsor\w*\b", lowered):
        return LabelClass(key="requires_sponsorship", sensitive=True)
    if re.search(
        r"\b(authori[sz]ed|eligible|legally\s+able|right)\s+to\s+work\b|\bwork\s+(permit|authori[sz]ation)\b",
        lowered,
    ):
        return LabelClass(key="work_authorization", sensitive=True)
    if re.search(r"\b(current|present|last\s+drawn)\b.*\b(ctc|salary|compensation|pay)\b", lowered):
        return LabelClass(key="current_salary", sensitive=True)
    if re.search(r"\b(expected|desired|expectations?)\b", lowered) and re.search(
        r"\b(ctc|salary|compensation|pay|package)\b", lowered
    ):
        return LabelClass(key="salary_expectation", sensitive=True)

    standard_key, _ = classify_question(lowered)
    if standard_key in _STANDARD_MATCHES:
        return LabelClass(key=standard_key, sensitive=standard_key in SENSITIVE_KEYS)

    for pattern, key in _IDENTITY:
        if re.search(pattern, lowered):
            return LabelClass(key=key, identity=True)

    # "Are you subject to any agreements with your current employer?" mentions the current
    # employer but asks yes or no about something else. The about-me keys name a fact to
    # supply, so a yes/no question never maps to them.
    if not _YES_NO_QUESTION.match(lowered):
        for pattern, key in _ABOUT_ME:
            if re.search(pattern, lowered):
                return LabelClass(key=key)

    if long_answer:
        scope = slugify(company, limit=24) if company else "any"
        return LabelClass(key=f"essay:{scope}:{slugify(text, limit=40)}"[:_MAX_KEY])
    return LabelClass(key=_key("form", text))


def classify_choice(label: str, options: tuple[str, ...], *, company: str = "") -> LabelClass:
    """Classify a question that is answered by picking from ``options``.

    Two corrections on top of :func:`classify_label`, both found on live forms:

    * **Consent hiding in the choices.** Ashby asks "Phone" with the options "Yes - I
      consent to receiving SMS text messages" / "No - ...". The label says phone; the
      question is a consent, keyed by its exact wording like every other declaration.
    * **An identity label on a choice is not the identity value.** A required radio
      labelled "Phone" is never answered with a phone number.
    """
    base = classify_label(label, company=company)
    described = f"{label} | {' / '.join(options)}"
    if not base.key.startswith("consent:") and _CONSENT.search(" ".join(options).casefold()):
        return LabelClass(key=_key("consent", described), sensitive=True)
    if base.identity:
        return LabelClass(key=_key("form", described))
    return base


def option_key(base_key: str, options: tuple[str, ...]) -> str:
    """Key for a question asked with a fixed list of choices.

    The same notice-period question offered as "Immediate / 15 days / 30 days" on one form
    and as free text on another needs two stored answers: the free-text answer is not one
    of the choices. Keying the constrained version by its option set means the user picks
    a choice once per distinct list, and the free-text answer is left untouched.
    """
    joined = "|".join(option.casefold().strip() for option in options)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]
    return f"opt:{base_key}"[: _MAX_KEY - 11] + f":{digest}"


def link_for(key: str, links: tuple[str, ...]) -> str:
    """Pick the profile link that answers a LinkedIn / GitHub / portfolio field."""
    hosts = {
        "linkedin": "linkedin.com",
        "github": "github.com",
        "twitter": ("twitter.com", "x.com"),
    }
    if key in hosts:
        wanted = hosts[key]
        needles = wanted if isinstance(wanted, tuple) else (wanted,)
        for link in links:
            if any(needle in link.casefold() for needle in needles):
                return link
        return ""
    if key == "portfolio":
        for link in links:
            lowered = link.casefold()
            if not any(
                host in lowered
                for host in ("linkedin.com", "github.com", "twitter.com", "x.com", "leetcode.com")
            ):
                return link
    return ""


def split_name(full_name: str) -> tuple[str, str]:
    """First and last name from a full name, splitting on the first space only."""
    parts = full_name.strip().split(None, 1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def resolve_option(value: str, options: tuple[str, ...]) -> str | None:
    """The offered option a stored answer refers to, or ``None`` if it is not clear.

    Exact (case-insensitive) first. Otherwise one of two prefix rules, each accepted only
    when exactly **one** option qualifies:

    * the answer is the leading words of an option: "India" picks "India +91" from a
      phone-country list, but "Yes" picks nothing from "Yes, full time" / "Yes, part time";
    * an option is the leading word(s) of the answer: "No, but I can relocate" picks "No"
      from Yes / No. The user wrote the option and then explained it.

    Never fuzzier than that — no synonyms, no reading of negations — because the chosen
    option is what the employer reads.
    """
    wanted = value.strip().casefold()
    if not wanted:
        return None
    for option in options:
        if option.strip().casefold() == wanted:
            return option
    pattern = re.compile(rf"^{re.escape(wanted)}(?![a-z0-9])")
    matches = [option for option in options if pattern.match(option.strip().casefold())]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return None
    leading = [
        option
        for option in options
        if option.strip()
        and re.match(rf"^{re.escape(option.strip().casefold())}(?![a-z0-9])", wanted)
    ]
    return leading[0] if len(leading) == 1 else None


__all__ = [
    "LabelClass",
    "classify_choice",
    "classify_label",
    "link_for",
    "option_key",
    "resolve_option",
    "slugify",
    "split_name",
]
