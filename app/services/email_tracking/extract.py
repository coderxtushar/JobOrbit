"""Fact extraction from a job-related email.

Every field is either read from the text or left as ``None``. Nothing is inferred beyond
what the words say: an ambiguous ``04/05/2026`` stays unknown rather than being read as
April or May, and a date without a year gets one only when the email's own received time
is known to anchor it. A wrong interview date is worse than none, because the user would
plan around it.

Pure standard library: the date formats ATS mail uses are few enough to parse directly.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from email.utils import getaddresses
from typing import Any
from urllib.parse import urlsplit

from app.services.email_tracking.classifier import (
    ASSESSMENT_DOMAINS,
    ATS_SENDER_DOMAINS,
    domain_matches,
    sender_domain,
)
from app.services.text import collapse_whitespace

_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_WEEKDAY = (
    r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|rsday|urday|sday)?,?\s+)?"
)
_ORD = r"(?:st|nd|rd|th)?"

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?P<year>20\d{2})-(?P<mnum>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(
        rf"\b{_WEEKDAY}(?P<day>\d{{1,2}}){_ORD}(?:\s+of)?\s+{_MONTH},?(?:\s+(?P<year>20\d{{2}}))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_WEEKDAY}{_MONTH}\s+(?P<day>\d{{1,2}}){_ORD},?(?:\s+(?P<year>20\d{{2}}))?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<a>\d{1,2})[/.](?P<b>\d{1,2})[/.](?P<year>20\d{2})\b"),
)

_TIME = re.compile(
    r"\b(?P<hour>[01]?\d|2[0-3])(?:[:.](?P<minute>[0-5]\d))?\s*(?P<ampm>[ap]\.?m\.?)?"
    r"(?:\s*\(?(?P<tz>IST|UTC|GMT|PST|PDT|EST|EDT|CST|CDT|CET|CEST|BST|SGT|AEST|"
    r"(?:UTC|GMT)\s?[+-]\s?\d{1,2}(?::?\d{2})?)\)?)?",
    re.IGNORECASE,
)

_TZ_OFFSETS: dict[str, float] = {
    "IST": 5.5,
    "UTC": 0,
    "GMT": 0,
    "PST": -8,
    "PDT": -7,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "CET": 1,
    "CEST": 2,
    "BST": 1,
    "SGT": 8,
    "AEST": 10,
}

_URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
_MEETING_HOSTS = (
    "zoom.us",
    "meet.google.com",
    "teams.microsoft.com",
    "teams.live.com",
    "webex.com",
)

_REFERENCE = re.compile(
    r"\b(?:application|reference|ref|requisition|req|job|candidate|tracking)\.?\s*"
    r"(?:id|no\.?|number|#|code|reference)\s*[:#.]?\s*(?P<ref>[A-Z0-9][A-Z0-9_-]{3,40})\b",
    re.IGNORECASE,
)
_REQ_TOKEN = re.compile(r"\b(?P<ref>(?:R|JR|REQ|JOB)-?\d{4,10})\b")

_DEADLINE_CUE = re.compile(
    r"(?:by|before|no later than|deadline(?: is)?:?|due(?: by| on)?|expires?(?: on)?|"
    r"valid (?:until|till)|complete (?:it )?(?:by|before))\s*$",
    re.IGNORECASE,
)
_WITHIN_DAYS = re.compile(
    r"within\s+(?P<n>\d{1,2}|one|two|three|four|five|six|seven|ten|fourteen)\s+"
    r"(?:calendar\s+|business\s+|working\s+)?days?",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "ten": 10,
    "fourteen": 14,
}
_INTERVIEW_CUE = re.compile(
    r"interview|scheduled|call|meeting|round|screen|chat|conversation|slot|availab", re.IGNORECASE
)

_STOP = r"(?=\s+(?:position|role|job|opening|opportunity|at|with|has|have|is|was|in|for)\b|[.,!;:|\n(]|\s+[-–]|$)"
_EMPLOYER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:thank(?:s| you) for (?:applying|your (?:application|interest))|"
        r"your application|you(?:r)? applied|interest in (?:joining|working at)?)\s+"
        r"(?:to|at|with|for a role at)\s+(?P<employer>[A-Z][\w&'.\- ]{1,60}?)" + _STOP
    ),
    re.compile(
        r"(?:interview|assessment|offer|position|role|opportunity|career|future)s?\s+"
        r"(?:with|at)\s+(?P<employer>[A-Z][\w&'.\- ]{1,60}?)" + _STOP
    ),
    re.compile(
        r"\b(?:position|role|post|opening) of [A-Z][\w/&+#()\- ]{2,80}? at\s+"
        r"(?P<employer>[A-Z][\w&'.\-]{1,40}(?: [A-Z][\w&'.\-]{1,30}){0,2})" + _STOP
    ),
    re.compile(
        r"(?:team|everyone|all of us|recruiting team|hiring team) at\s+(?P<employer>[A-Z][\w&'.\- ]{1,60}?)"
        + _STOP
    ),
    re.compile(
        r"\bjoin(?:ing)?\s+(?P<employer>[A-Z][\w&'.\-]{1,40}(?: [A-Z][\w&'.\-]{1,30}){0,2})" + _STOP
    ),
)
_TITLE_END = r"(?=\s+(?:at|with|in|has|is|was)\b|[.!;:|\n,]|\s+[-\u2013]|$)"
_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:position|role|post|opening) of\s+(?P<title>[A-Z][\w/&+#()\- ]{2,80}?)" + _TITLE_END
    ),
    re.compile(
        r"\b(?:for|to) (?:the |our |an? )?(?P<title>[A-Z][\w/&+#()\- ]{2,80}?)\s+"
        r"(?:position|role|opening|opportunity|vacancy)\b"
    ),
    re.compile(
        r"\b(?:application|applying|applied|interview)\s+(?:for|to)\s+(?:the |an? )?"
        r"(?P<title>[A-Z][\w/&+#()\- ]{2,80}?)\s+(?:at|with)\s+[A-Z]"
    ),
)
#: Subject lines such as "Interview invitation - Software Engineer at Globex". Applied to
#: the subject only: in a body the same shape matches ordinary sentences.
_SUBJECT_TITLE = re.compile(
    r"^(?:(?i:re|fwd?):\s*)*(?P<title>[A-Z][\w/&+#.()\-\u2013|: ]{2,120}?)\s+(?:at|@)\s+[A-Z]"
)
_TITLE_NOISE = re.compile(
    r"^(?:interview|invitation|application|update|thank you|thanks|your|new|offer|"
    r"assessment|next steps|regarding|re|fwd?)\b",
    re.IGNORECASE,
)
_ROLE_PERSON_AT = re.compile(
    r"\b(?:recruiter|recruiting|sourcer|talent (?:partner|acquisition|lead)|hiring manager|"
    r"manager|engineer|partner|lead|director) (?:at|with|from)\s+"
    r"(?P<employer>[A-Z][\w&'.\-]{1,40}(?: [A-Z][\w&'.\-]{1,30}){0,2})" + _STOP
)
_ROLE_MAILBOX = re.compile(
    r"^(?:no-?reply|do-?not-?reply|careers?|jobs?|talent|recruit\w*|hr|hiring|people|notifications?)",
    re.IGNORECASE,
)
_GENERIC_NAMES = re.compile(
    r"^(?:no[- ]?reply|do[- ]?not[- ]?reply|notifications?|jobs?|careers?|recruiting|recruitment|"
    r"talent(?: acquisition)?|hiring(?: team)?|hr|people|team|greenhouse|lever|ashby|workday|"
    r"smartrecruiters|icims|jobvite|workable|linkedin|indeed|naukri|hackerrank|codility|"
    r"hackerearth|codesignal|testgorilla|calendly)$",
    re.IGNORECASE,
)
_NAME_SUFFIX = re.compile(
    r"\s*(?:[-|@,]\s*)?(?:\b(?:recruiting|recruitment|careers?|jobs|talent(?: acquisition)?|"
    r"hiring(?: team)?|hr|people(?: team)?|team|via \w+|notifications?)\b\s*)+$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ExtractedFacts:
    employer: str | None = None
    job_title: str | None = None
    application_reference: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    sender_domain: str | None = None
    timestamp: str | None = None
    deadline: str | None = None
    interview_date: str | None = None
    interview_time: str | None = None
    interview_timezone: str | None = None
    #: Only set when the timezone was stated, so it is a real instant and not a guess.
    interview_at: str | None = None
    meeting_link: str | None = None
    assessment_link: str | None = None
    links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("links", None)
        return data


# ------------------------------------------------------------------------- dates


def _month(value: str) -> int | None:
    return _MONTHS.get(value.lower().rstrip("."))


def _build_date(year: int | None, month: int, day: int, reference: datetime | None) -> date | None:
    if year is None:
        if reference is None:
            return None
        # A date without a year in a mail means the next such date on or after receipt
        # (allowing a week's slack for "as discussed on 28 Nov" in a late reply).
        year = reference.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate < reference.date() - timedelta(days=7):
            year += 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str, reference: datetime | None = None) -> list[tuple[int, int, date]]:
    """Every unambiguous date in ``text`` as ``(start, end, date)``, in text order."""
    found: list[tuple[int, int, date]] = []
    taken: list[tuple[int, int]] = []
    for index, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            groups = match.groupdict()
            year = int(groups["year"]) if groups.get("year") else None
            value: date | None
            if index == 0:
                value = _build_date(year, int(groups["mnum"]), int(groups["day"]), reference)
            elif index == 3:
                first, second = int(groups["a"]), int(groups["b"])
                if first > 12 >= second:
                    value = _build_date(year, second, first, reference)
                elif second > 12 >= first:
                    value = _build_date(year, first, second, reference)
                elif first == second:
                    value = _build_date(year, first, first, reference)
                else:
                    value = None  # 04/05/2026: April or May? Unknown, so not guessed.
            else:
                month = _month(groups["month"])
                value = _build_date(year, month, int(groups["day"]), reference) if month else None
            if value is not None:
                found.append((span[0], span[1], value))
                taken.append(span)
    found.sort()
    return found


def _parse_time(text: str) -> tuple[time, str | None] | None:
    """The first plausible clock time in ``text``: needs minutes or am/pm to count."""
    for match in _TIME.finditer(text):
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        ampm = (match.group("ampm") or "").lower().replace(".", "")
        if not match.group("minute") and not ampm:
            continue  # a bare number such as "3 rounds" is not a time
        if ampm:
            if hour < 1 or hour > 12:
                continue
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        tz = match.group("tz")
        return time(hour, minute), (tz.upper().replace(" ", "") if tz else None)
    return None


def _tz_from_label(label: str) -> timezone | None:
    if label in _TZ_OFFSETS:
        return timezone(timedelta(hours=_TZ_OFFSETS[label]))
    match = re.match(r"(?:UTC|GMT)([+-])(\d{1,2}):?(\d{2})?$", label)
    if match:
        sign = 1 if match.group(1) == "+" else -1
        minutes = int(match.group(2)) * 60 + int(match.group(3) or 0)
        return timezone(sign * timedelta(minutes=minutes))
    return None


# ------------------------------------------------------------------------- links


def find_links(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for raw in _URL.findall(text or ""):
        seen.setdefault(raw.rstrip(".,;:!?"), None)
    return list(seen)


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _meeting_link(links: list[str]) -> str | None:
    for link in links:
        host = _host(link)
        if any(host == known or host.endswith("." + known) for known in _MEETING_HOSTS):
            if "meet.google.com" in host and not re.search(r"/[a-z]{3}-[a-z]{4}-[a-z]{3}", link):
                continue
            return link
    return None


def _assessment_link(links: list[str]) -> str | None:
    for link in links:
        if domain_matches(_host(link), ASSESSMENT_DOMAINS):
            return link
    return None


# ------------------------------------------------------------------------- names


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = collapse_whitespace(value).strip(" .,-–|'\"")
    cleaned = re.sub(r"^(?:the)\s+", "", cleaned, flags=re.IGNORECASE)
    if len(cleaned) < 2 or _GENERIC_NAMES.match(cleaned):
        return None
    return cleaned


def employer_from_sender_name(name: str, address: str = "") -> str | None:
    """'Acme Recruiting' -> 'Acme'. Generic names ('Greenhouse', 'no-reply') -> None.

    A plain personal name ("Jane <jane@hooli.com>") is not an employer, so the display name
    is only used when it carries a hiring suffix, names a person *at* a company, says
    "via" a hiring system, or was sent from a role mailbox (careers@, no-reply@...).
    """
    if not name:
        return None
    original = name.strip().strip("\"'")
    via = re.match(r"^(?P<employer>.+?)\s+via\s+\w+", original, re.IGNORECASE)
    if via:
        return _clean_name(via.group("employer"))
    person_at = re.search(r"\b(?:at|from|@)\s+(.+)$", original)
    if person_at:
        return _clean_name(_NAME_SUFFIX.sub("", person_at.group(1)))
    stripped = _NAME_SUFFIX.sub("", original)
    local_part = address.split("@", 1)[0]
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    from_hiring_system = bool(
        domain_matches(domain, ATS_SENDER_DOMAINS) or domain_matches(domain, ASSESSMENT_DOMAINS)
    )
    if stripped == original and not _ROLE_MAILBOX.match(local_part) and not from_hiring_system:
        return None
    return _clean_name(stripped)


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    # "Interview invitation - Software Engineer" keeps the part after the last separator.
    parts = [part for part in re.split(r"\s+[-\u2013|]\s+|:\s+", value) if part.strip()]
    title = parts[-1] if parts else value
    title = _clean_name(title)
    if title is None or _TITLE_NOISE.match(title) or len(title.split()) > 8:
        return None
    return title


def _first(patterns: tuple[re.Pattern[str], ...], *texts: str, group: str) -> str | None:
    for text in texts:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                value = _clean_name(match.group(group))
                if value:
                    return value
    return None


# ------------------------------------------------------------------------- entry point


def extract(
    subject: str,
    body: str,
    sender: str,
    received_at: datetime | None = None,
) -> ExtractedFacts:
    """Extract what the email states. Unknown fields stay ``None``."""
    subject = collapse_whitespace(subject or "")
    flat_body = collapse_whitespace(body or "")
    addresses = getaddresses([sender or ""])
    sender_name, sender_address = addresses[0] if addresses else ("", "")
    facts = ExtractedFacts(
        sender=sender_address.lower() or None,
        sender_name=sender_name or None,
        sender_domain=sender_domain(sender) or None,
        timestamp=received_at.astimezone(UTC).isoformat() if received_at else None,
    )

    facts.employer = _first(
        (*_EMPLOYER_PATTERNS, _ROLE_PERSON_AT), subject, flat_body, group="employer"
    )
    if facts.employer is None:
        facts.employer = employer_from_sender_name(sender_name, sender_address)
    facts.job_title = _clean_title(_first(_TITLE_PATTERNS, subject, flat_body, group="title"))
    if facts.job_title is None:
        subject_title = _SUBJECT_TITLE.search(subject)
        facts.job_title = _clean_title(subject_title.group("title") if subject_title else None)

    for text in (subject, flat_body):
        reference = _REFERENCE.search(text) or _REQ_TOKEN.search(text)
        if reference and any(ch.isdigit() for ch in reference.group("ref")):
            facts.application_reference = reference.group("ref")
            break

    facts.links = find_links(body)
    facts.meeting_link = _meeting_link(facts.links)
    facts.assessment_link = _assessment_link(facts.links)

    combined = f"{subject}\n{flat_body}"
    dates = find_dates(combined, received_at)
    for start, end, value in dates:
        before = combined[max(0, start - 40) : start]
        if facts.deadline is None and _DEADLINE_CUE.search(before):
            facts.deadline = value.isoformat()
            continue
        if facts.interview_date is None:
            window = combined[max(0, start - 120) : end + 60]
            if _INTERVIEW_CUE.search(window):
                facts.interview_date = value.isoformat()
                parsed = _parse_time(combined[end : end + 60]) or _parse_time(
                    combined[max(0, start - 40) : start]
                )
                if parsed:
                    clock, tz_label = parsed
                    facts.interview_time = clock.strftime("%H:%M")
                    facts.interview_timezone = tz_label
                    tz = _tz_from_label(tz_label) if tz_label else None
                    if tz is not None:
                        facts.interview_at = datetime.combine(value, clock, tz).isoformat()
    if facts.deadline is None and received_at is not None:
        within = _WITHIN_DAYS.search(combined)
        if within:
            raw = within.group("n").lower()
            days = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
            facts.deadline = (received_at.astimezone(UTC).date() + timedelta(days=days)).isoformat()
    return facts


__all__ = ["ExtractedFacts", "employer_from_sender_name", "extract", "find_dates", "find_links"]
