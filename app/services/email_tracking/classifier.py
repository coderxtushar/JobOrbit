"""Rule-based classification of job-related email.

Deterministic on purpose. A classifier whose output feeds suggested status changes has to
be explainable ("matched 'move forward with other candidates'") and reproducible in a test,
and the phrasing applicant-tracking systems use is formulaic enough that weighted phrases
do well. Each rule adds a weight to one category; the decision then applies a precedence:

* A strong rejection wins over everything, because a rejection almost always quotes the
  application it rejects ("Thank you for applying ... unfortunately ..."), and treating it
  as a confirmation would tell the user good news that is false.
* Offer, interview and assessment come next, each needing a strong signal.
* A weak rejection ("unfortunately", "after careful consideration") still beats a plain
  confirmation, for the same reason as the first rule.
* Then confirmation, process update, recruiter outreach, and finally a generic
  "other_job_related" for mail from a hiring system that matched nothing specific.

Job-alert digests ("10 new jobs for you") are *not* responses to an application, so they
are classified ``not_job_related`` for tracking purposes; :mod:`app.sources.email_alerts`
handles them as a discovery source instead.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from app.services.text import collapse_whitespace

APPLICATION_CONFIRMATION = "application_confirmation"
REJECTION = "rejection"
INTERVIEW_INVITATION = "interview_invitation"
RECRUITER_MESSAGE = "recruiter_message"
ASSESSMENT_INVITATION = "assessment_invitation"
PROCESS_UPDATE = "process_update"
OFFER = "offer"
OTHER_JOB_RELATED = "other_job_related"
NOT_JOB_RELATED = "not_job_related"

CATEGORIES: tuple[str, ...] = (
    APPLICATION_CONFIRMATION,
    REJECTION,
    INTERVIEW_INVITATION,
    RECRUITER_MESSAGE,
    ASSESSMENT_INVITATION,
    PROCESS_UPDATE,
    OFFER,
    OTHER_JOB_RELATED,
    NOT_JOB_RELATED,
)

#: Mail domains of applicant-tracking systems. Mail from one of these is about hiring.
ATS_SENDER_DOMAINS: tuple[str, ...] = (
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "hire.lever.co",
    "ashbyhq.com",
    "myworkday.com",
    "workday.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
    "workablemail.com",
    "workable.com",
    "taleo.net",
    "successfactors.com",
    "bamboohr.com",
    "recruitee.com",
    "breezy.hr",
    "teamtailor.com",
    "personio.de",
    "rippling.com",
    "freshteam.com",
    "zohorecruit.com",
)

#: Online-assessment vendors. A link to, or mail from, one of these is an assessment.
ASSESSMENT_DOMAINS: tuple[str, ...] = (
    "hackerrank.com",
    "codility.com",
    "hackerearth.com",
    "codesignal.com",
    "testgorilla.com",
    "mettl.com",
    "imocha.io",
    "coderbyte.com",
    "hirevue.com",
    "karat.io",
    "codeinterview.io",
    "devskiller.com",
    "glider.ai",
)

STRONG = 3.0


class Classification(NamedTuple):
    category: str
    confidence: float
    reasons: list[str]

    @property
    def is_job_related(self) -> bool:
        return self.category != NOT_JOB_RELATED


_Rule = tuple[re.Pattern[str], float, str]


def _rules(*entries: tuple[str, float, str]) -> tuple[_Rule, ...]:
    return tuple(
        (re.compile(pattern, re.IGNORECASE), weight, label) for pattern, weight, label in entries
    )


_REJECTION = _rules(
    (
        r"move forward with (?:other|another|different) (?:candidates?|applicants?)",
        3.5,
        "move forward with other candidates",
    ),
    (
        r"(?:decided|chosen|elected|opted) to (?:move forward|proceed|continue|go|pursue) with (?:other|another|a different)",
        3.5,
        "decided to proceed with other candidates",
    ),
    (r"pursue other (?:candidates|applicants)", 3.5, "pursue other candidates"),
    (
        r"(?:not|won't|will not|unable to|cannot|can't|not able to) (?:be )?(?:mov|progress|proceed|advanc|tak)\w* (?:forward|further|ahead)",
        3.5,
        "not moving forward",
    ),
    (r"decided not to (?:proceed|move|progress|advance|continue)", 3.5, "decided not to proceed"),
    (
        r"(?:not|won't|will not) be (?:moving|proceeding|progressing|advancing|continuing)",
        3.5,
        "will not be progressing",
    ),
    (
        r"(?:have|has|were|was) not (?:been )?(?:selected|shortlisted|successful)",
        3.5,
        "not selected",
    ),
    (
        r"no longer (?:being )?(?:considered|under consideration|in consideration)",
        3.5,
        "no longer under consideration",
    ),
    (r"regret to (?:inform|let you know|advise)", 3.0, "regret to inform"),
    (
        r"position has (?:now )?been filled|role has (?:now )?been filled",
        3.0,
        "position has been filled",
    ),
    (
        r"(?:candidates|applicants) whose (?:experience|qualifications|skills|background)",
        2.5,
        "other candidates whose experience",
    ),
    (r"\bunsuccessful\b", 2.5, "unsuccessful"),
    (r"not (?:a|the right) (?:fit|match) (?:for|at this)", 2.5, "not the right fit"),
    (r"after careful (?:consideration|review)", 1.5, "after careful consideration"),
    (
        r"(?:keep|retain) your (?:resume|cv|details|profile|information) on file",
        1.0,
        "keep your details on file",
    ),
    (
        r"wish you (?:the best|all the best|every success|luck|success) (?:of luck )?(?:in|with) your",
        1.0,
        "wishing you luck in your search",
    ),
)
#: ``unfortunately`` is the single most common rejection word, but it also appears in
#: confirmations ("unfortunately we cannot reply to every applicant"), so it only counts
#: when the same sentence is not one of those disclaimers.
_UNFORTUNATELY = re.compile(r"\bunfortunately\b[^.!?\n]*", re.IGNORECASE)
_DISCLAIMER = re.compile(
    r"volume|respond to (?:every|each|all)|reply to (?:every|each|all)|individual(?:ly)? "
    r"(?:feedback|response)|unable to (?:respond|reply)|resched",
    re.IGNORECASE,
)

_OFFER = _rules(
    (r"\boffer letter\b", 3.5, "offer letter"),
    (
        r"(?:pleased|delighted|happy|excited|thrilled) to (?:formally )?(?:offer you(?! (?:an? |the )?(?:interview|chance|opportunity|slot))|extend (?:you )?(?:an|the|this) offer)",
        4.0,
        "pleased to offer you",
    ),
    (
        r"extend (?:you )?(?:an|a formal|a written|the) (?:formal |written )?offer",
        3.5,
        "extend an offer",
    ),
    (r"offer of employment|employment offer", 3.5, "offer of employment"),
    (r"\bjob offer\b|\byour offer\b", 2.0, "job offer"),
    (
        r"accept (?:the|this|our) offer|offer (?:acceptance|expires|deadline)",
        2.0,
        "accept the offer",
    ),
    (r"compensation package|joining bonus|\bctc\b|date of joining", 1.0, "compensation details"),
)

_INTERVIEW = _rules(
    (
        r"schedul\w* (?:an?|your|the|a quick|a short) (?:\w+ )?(?:interview|onsite)",
        3.5,
        "schedule an interview",
    ),
    (
        r"invit\w* you (?:to|for) (?:an?|the|our)? ?(?:\w+ )?(?:interview|onsite)",
        3.5,
        "invitation to interview",
    ),
    (
        r"(?:schedul\w*|set up|arrange) (?:an?|a quick|a short|some time for a) (?:\w+ )?(?:call|chat|conversation)",
        2.0,
        "schedule a call",
    ),
    (
        r"interview invitation|invitation to interview|interview request",
        3.5,
        "interview invitation",
    ),
    (
        r"(?:like|love|want) to (?:speak|talk|chat|meet) with you",
        2.5,
        "would like to speak with you",
    ),
    (
        r"\b(?:phone|technical|video|first|second|final|hr|recruiter|onsite|on-site) (?:screen|interview|round)\b",
        2.5,
        "named interview round",
    ),
    (
        r"your availability|share (?:a few|some) (?:time ?slots|times)|select a (?:time|slot)|book a (?:time|slot)",
        2.0,
        "asks for availability",
    ),
    (r"calendly\.com|cal\.com/|goodtime\.io|calendar invite", 2.0, "scheduling link"),
    (
        r"next (?:round|stage|step)s? (?:of|in) (?:the|our) (?:interview|hiring|recruitment) process",
        2.0,
        "next interview round",
    ),
    (
        r"zoom\.us/j/|meet\.google\.com/|teams\.microsoft\.com/l/meetup-join|webex\.com/",
        1.5,
        "meeting link",
    ),
    (r"\binterview(?:s|ing|ed)?\b", 0.5, "mentions an interview"),
)

_ASSESSMENT = _rules(
    (
        r"(?:online|coding|technical|skills?|aptitude|programming) (?:assessment|test|challenge|exercise)",
        3.5,
        "online assessment",
    ),
    (r"take[- ]home (?:assignment|exercise|task|challenge|project)", 3.5, "take-home assignment"),
    (
        r"complete (?:the|this|an|our|a) (?:\w+ )?(?:assessment|test|challenge|assignment)",
        3.0,
        "complete the assessment",
    ),
    (
        r"assessment (?:invitation|invite|link)|invit\w* (?:you )?to (?:take|complete) (?:an?|the)",
        3.0,
        "assessment invitation",
    ),
    (
        r"\b(?:hackerrank|codility|hackerearth|codesignal|testgorilla|mettl|imocha|coderbyte|hirevue|devskiller)\b",
        2.5,
        "assessment platform",
    ),
)

_CONFIRMATION = _rules(
    (
        r"(?:we(?:'ve| have)?|has been|have) (?:successfully )?received your (?:job )?application",
        3.5,
        "we have received your application",
    ),
    (
        r"your (?:job )?application (?:has been|was|is) (?:successfully )?(?:received|submitted)",
        3.5,
        "your application has been received",
    ),
    (
        r"your application (?:for|to) .{3,80}? (?:has been|was) (?:successfully )?(?:received|submitted|sent)",
        3.5,
        "your application has been submitted",
    ),
    (r"your application was sent to", 3.5, "your application was sent"),
    (r"application (?:received|confirmation|submitted)", 3.0, "application received"),
    (
        r"thank(?:s| you) for (?:applying|your (?:job )?application|submitting your application)",
        2.5,
        "thank you for applying",
    ),
    (r"thank(?:s| you) for your interest in", 1.5, "thank you for your interest"),
    (
        r"(?:will|are going to) (?:carefully )?review your (?:application|qualifications|resume|cv|profile)",
        1.5,
        "we will review your application",
    ),
    (
        r"if (?:your|there is a) (?:skills|experience|qualifications|background|profile)? ?(?:match|are a (?:good )?(?:fit|match))",
        1.0,
        "we will contact you if there is a match",
    ),
)

_PROCESS_UPDATE = _rules(
    (
        r"(?:application|candidacy) (?:is )?(?:currently )?(?:under review|being reviewed|in review)",
        3.0,
        "application under review",
    ),
    (
        r"(?:update|status) (?:on|of|regarding) your (?:application|candidacy)",
        2.5,
        "update on your application",
    ),
    (
        r"(?:still|currently) (?:reviewing|evaluating) (?:applications|candidates|your)",
        2.5,
        "still reviewing",
    ),
    (
        r"your application (?:has been )?(?:moved|advanced|forwarded|shared) (?:to|with)",
        3.0,
        "application moved forward",
    ),
    (r"application status|candidate (?:portal|status)", 1.5, "application status"),
    (r"(?:we'?ll|we will) be in touch", 1.0, "we will be in touch"),
)

_RECRUITER = _rules(
    (
        r"(?:came|come) across your (?:profile|resume|cv)|found your (?:profile|resume)",
        3.0,
        "came across your profile",
    ),
    (
        r"(?:i'?m|i am) (?:a |an )?(?:\w+ )?(?:recruiter|talent (?:acquisition|partner)|sourcer|hiring manager)",
        3.0,
        "introduces themselves as a recruiter",
    ),
    (
        r"(?:open|interested) (?:to|in) (?:new|exploring|a new)? ?(?:opportunit|role|position|conversation)",
        2.5,
        "asks if you are open to opportunities",
    ),
    (
        r"opportunity (?:that )?(?:might|may|could) (?:interest|be of interest)",
        2.5,
        "an opportunity that might interest you",
    ),
    (r"reaching out (?:regarding|about|with|to)", 1.5, "reaching out"),
    (r"\b(?:recruiter|talent acquisition|headhunter|staffing)\b", 1.0, "recruiter wording"),
)

_JOB_ALERT = _rules(
    (
        r"jobs? (?:you may|you might|that may|that might) (?:be interested in|like)",
        3.0,
        "job recommendations",
    ),
    (r"new jobs? (?:for you|matching|that match)|\d+\+? new jobs?", 3.0, "new jobs digest"),
    (r"\bjob alerts?\b|recommended jobs|jobs based on your (?:profile|search)", 3.0, "job alert"),
)

_JOB_CONTEXT = re.compile(
    r"\b(?:application|applied|applying|applicant|candidate|candidacy|position|role|"
    r"recruit\w*|hiring|interview\w*|job|career|talent|resume|cv|opening|vacancy|offer)\b",
    re.IGNORECASE,
)


def sender_domain(sender: str) -> str:
    """The lower-cased domain of a ``From`` value, or '' when none is present."""
    match = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", sender or "")
    return match.group(1).lower().rstrip(".") if match else ""


def domain_matches(domain: str, candidates: tuple[str, ...]) -> str:
    """The entry of ``candidates`` that ``domain`` equals or is a subdomain of."""
    for candidate in candidates:
        if domain == candidate or domain.endswith("." + candidate):
            return candidate
    return ""


def _score(rules: tuple[_Rule, ...], text: str, reasons: list[str], category: str) -> float:
    total = 0.0
    for pattern, weight, label in rules:
        if pattern.search(text):
            total += weight
            reasons.append(f"{category}: '{label}'")
    return total


def _confidence(score: float, competing: float) -> float:
    """Map a rule score to [0.35, 0.97], lowered when another category also scored."""
    base = 0.45 + 0.1 * min(score, 5.0)
    if competing >= STRONG:
        base -= 0.15
    elif competing > 0:
        base -= 0.05
    return round(max(0.35, min(0.97, base)), 2)


def classify(subject: str, body: str, sender: str) -> Classification:
    """Classify one email. Returns ``(category, confidence, reasons)``."""
    text = collapse_whitespace(f"{subject or ''}\n{body or ''}")
    domain = sender_domain(sender)
    reasons: list[str] = []

    scores: dict[str, float] = {
        REJECTION: _score(_REJECTION, text, reasons, REJECTION),
        OFFER: _score(_OFFER, text, reasons, OFFER),
        INTERVIEW_INVITATION: _score(_INTERVIEW, text, reasons, INTERVIEW_INVITATION),
        ASSESSMENT_INVITATION: _score(_ASSESSMENT, text, reasons, ASSESSMENT_INVITATION),
        APPLICATION_CONFIRMATION: _score(_CONFIRMATION, text, reasons, APPLICATION_CONFIRMATION),
        PROCESS_UPDATE: _score(_PROCESS_UPDATE, text, reasons, PROCESS_UPDATE),
        RECRUITER_MESSAGE: _score(_RECRUITER, text, reasons, RECRUITER_MESSAGE),
    }

    for sentence in _UNFORTUNATELY.findall(text):
        if not _DISCLAIMER.search(sentence):
            scores[REJECTION] += 2.0
            reasons.append(f"{REJECTION}: 'unfortunately'")
            break

    ats = domain_matches(domain, ATS_SENDER_DOMAINS)
    assessment_vendor = domain_matches(domain, ASSESSMENT_DOMAINS)
    if assessment_vendor:
        scores[ASSESSMENT_INVITATION] += 2.0
        reasons.append(f"{ASSESSMENT_INVITATION}: sender is {assessment_vendor}")
    if ats:
        reasons.append(f"sender is the applicant-tracking system {ats}")

    alert_reasons: list[str] = []
    alert_score = _score(_JOB_ALERT, text, alert_reasons, "job_alert")
    context_hits = len(_JOB_CONTEXT.findall(text))

    # Interview weight from a bare mention of the word or a meeting link alone is not an
    # invitation; it needs one of the stronger phrases to reach the threshold.
    def strong(category: str) -> bool:
        return scores[category] >= STRONG

    def best_other(excluded: str) -> float:
        return max((value for key, value in scores.items() if key != excluded), default=0.0)

    def decide(category: str) -> Classification:
        return Classification(
            category, _confidence(scores[category], best_other(category)), reasons
        )

    if strong(REJECTION):
        return decide(REJECTION)

    leading = [c for c in (OFFER, INTERVIEW_INVITATION, ASSESSMENT_INVITATION) if strong(c)]
    if leading:
        # Ties resolve in the tuple's order: offer, then interview, then assessment.
        return decide(max(leading, key=lambda c: scores[c]))

    if scores[REJECTION] >= 1.5 and (
        scores[APPLICATION_CONFIRMATION] > 0 or scores[PROCESS_UPDATE] > 0 or context_hits
    ):
        return decide(REJECTION)

    if alert_score >= STRONG and not ats and max(scores.values()) < STRONG:
        return Classification(
            NOT_JOB_RELATED,
            0.8,
            [*reasons, *alert_reasons, "job-alert digest, not a response to an application"],
        )

    for category in (APPLICATION_CONFIRMATION, PROCESS_UPDATE, RECRUITER_MESSAGE):
        if scores[category] >= 2.0:
            return decide(category)

    if ats or assessment_vendor or (context_hits >= 3 and max(scores.values()) > 0):
        return Classification(
            OTHER_JOB_RELATED, 0.5 if ats else 0.4, reasons or ["job-related wording"]
        )

    return Classification(
        NOT_JOB_RELATED, 0.7 if context_hits == 0 else 0.55, reasons or ["no hiring signals"]
    )


__all__ = [
    "APPLICATION_CONFIRMATION",
    "ASSESSMENT_DOMAINS",
    "ASSESSMENT_INVITATION",
    "ATS_SENDER_DOMAINS",
    "CATEGORIES",
    "Classification",
    "INTERVIEW_INVITATION",
    "NOT_JOB_RELATED",
    "OFFER",
    "OTHER_JOB_RELATED",
    "PROCESS_UPDATE",
    "RECRUITER_MESSAGE",
    "REJECTION",
    "classify",
    "domain_matches",
    "sender_domain",
]
