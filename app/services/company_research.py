"""Company research assembled only from sources JobOrbit can cite.

The temptation with "company research" is to describe the company: its products, its
funding, its culture. None of that is in the database, and writing it anyway is exactly
the invented fact this product exists to avoid. So a profile here is built from three
kinds of source, each named on every fact it supports:

* **job listings** JobOrbit holds for the company, cited by URL and the date they were
  retrieved, including the "About us" text those listings carry (quoted, not paraphrased);
* **your profile**, for which of your own projects are relevant to a specific job;
* **the company's own page**, only when you supply its URL, enable
  ``company_research_external`` and ask for the fetch. Only its ``<title>`` and meta
  description are kept, with the URL and fetch date. A URL is never guessed from a name.

Business model and products are reported only when cited text states them ("B2B",
"SaaS", "marketplace", "platform for ..."), with the quote. Otherwise the profile says
"not stated in the available sources" rather than leaving a gap a reader might fill.

The company-level part is cached in :class:`~app.db.models.CompanyProfile` and rebuilt when
asked, or when a listing for the company has arrived since the last build. The job-specific
part (requirements, relevant projects, interview topics) is cheap and computed per call.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import CandidateProfile, CompanyProfile, Job, utcnow
from app.services.evidence import analyse_description
from app.services.normalization import extract_skills_from_description
from app.services.text import canonical_skills, collapse_whitespace, normalize_company
from app.services.url_safety import inspect_url
from app.sources.http_fetch import USER_AGENT

NOT_STATED = "not stated in the available sources"
PROFILE_SOURCE: dict[str, Any] = {
    "id": "profile",
    "kind": "profile",
    "label": "your profile",
    "url": "",
    "retrieved_at": None,
}

#: Bytes read from a company page. A title and meta description sit in the first few KB;
#: the cap keeps a hostile or huge page from costing memory.
WEBSITE_MAX_BYTES = 256_000
_MAX_REDIRECTS = 3
_QUOTE_LIMIT = 600

_ABOUT_HEADINGS = (
    "about us",
    "about the company",
    "about company",
    "who we are",
    "company overview",
    "company description",
    "about the organisation",
    "about the organization",
)
_HEADING_WORDS = (
    "about",
    "responsibilit",
    "requirement",
    "qualification",
    "what you",
    "who you",
    "benefit",
    "perks",
    "nice to have",
    "preferred",
    "skills",
    "role",
    "the job",
    "the team",
    "compensation",
    "how to apply",
    "why join",
    "our culture",
    "equal opportunity",
    "must have",
    "good to have",
    "you will",
    "you'll",
    "we offer",
    "overview",
    "description",
)

#: (label, pattern) — a business-model term only counts when the cited text contains it.
_BUSINESS_MODEL_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("B2B", re.compile(r"\bB2B\b", re.IGNORECASE)),
    ("B2C", re.compile(r"\bB2C\b", re.IGNORECASE)),
    ("D2C", re.compile(r"\bD2C\b|\bdirect[- ]to[- ]consumer\b", re.IGNORECASE)),
    ("SaaS", re.compile(r"\bSaaS\b|\bsoftware[- ]as[- ]a[- ]service\b", re.IGNORECASE)),
    ("marketplace", re.compile(r"\bmarketplace\b", re.IGNORECASE)),
    ("subscription", re.compile(r"\bsubscription\b", re.IGNORECASE)),
    ("e-commerce", re.compile(r"\be-?commerce\b", re.IGNORECASE)),
    ("open source", re.compile(r"\bopen[- ]source (?:company|platform|project)\b", re.I)),
    (
        "IT services / consulting",
        re.compile(r"\b(?:IT services|consulting firm|services company)\b", re.I),
    ),
)
_PRODUCT_CUES = re.compile(
    r"\b(?:(?:platform|app|application|tool|software|solution|product)s?\s+(?:for|that)\s+"
    r"[^.;\n]{3,120}|our products?\s+[^.;\n]{3,120}|we (?:build|make|develop)\s+[^.;\n]{3,120}|"
    r"helps?\s+(?:businesses|companies|teams|people|customers|merchants|developers)\s+"
    r"[^.;\n]{3,120})",
    re.IGNORECASE,
)

#: Engineering themes and the phrases that trigger them. Matched on word boundaries in the
#: full description; the phrase found and its line are kept as evidence.
ENGINEERING_THEMES: dict[str, tuple[str, ...]] = {
    "Scale and performance": (
        "at scale",
        "scalable",
        "scalability",
        "millions of",
        "high throughput",
        "high-throughput",
        "low latency",
        "low-latency",
        "performance",
    ),
    "Reliability and operations": (
        "reliability",
        "uptime",
        "on-call",
        "on call",
        "observability",
        "monitoring",
        "incident",
    ),
    "Distributed systems": (
        "distributed systems",
        "distributed system",
        "microservices",
        "microservice",
        "event-driven",
        "event driven",
    ),
    "Data and machine learning": (
        "machine learning",
        "data pipeline",
        "data pipelines",
        "data platform",
        "generative ai",
        "large language model",
        "llms",
        "deep learning",
        "analytics",
    ),
    "Security and compliance": ("security", "secure", "compliance", "privacy", "encryption"),
    "Developer tooling and automation": (
        "developer experience",
        "internal tools",
        "automation",
        "ci/cd",
        "tooling",
    ),
    "Product and user experience": (
        "user experience",
        "customer-facing",
        "end users",
        "end-users",
        "design system",
        "accessibility",
    ),
    "Testing and code quality": (
        "unit tests",
        "testing",
        "test-driven",
        "code review",
        "code reviews",
        "code quality",
    ),
    "Cloud infrastructure": (
        "cloud-native",
        "cloud native",
        "infrastructure as code",
        "cloud infrastructure",
    ),
}


class ExternalResearchRefused(RuntimeError):
    """The website fetch was requested but cannot be done. ``code`` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class CompanyResearch:
    """A cached company profile plus the job-specific context computed for this call."""

    profile: CompanyProfile
    from_cache: bool
    job_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.profile.display_name,
            "company_normalized": self.profile.company_normalized,
            "website": self.profile.website,
            "refreshed_at": _iso(self.profile.refreshed_at),
            "from_cache": self.from_cache,
            "data": self.profile.data,
            "sources": self.profile.sources,
            "job_context": self.job_context,
        }


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _clip(text: str, limit: int = _QUOTE_LIMIT) -> str:
    cleaned = collapse_whitespace(text)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _job_source(job: Job) -> dict[str, Any]:
    """How a fact drawn from this listing is cited: its URL and when it was retrieved."""
    retrieved = [ref.retrieved_at for ref in job.source_references if ref.retrieved_at]
    retrieved_at = max(retrieved) if retrieved else job.discovered_at
    url = job.url if job.url and inspect_url(job.url).safe else ""
    return {
        "id": f"job:{job.id}",
        "kind": "job_listing",
        "label": f"{job.title} — job listing",
        "job_id": job.id,
        "url": url,
        "retrieved_at": _iso(retrieved_at),
        "posted_at": _iso(job.posted_at),
    }


def _listings(session: Session, company_normalized: str) -> list[Job]:
    statement = (
        select(Job)
        .where(Job.company_normalized == company_normalized, Job.duplicate_of_id.is_(None))
        .order_by(Job.discovered_at.desc(), Job.id.desc())
    )
    return list(session.scalars(statement))


def is_heading(line: str) -> bool:
    """A short line that reads like a section heading in a job description."""
    stripped = line.strip().strip("#*").strip()
    if not stripped or len(stripped.split()) > 8 or len(stripped) > 70:
        return False
    lowered = stripped.lower()
    if stripped.endswith(":"):
        return True
    return any(lowered.startswith(word) for word in _HEADING_WORDS)


def about_sections(description: str, company: str = "") -> list[str]:
    """The text under an "About us"/"About the company" heading, verbatim, per section.

    "About <company>" counts too. An inline form ("About us: Acme builds ...") is read
    from the text after the colon.
    """
    if not description:
        return []
    headings = list(_ABOUT_HEADINGS)
    if company.strip():
        headings.append(f"about {company.strip().lower()}")
    lines = description.splitlines()
    sections: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip().strip("#*").strip()
        lowered = line.lower()
        heading = next((h for h in headings if lowered.startswith(h)), None)
        if heading is None:
            index += 1
            continue
        body: list[str] = []
        remainder = line[len(heading) :].lstrip(" :-–—").strip()
        if remainder and len(remainder.split()) > 3:
            body.append(remainder)
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if candidate and is_heading(candidate):
                break
            if candidate:
                body.append(candidate)
            index += 1
        text = " ".join(body).strip()
        if text:
            sections.append(text)
    return sections


def _sentences_with(text: str, pattern: re.Pattern[str]) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [_clip(sentence, 300) for sentence in sentences if pattern.search(sentence)]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", re.IGNORECASE)


_THEME_PATTERNS = {
    theme: [(phrase, _phrase_pattern(phrase)) for phrase in phrases]
    for theme, phrases in ENGINEERING_THEMES.items()
}


def engineering_focus(texts: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Themes found in (description, source) pairs, with the phrases that triggered them."""
    found: dict[str, dict[str, Any]] = {}
    for text, source in texts:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for theme, patterns in _THEME_PATTERNS.items():
                for phrase, pattern in patterns:
                    if not pattern.search(line):
                        continue
                    entry = found.setdefault(
                        theme, {"theme": theme, "phrases": [], "evidence": [], "_seen": set()}
                    )
                    if phrase not in entry["phrases"]:
                        entry["phrases"].append(phrase)
                    key = (source["id"], line)
                    if key not in entry["_seen"] and len(entry["evidence"]) < 4:
                        entry["_seen"].add(key)
                        quote = _clip(line.lstrip("•-*· \t"), 300)
                        entry["evidence"].append({"quote": quote, "source": source})
    themes = []
    for entry in found.values():
        entry.pop("_seen")
        themes.append(entry)
    themes.sort(key=lambda item: (-len(item["evidence"]), item["theme"]))
    return themes


def _job_skills(job: Job) -> list[str]:
    evidence = analyse_description(job.description)
    return canonical_skills(
        list(job.required_skills)
        + list(job.preferred_skills)
        + evidence.required
        + evidence.preferred
        + evidence.incidental
    )


def _opening_paragraph(description: str, company: str) -> str:
    """The text before the first heading, when it reads as the company describing itself."""
    lines: list[str] = []
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if is_heading(line):
            break
        lines.append(line)
    text = " ".join(lines)
    lowered = f" {text.lower()} "
    names = [name for name in (company.lower().strip(),) if name]
    if any(f" {name}" in lowered for name in names) or re.search(r"\b(?:we|our)\b", lowered):
        return text
    return ""


# --------------------------------------------------------------------------------------
# Website fetch (opt-in, user-supplied URL only)
# --------------------------------------------------------------------------------------


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            values = {key.lower(): (value or "") for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").lower()
            if name in ("description", "og:description") and not self.description:
                self.description = values.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 500:
            self.title += data


def parse_page_head(html_text: str) -> tuple[str, str]:
    """The page's ``<title>`` and meta description, whitespace-collapsed and clipped."""
    parser = _HeadParser()
    try:
        parser.feed(html_text)
    except Exception:  # pragma: no cover - HTMLParser is lenient; guard odd input
        pass
    return _clip(parser.title, 300), _clip(parser.description, 600)


def fetch_website_summary(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    """GET one page and keep only its title and meta description.

    Redirects are followed by hand, at most three, and every hop is re-checked with
    :func:`inspect_url`, so a public URL cannot bounce the request to a private address.
    Errors are returned in the result rather than raised: a failed fetch should leave the
    listings-based profile intact.
    """
    fetched_at = _iso(utcnow())
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        verdict = inspect_url(current)
        if not verdict.safe:
            return {"url": url, "fetched_at": fetched_at, "error": f"unsafe url: {verdict.reason}"}
        try:
            response = requests.get(
                current,
                timeout=timeout_seconds,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            return {"url": url, "fetched_at": fetched_at, "error": type(exc).__name__}
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                if not location:
                    return {"url": url, "fetched_at": fetched_at, "error": "redirect without url"}
                current = urljoin(current, location)
                continue
            if not response.ok:
                return {
                    "url": url,
                    "fetched_at": fetched_at,
                    "error": f"HTTP {response.status_code}",
                }
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return {
                    "url": url,
                    "fetched_at": fetched_at,
                    "error": f"not an HTML page ({content_type or 'no content type'})",
                }
            body = b""
            for chunk in response.iter_content(chunk_size=16_384):
                body += chunk
                if len(body) >= WEBSITE_MAX_BYTES:
                    break
            encoding = response.encoding or "utf-8"
            title, description = parse_page_head(body.decode(encoding, errors="replace"))
            return {
                "url": url,
                "final_url": current,
                "fetched_at": fetched_at,
                "title": title,
                "description": description,
            }
        finally:
            response.close()
    return {"url": url, "fetched_at": fetched_at, "error": "too many redirects"}


# --------------------------------------------------------------------------------------
# Building the profile
# --------------------------------------------------------------------------------------


def _stated_claims(
    texts: list[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    business: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for text, source in texts:
        for label, pattern in _BUSINESS_MODEL_CUES:
            for quote in _sentences_with(text, pattern):
                if (label, quote) in seen:
                    continue
                seen.add((label, quote))
                business.append({"statement": label, "quote": quote, "source": source})
        for quote in _sentences_with(text, _PRODUCT_CUES):
            if ("product", quote) in seen:
                continue
            seen.add(("product", quote))
            match = _PRODUCT_CUES.search(quote)
            products.append(
                {
                    "statement": collapse_whitespace(match.group(0)) if match else quote,
                    "quote": quote,
                    "source": source,
                }
            )
    return business[:8], products[:8]


def _build_company_data(
    jobs: list[Job], display_name: str, website: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = [_job_source(job) for job in jobs]
    by_job = {job.id: source for job, source in zip(jobs, sources, strict=True)}

    listings = [
        {
            "job_id": job.id,
            "title": job.title,
            "location": job.location,
            "url": by_job[job.id]["url"],
            "posted_at": _iso(job.posted_at),
            "retrieved_at": by_job[job.id]["retrieved_at"],
            "source": by_job[job.id],
        }
        for job in jobs
    ]

    about: list[dict[str, Any]] = []
    cited_texts: list[tuple[str, dict[str, Any]]] = []
    seen_about: set[str] = set()
    for job in jobs:
        sections = about_sections(job.description, display_name)
        heading = "about section"
        if not sections:
            opening = _opening_paragraph(job.description, display_name)
            sections = [opening] if opening else []
            heading = "opening of the listing"
        for section in sections:
            quote = _clip(section)
            if quote in seen_about:
                continue
            seen_about.add(quote)
            about.append({"quote": quote, "where": heading, "source": by_job[job.id]})
            cited_texts.append((section, by_job[job.id]))

    if website and not website.get("error"):
        website_source = {
            "id": "website",
            "kind": "website",
            "label": "company website (title and meta description)",
            "url": website.get("final_url") or website["url"],
            "retrieved_at": website.get("fetched_at"),
        }
        sources.append(website_source)
        page_text = "\n".join(
            part for part in (website.get("title", ""), website.get("description", "")) if part
        )
        if page_text:
            cited_texts.append((page_text, website_source))

    business, products = _stated_claims(cited_texts)

    skill_counts: Counter[str] = Counter()
    skill_sources: dict[str, list[str]] = {}
    for job in jobs:
        for skill in _job_skills(job):
            skill_counts[skill] += 1
            skill_sources.setdefault(skill, []).append(by_job[job.id]["id"])
    technologies = [
        {"skill": skill, "listing_count": count, "source_ids": skill_sources[skill]}
        for skill, count in sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    focus = engineering_focus([(job.description, by_job[job.id]) for job in jobs])

    dates = [job.discovered_at for job in jobs if job.discovered_at]
    data: dict[str, Any] = {
        "display_name": display_name,
        "listing_count": len(jobs),
        "first_seen": _iso(min(dates)) if dates else None,
        "last_seen": _iso(max(dates)) if dates else None,
        "listings": listings,
        "about": about,
        "business_model": {
            "stated": bool(business),
            "facts": business,
            "message": "" if business else NOT_STATED,
        },
        "products": {
            "stated": bool(products),
            "facts": products,
            "message": "" if products else NOT_STATED,
        },
        "technologies": technologies,
        "engineering_focus": focus,
        "website": website,
        "notes": [
            "Every fact cites the listing, your profile or the page it came from.",
            "Nothing here was looked up elsewhere; anything not in a source is reported as "
            "not stated.",
        ],
    }
    return data, sources


def _is_stale(row: CompanyProfile, session: Session, company_normalized: str) -> bool:
    newest, count = session.execute(
        select(func.max(Job.discovered_at), func.count(Job.id)).where(
            Job.company_normalized == company_normalized, Job.duplicate_of_id.is_(None)
        )
    ).one()
    if count != (row.data or {}).get("listing_count"):
        return True
    if newest is None:
        return False
    if newest.tzinfo is None:  # SQLite aggregate bypasses the column type decorator
        from datetime import UTC

        newest = newest.replace(tzinfo=UTC)
    return bool(newest > row.refreshed_at)


def build_company_profile(
    session: Session,
    company: str,
    *,
    refresh: bool = False,
    fetch_website: bool = False,
    website: str | None = None,
    job: Job | None = None,
    profile: CandidateProfile | None = None,
    settings: Settings | None = None,
) -> CompanyResearch:
    """Return the cited company profile, rebuilding it only when it is out of date.

    ``website`` is a URL the user supplied; it is stored but fetched only when
    ``fetch_website`` is true and ``company_research_external`` is enabled — otherwise
    :class:`ExternalResearchRefused` is raised, so a request for external data never
    silently returns without it. ``job`` and ``profile`` add the job-specific context.
    """
    settings = settings or get_settings()
    company_normalized = normalize_company(company) or collapse_whitespace(company).lower()
    if not company_normalized:
        raise ValueError("a company name is required")

    supplied_website = (website or "").strip()
    if supplied_website and not inspect_url(supplied_website).safe:
        reason = inspect_url(supplied_website).reason
        raise ExternalResearchRefused("unsafe_url", f"The website URL was rejected: {reason}.")

    row = session.scalar(
        select(CompanyProfile).where(CompanyProfile.company_normalized == company_normalized)
    )
    known_website = supplied_website or (row.website if row is not None else "")

    if fetch_website:
        if not settings.company_research_external:
            raise ExternalResearchRefused(
                "external_research_disabled",
                "Fetching a company website is off. Set JA_COMPANY_RESEARCH_EXTERNAL=true "
                "to allow it; research from the listings still works without it.",
            )
        if not known_website:
            raise ExternalResearchRefused(
                "website_unknown",
                "No website URL is known for this company. Supply one: JobOrbit never "
                "guesses a company's website from its name.",
            )

    website_changed = row is not None and bool(supplied_website) and supplied_website != row.website
    needs_build = (
        row is None
        or refresh
        or fetch_website
        or website_changed
        or _is_stale(row, session, company_normalized)
    )

    if needs_build:
        jobs = _listings(session, company_normalized)
        names = Counter(job.company for job in jobs if job.company)
        display_name = names.most_common(1)[0][0] if names else collapse_whitespace(company)

        previous_site = (row.data or {}).get("website") if row is not None else None
        website_data: dict[str, Any] | None = None
        if fetch_website:
            website_data = fetch_website_summary(
                known_website, timeout_seconds=settings.ats_timeout_seconds
            )
        elif previous_site and previous_site.get("url") == known_website:
            website_data = previous_site  # keep the earlier fetch, with its own date
        elif known_website:
            website_data = {
                "url": known_website,
                "fetched_at": None,
                "note": "supplied by you; not fetched",
            }

        data, sources = _build_company_data(jobs, display_name, website_data)
        if row is None:
            row = CompanyProfile(company_normalized=company_normalized)
            session.add(row)
        row.display_name = display_name
        row.website = known_website
        row.data = data
        row.sources = sources
        row.refreshed_at = utcnow()
        session.flush()

    assert row is not None
    context = job_context(job, row, profile) if job is not None else None
    return CompanyResearch(profile=row, from_cache=not needs_build, job_context=context)


# --------------------------------------------------------------------------------------
# Job-specific context
# --------------------------------------------------------------------------------------


def project_skills(project: dict[str, Any]) -> list[str]:
    """Skills a project states: its technology list plus vocabulary hits in its own text.

    Sentence punctuation is dropped first, because the shared vocabulary scan keeps "."
    (for "node.js") and would otherwise miss the last skill in "built with PostgreSQL."
    """
    stated = [str(item) for item in project.get("technologies") or []]
    text = f"{project.get('name', '')} {project.get('description', '')}"
    text = re.sub(r"[.,;:!?)](?=\s|$)", " ", text)
    return canonical_skills(stated + extract_skills_from_description(text))


def relevant_projects(
    profile: CandidateProfile | None, job_skills: list[str]
) -> list[dict[str, Any]]:
    """Your own projects whose stated technologies or description overlap the job's skills."""
    if profile is None:
        return []
    wanted = set(job_skills)
    results: list[dict[str, Any]] = []
    for project in profile.projects or []:
        if not isinstance(project, dict) or not project.get("name"):
            continue
        overlap = [skill for skill in project_skills(project) if skill in wanted]
        if not overlap:
            continue
        results.append(
            {
                "name": str(project.get("name")),
                "overlap": overlap,
                "quote": _clip(str(project.get("description") or ""), 300),
                "source": PROFILE_SOURCE,
            }
        )
    results.sort(key=lambda item: -len(item["overlap"]))
    return results


def job_context(job: Job, row: CompanyProfile, profile: CandidateProfile | None) -> dict[str, Any]:
    """Requirements of one job, your relevant projects, and topics derived from them."""
    source = _job_source(job)
    evidence = analyse_description(job.description)
    required = canonical_skills(list(job.required_skills) + evidence.required)
    preferred = [
        skill
        for skill in canonical_skills(list(job.preferred_skills) + evidence.preferred)
        if skill not in required
    ]

    def _skill_fact(skill: str, level: str) -> dict[str, Any]:
        quote = evidence.spans.get(skill, "")
        where = "listing text" if quote else "the listing's skill list"
        return {"skill": skill, "level": level, "quote": quote, "where": where, "source": source}

    requirements: dict[str, Any] = {
        "required_skills": [_skill_fact(skill, "required") for skill in required],
        "preferred_skills": [_skill_fact(skill, "preferred") for skill in preferred],
        "experience": (
            {
                "quote": evidence.years_phrase or job.experience_raw,
                "source": source,
            }
            if (evidence.years_phrase or job.experience_raw)
            else None
        ),
        "education": [{"quote": item, "source": source} for item in job.education_requirements],
    }

    topics: list[dict[str, Any]] = []
    for skill in required:
        topics.append(
            {
                "topic": f"{skill}: fundamentals and how it would be used in this role",
                "derived_from": f"required skill '{skill}' in this listing",
                "source": source,
            }
        )
    for skill in preferred[:5]:
        topics.append(
            {
                "topic": f"{skill}: working knowledge (listed as preferred)",
                "derived_from": f"preferred skill '{skill}' in this listing",
                "source": source,
            }
        )
    if requirements["experience"]:
        topics.append(
            {
                "topic": "Examples that show the experience the listing asks for",
                "derived_from": f"experience requirement: '{requirements['experience']['quote']}'",
                "source": source,
            }
        )
    for theme in engineering_focus([(job.description, source)]):
        topics.append(
            {
                "topic": f"{theme['theme']} — be ready to discuss trade-offs",
                "derived_from": "listing mentions " + ", ".join(f"'{p}'" for p in theme["phrases"]),
                "source": source,
            }
        )

    return {
        "job_id": job.id,
        "title": job.title,
        "source": source,
        "requirements": requirements,
        "relevant_projects": relevant_projects(profile, required + preferred + _job_skills(job)),
        "interview_topics": topics,
        "company_profile_refreshed_at": _iso(row.refreshed_at),
    }


__all__ = [
    "ENGINEERING_THEMES",
    "NOT_STATED",
    "CompanyResearch",
    "ExternalResearchRefused",
    "about_sections",
    "build_company_profile",
    "engineering_focus",
    "fetch_website_summary",
    "is_heading",
    "job_context",
    "parse_page_head",
    "project_skills",
    "relevant_projects",
]
