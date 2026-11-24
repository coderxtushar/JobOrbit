"""Matching an email to the application it is about.

Each application gets a score in [0, 1] built from independent signals, and every signal
that contributed is recorded so the review inbox can say *why* a candidate was proposed.
Linking is deliberately conservative: an email is linked automatically only when the best
candidate is both clearly good and clearly ahead of the next one. Two applications at the
same company with similar titles are exactly where a confident-looking guess goes wrong,
so that case goes to the user instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    SubmissionAttempt,
)
from app.services.email_tracking.classifier import ATS_SENDER_DOMAINS, domain_matches
from app.services.email_tracking.extract import ExtractedFacts
from app.services.text import normalize_company, normalize_text

AUTO_LINK_THRESHOLD = 0.75
#: The best candidate must beat the runner-up by at least this much to be auto-linked.
AUTO_LINK_MARGIN = 0.2
#: Candidates below this are not worth showing in the review inbox.
CANDIDATE_FLOOR = 0.25
MAX_CANDIDATES = 5
#: Upper bound on applications scored per email; a single user rarely has more.
MAX_APPLICATIONS_SCANNED = 5000

AUTO_LINKED = "auto_linked"
NEEDS_REVIEW = "needs_review"
UNMATCHED = "unmatched"
USER_LINKED = "user_linked"
DISMISSED = "dismissed"

#: ATS job-board hosts paired with the mail domains the same ATS sends from. A Greenhouse
#: job and a Greenhouse email are weak evidence on their own (thousands of companies use
#: it), but the board slug in the job URL names the company.
_ATS_BOARDS: dict[str, tuple[str, ...]] = {
    "greenhouse.io": ("greenhouse.io", "greenhouse-mail.io"),
    "lever.co": ("lever.co", "hire.lever.co"),
    "ashbyhq.com": ("ashbyhq.com",),
    "myworkdayjobs.com": ("myworkday.com", "workday.com"),
    "smartrecruiters.com": ("smartrecruiters.com",),
    "workable.com": ("workable.com", "workablemail.com"),
}
_PRE_SUBMISSION = frozenset(
    {
        ApplicationStatus.DISCOVERED,
        ApplicationStatus.SCORED,
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.SKIPPED,
    }
)
_GENERIC_TITLE_WORDS = frozenset(
    {"senior", "junior", "sr", "jr", "i", "ii", "iii", "the", "a", "an"}
)


@dataclass(slots=True)
class Candidate:
    application_id: int
    score: float
    job_title: str
    company: str
    status: str
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "score": round(self.score, 3),
            "job_title": self.job_title,
            "company": self.company,
            "status": self.status,
            "signals": list(self.signals),
        }


@dataclass(slots=True)
class MatchResult:
    state: str
    application_id: int | None
    confidence: float
    candidates: list[Candidate]

    def candidate_dicts(self) -> list[dict[str, Any]]:
        return [candidate.to_dict() for candidate in self.candidates]


@dataclass(frozen=True, slots=True)
class EmailEvidence:
    """What the matcher may look at. Body text is used in memory only, never stored."""

    facts: ExtractedFacts
    subject: str
    body: str
    sender_domain: str
    recipient: str
    received_at: datetime | None
    category: str


def registrable_domain(host: str) -> str:
    """'careers.acme.co.in' -> 'acme.co.in'; 'mail.acme.com' -> 'acme.com'.

    A heuristic without the public-suffix list: two-letter country codes preceded by a
    short second-level label (co, com, org, net, ac, gov, edu) keep three labels.
    """
    labels = [label for label in (host or "").lower().strip(".").split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _host(url: str) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _board_slug(url: str) -> str:
    """The company slug in an ATS board URL, e.g. 'acme' in jobs.lever.co/acme/123."""
    try:
        parts = [part for part in urlsplit(url or "").path.split("/") if part]
    except ValueError:
        return ""
    if not parts:
        return ""
    if parts[0] in {"embed", "jobs", "job_app", "en-US", "en"} and len(parts) > 1:
        return parts[1].lower()
    return parts[0].lower()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = set(left.split()) - _GENERIC_TITLE_WORDS
    right_tokens = set(right.split()) - _GENERIC_TITLE_WORDS
    jaccard = (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens and right_tokens
        else 0.0
    )
    return max(jaccard, SequenceMatcher(None, left, right).ratio() * 0.9)


def _mentions(haystack: str, needle: str) -> bool:
    if not needle or len(needle) < 3:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _reference_hit(reference: str, job: Job, attempts: list[SubmissionAttempt]) -> bool:
    needle = reference.lower()
    haystacks = [job.url or "", job.canonical_url or ""]
    haystacks += [ref.external_id or "" for ref in job.source_references]
    haystacks += [ref.url or "" for ref in job.source_references]
    for attempt in attempts:
        haystacks += [attempt.confirmation_id, attempt.provider_reference, attempt.submitted_url]
    return any(needle in (value or "").lower() for value in haystacks)


def score_application(
    application: Application,
    job: Job,
    evidence: EmailEvidence,
    profile: CandidateProfile | None,
    attempts: list[SubmissionAttempt],
) -> Candidate:
    facts = evidence.facts
    content = normalize_text(f"{evidence.subject} {evidence.body}")
    company = job.company_normalized or normalize_company(job.company)
    title = normalize_text(job.title)
    signals: list[str] = []
    score = 0.0

    # Employer: the strongest single signal, from the extracted name or a mention.
    employer = normalize_company(facts.employer or "")
    employer_score = 0.0
    if employer and company:
        similarity = _similarity(employer, company)
        if similarity >= 0.999:
            employer_score = 0.45
            signals.append(f"employer '{facts.employer}' matches")
        elif similarity >= 0.8 or _mentions(employer, company) or _mentions(company, employer):
            employer_score = 0.35
            signals.append(f"employer '{facts.employer}' is similar to '{job.company}'")
    if employer_score == 0.0 and _mentions(content, company):
        employer_score = 0.3
        signals.append(f"the email mentions '{job.company}'")
    score += employer_score

    # Title.
    extracted_title = normalize_text(facts.job_title or "")
    if extracted_title and title:
        similarity = _similarity(extracted_title, title)
        if similarity >= 0.999:
            score += 0.25
            signals.append("job title matches")
        elif similarity >= 0.6:
            score += 0.15
            signals.append(f"job title is similar ({similarity:.0%})")
        elif similarity < 0.3:
            score -= 0.1
            signals.append("job title differs")
    elif title and _mentions(content, title):
        score += 0.15
        signals.append("the email mentions the job title")

    # Application reference.
    if facts.application_reference and _reference_hit(facts.application_reference, job, attempts):
        score += 0.4
        signals.append(f"reference {facts.application_reference} matches the job")

    # Sender domain against the job's own domain, or the ATS it was posted on.
    sender = evidence.sender_domain
    job_host = _host(job.url) or _host(job.canonical_url)
    if sender and job_host:
        ats_board = next(
            (board for board in _ATS_BOARDS if job_host == board or job_host.endswith("." + board)),
            "",
        )
        if ats_board and domain_matches(sender, _ATS_BOARDS[ats_board]):
            score += 0.1
            signals.append(f"sent by {ats_board}, where the job was posted")
            slug = _board_slug(job.url)
            if slug and (
                slug == company.replace(" ", "") or _mentions(content, slug.replace("-", " "))
            ):
                score += 0.1
                signals.append(f"the job's board '{slug}' matches")
        elif not domain_matches(sender, ATS_SENDER_DOMAINS) and registrable_domain(
            sender
        ) == registrable_domain(job_host):
            score += 0.25
            signals.append(f"sender domain {sender} matches the job's site")

    # Recipient against the profile's address: a sanity check for a single-user install.
    if profile is not None and profile.email and evidence.recipient:
        if profile.email.strip().lower() in evidence.recipient.lower():
            score += 0.05
            signals.append("sent to your profile email")

    # Timing: a response cannot predate the application it responds to.
    anchor = application.submitted_at or application.prepared_at or application.created_at
    if evidence.received_at is not None and anchor is not None:
        if evidence.received_at < anchor - timedelta(days=1):
            score -= 0.3
            signals.append("email predates the application")
        elif evidence.received_at - anchor <= timedelta(days=60):
            score += 0.1
            signals.append("received within 60 days of the application")
        elif evidence.received_at - anchor > timedelta(days=180):
            score -= 0.1
            signals.append("received more than 180 days after the application")

    if application.status in _PRE_SUBMISSION and evidence.category != "recruiter_message":
        score -= 0.1
        signals.append(f"the application is still {application.status.value}")

    return Candidate(
        application_id=application.id,
        score=max(0.0, min(1.0, score)),
        job_title=job.title,
        company=job.company,
        status=application.status.value,
        signals=signals,
    )


def match_email(
    session: Session, evidence: EmailEvidence, profile: CandidateProfile | None
) -> MatchResult:
    """Score every application and decide between auto-link, review and unmatched."""
    rows = session.execute(
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .order_by(Application.id.desc())
        .limit(MAX_APPLICATIONS_SCANNED)
    ).all()
    if not rows:
        return MatchResult(UNMATCHED, None, 0.0, [])

    attempts_by_application: dict[int, list[SubmissionAttempt]] = {}
    application_ids = [application.id for application, _ in rows]
    for attempt in session.scalars(
        select(SubmissionAttempt).where(SubmissionAttempt.application_id.in_(application_ids))
    ):
        if attempt.application_id is not None:
            attempts_by_application.setdefault(attempt.application_id, []).append(attempt)

    scored = sorted(
        (
            score_application(
                application, job, evidence, profile, attempts_by_application.get(application.id, [])
            )
            for application, job in rows
        ),
        key=lambda candidate: (-candidate.score, -candidate.application_id),
    )
    candidates = [c for c in scored if c.score >= CANDIDATE_FLOOR][:MAX_CANDIDATES]
    if not candidates:
        return MatchResult(UNMATCHED, None, 0.0, [])

    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    if best.score >= AUTO_LINK_THRESHOLD and best.score - runner_up >= AUTO_LINK_MARGIN:
        return MatchResult(AUTO_LINKED, best.application_id, best.score, candidates)
    return MatchResult(NEEDS_REVIEW, None, best.score, candidates)


__all__ = [
    "AUTO_LINKED",
    "AUTO_LINK_MARGIN",
    "AUTO_LINK_THRESHOLD",
    "CANDIDATE_FLOOR",
    "DISMISSED",
    "NEEDS_REVIEW",
    "UNMATCHED",
    "USER_LINKED",
    "Candidate",
    "EmailEvidence",
    "MatchResult",
    "match_email",
    "registrable_domain",
    "score_application",
]
