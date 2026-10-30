"""Open job-feed adapters.

These differ from the per-company ATS boards in ``app/sources/ats.py``: each publisher
exposes **one whole-feed endpoint** rather than a board belonging to a single employer, so
there is no board identifier to configure and the whole feed is in scope on every call.
That makes them higher-volume and higher-duplication than an ATS board, and it makes each
publisher's own terms the governing constraint rather than "this is the company's own
board". Every adapter below was written against an observed response, and the publisher's
notice — which each of these APIs returns inside its own payload — is quoted in
``policy_basis``.

Consequences that shaped the design:

* **Every feed is off by default.** ``JA_FEED_DISCOVERY_ENABLED`` plus a per-source switch
  must both be true before a single request is made, because enabling one pulls a global
  feed rather than one employer's jobs.
* **Pages are capped** by ``JA_FEED_MAX_PAGES``. These feeds are large enough that an
  unbounded walk would be indistinguishable from a crawl.
* **Remotive is deliberately single-page**: its notice advises no more than about four
  requests a day, so this adapter never paginates it.
* **Attribution is satisfied structurally.** Several notices require linking back to the
  original listing; the application stores the publisher's own URL and the only apply path
  it offers is opening that URL, so a listing is never re-published or re-hosted.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.config import Settings, get_settings
from app.db.models import SourceName
from app.logging_conf import get_logger
from app.schemas.job import RawJobRecord
from app.services.text import strip_html
from app.sources.base import (
    AdapterCapabilities,
    CapabilityNotAvailable,
    DiscoveryResult,
    SourceAdapter,
    SourceUnavailable,
)
from app.sources.http_fetch import fetch_json, parse_epoch_seconds, parse_iso

logger = get_logger(__name__)


class FeedAdapter(SourceAdapter):
    """Shared paginated fetch loop for whole-feed job APIs."""

    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=True,
        browser_assistance_enabled=False,
    )

    #: Pages this publisher's terms allow per run. ``1`` means "never paginate".
    max_pages: int = 1
    enable_var: str = ""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def feed_url(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        raise NotImplementedError  # pragma: no cover - overridden

    def next_page_url(self, payload: Any, page: int) -> str | None:
        return None

    def _page_budget(self) -> int:
        return max(1, min(self.max_pages, self._settings.feed_max_pages))

    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        if not self._settings.feed_discovery_enabled:
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                "Open job-feed discovery is switched off. Set "
                "JA_FEED_DISCOVERY_ENABLED=true and the per-source switch to use it.",
            )
        if not self._settings.feed_enabled(self.source.value):
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                f"{self.display_name} discovery is switched off. Set "
                f"{self.enable_var}=true to use it. {self.policy_basis}",
            )

        records: list[RawJobRecord] = []
        errors: list[str] = []
        invalid = 0
        url: str | None = self.feed_url()
        pages = 0
        budget = self._page_budget()

        while url and pages < budget:
            fetched = fetch_json(
                url,
                board=self.source.value,
                display_name=self.display_name,
                timeout_seconds=self._settings.ats_timeout_seconds,
                max_attempts=self._settings.ats_max_attempts,
            )
            if fetched.error:
                errors.append(f"page {pages + 1}: {fetched.error}")
                break
            pages += 1
            try:
                parsed, skipped = self.parse_feed(fetched.payload)
            except (TypeError, ValueError, AttributeError) as exc:
                errors.append(f"page {pages}: the response shape was not understood ({exc})")
                break
            records.extend(parsed)
            invalid += skipped
            if not parsed:
                break
            url = self.next_page_url(fetched.payload, pages)

        if not records and errors:
            raise SourceUnavailable(
                self.source, f"{self.display_name} returned no jobs: " + "; ".join(errors[:3])
            )

        logger.info(
            "feed discovery finished",
            extra={
                "source": self.source.value,
                "records": len(records),
                "pages": pages,
                "errors": len(errors),
            },
        )
        return DiscoveryResult(
            records=records,
            errors=errors,
            invalid_count=invalid,
            metadata={
                "pages_read": pages,
                "page_budget": budget,
                "endpoint": self.feed_url(),
            },
        )


class ArbeitnowAdapter(FeedAdapter):
    source = SourceName.ARBEITNOW
    display_name = "Arbeitnow"
    policy_basis = (
        "Arbeitnow publishes a free public job-board API at "
        "arbeitnow.com/api/job-board-api. Its own payload states: 'This is a free public "
        "API for jobs, please do not abuse. I would appreciate linking back to the site.' "
        "Paging is documented via '?page='. No credentials and no circumvention."
    )
    limitations = (
        "Coverage is weighted towards Germany, the wider EU and remote roles, so it adds "
        "little for on-site Indian listings.",
        "It is an aggregator, so expect heavy duplication against ATS boards; the existing "
        "fingerprint deduplication merges those into one job with several source "
        "references.",
        "Many entries carry an empty location and no employment type.",
    )
    enable_var = "JA_ARBEITNOW_ENABLED"
    max_pages = 10

    def feed_url(self) -> str:
        return "https://www.arbeitnow.com/api/job-board-api"

    def next_page_url(self, payload: Any, page: int) -> str | None:
        if not isinstance(payload, dict):
            return None
        links = payload.get("links")
        if not isinstance(links, dict):
            return None
        nxt = links.get("next")
        return nxt.strip() if isinstance(nxt, str) and nxt.strip() else None

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'data' array")
        entries = payload.get("data")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise ValueError("'data' was present but was not an array")

        records: list[RawJobRecord] = []
        skipped = 0
        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            company = str(entry.get("company_name", "")).strip()
            if not title or not url or not company:
                skipped += 1
                continue
            job_types = entry.get("job_types")
            records.append(
                RawJobRecord(
                    source=self.source,
                    external_id=str(entry.get("slug", "")).strip() or None,
                    title=title,
                    company=company,
                    location=str(entry.get("location", "") or "").strip(),
                    url=url,
                    description=strip_html(str(entry.get("description", "") or ""))[:20000],
                    employment_type=_first_text(job_types),
                    work_arrangement="remote" if entry.get("remote") else "",
                    preferred_skills=_string_list(entry.get("tags"))[:20],
                    posted_at=parse_epoch_seconds(entry.get("created_at")),
                    retrieval_method="arbeitnow_job_board_api",
                    source_metadata={"tags": _string_list(entry.get("tags"))[:10]},
                )
            )
        return records, skipped


class RemoteOkAdapter(FeedAdapter):
    source = SourceName.REMOTEOK
    display_name = "Remote OK"
    policy_basis = (
        "Remote OK publishes an unauthenticated feed at remoteok.com/api. Its own payload "
        "requires linking back to the listing URL on Remote OK and crediting Remote OK as "
        "the source; this application stores that URL and its only apply path is opening "
        "it, so listings are never re-hosted. The feed is one page and is not paginated."
    )
    limitations = (
        "Remote-only by definition, so it adds nothing for on-site roles.",
        "The first element of the response is a legal/metadata object rather than a job and "
        "is skipped; it is not counted as an invalid row.",
        "Remote OK's terms are about display and attribution, so republishing these "
        "listings anywhere would need their permission. Reading them for one person's own "
        "job search is what this adapter does.",
    )
    enable_var = "JA_REMOTEOK_ENABLED"
    max_pages = 1

    def feed_url(self) -> str:
        return "https://remoteok.com/api"

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, list):
            raise ValueError("expected a JSON array of postings")
        records: list[RawJobRecord] = []
        skipped = 0
        for entry in payload:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            if "legal" in entry and "position" not in entry:
                continue
            title = str(entry.get("position", "")).strip()
            url = str(entry.get("url") or entry.get("apply_url") or "").strip()
            company = str(entry.get("company", "")).strip()
            if not title or not url or not company:
                skipped += 1
                continue
            records.append(
                RawJobRecord(
                    source=self.source,
                    external_id=str(entry.get("id", "")).strip() or None,
                    title=title,
                    company=company,
                    location=str(entry.get("location", "") or "").strip(),
                    url=url,
                    description=strip_html(str(entry.get("description", "") or ""))[:20000],
                    work_arrangement="remote",
                    preferred_skills=_string_list(entry.get("tags"))[:20],
                    posted_at=parse_iso(entry.get("date"))
                    or parse_epoch_seconds(entry.get("epoch")),
                    retrieval_method="remoteok_public_api",
                    source_metadata={
                        "tags": _string_list(entry.get("tags"))[:10],
                        "salary_min": entry.get("salary_min"),
                        "salary_max": entry.get("salary_max"),
                    },
                )
            )
        return records, skipped


class RemotiveAdapter(FeedAdapter):
    source = SourceName.REMOTIVE
    display_name = "Remotive"
    policy_basis = (
        "Remotive publishes an unauthenticated feed at remotive.com/api/remote-jobs. Its "
        "own payload grants API access so developers can share its jobs further, requires "
        "linking back to the Remotive URL and crediting Remotive, and advises no more than "
        "about four requests a day. This adapter therefore makes exactly one request per "
        "run and never paginates."
    )
    limitations = (
        "The public feed is small: twelve jobs were returned when this adapter was "
        "verified, against a much larger site. Remotive gates bulk access behind a paid "
        "API, which this project does not use.",
        "Listings are delayed by about 24 hours by Remotive, so freshness scoring is "
        "systematically one day pessimistic for this source.",
        "Remote-only, and its terms forbid re-submitting its jobs to other job sites.",
    )
    enable_var = "JA_REMOTIVE_ENABLED"
    max_pages = 1

    def feed_url(self) -> str:
        return "https://remotive.com/api/remote-jobs"

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'jobs' array")
        jobs = payload.get("jobs")
        if jobs is None:
            jobs = []
        if not isinstance(jobs, list):
            raise ValueError("'jobs' was present but was not an array")

        records: list[RawJobRecord] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            company = str(entry.get("company_name", "")).strip()
            if not title or not url or not company:
                skipped += 1
                continue
            records.append(
                RawJobRecord(
                    source=self.source,
                    external_id=str(entry.get("id", "")).strip() or None,
                    title=title,
                    company=company,
                    location=str(entry.get("candidate_required_location", "") or "").strip(),
                    url=url,
                    description=strip_html(str(entry.get("description", "") or ""))[:20000],
                    employment_type=str(entry.get("job_type", "") or "").replace("_", " ").strip(),
                    work_arrangement="remote",
                    salary_raw=str(entry.get("salary", "") or "").strip()[:200],
                    preferred_skills=_string_list(entry.get("tags"))[:20],
                    posted_at=parse_iso(entry.get("publication_date")),
                    retrieval_method="remotive_public_api",
                    source_metadata={"category": entry.get("category")},
                )
            )
        return records, skipped


class HimalayasAdapter(FeedAdapter):
    source = SourceName.HIMALAYAS
    display_name = "Himalayas"
    policy_basis = (
        "Himalayas publishes an unauthenticated feed at himalayas.app/jobs/api. Its own "
        "payload documents cursor paging as the supported way to walk the feed: 'Pass the "
        "nextCursor value from each response back as ?cursor='. No credentials are used."
    )
    limitations = (
        "Remote-only, with the stated location expressed as a restriction list (for "
        "example ['United States']) rather than a place of work.",
        "A page returns at most twenty jobs regardless of the requested limit, so the page "
        "budget governs how much of the feed is read.",
        "The feed carries no stable numeric id, so the listing URL is used as the external "
        "identifier.",
    )
    enable_var = "JA_HIMALAYAS_ENABLED"
    max_pages = 10

    _PAGE_SIZE = 20

    def feed_url(self) -> str:
        return f"https://himalayas.app/jobs/api?limit={self._PAGE_SIZE}"

    def next_page_url(self, payload: Any, page: int) -> str | None:
        if not isinstance(payload, dict):
            return None
        cursor = payload.get("nextCursor")
        if not isinstance(cursor, str) or not cursor.strip():
            return None
        return (
            f"https://himalayas.app/jobs/api?limit={self._PAGE_SIZE}"
            f"&cursor={quote(cursor.strip(), safe='')}"
        )

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'jobs' array")
        jobs = payload.get("jobs")
        if jobs is None:
            jobs = []
        if not isinstance(jobs, list):
            raise ValueError("'jobs' was present but was not an array")

        records: list[RawJobRecord] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("applicationLink") or entry.get("guid") or "").strip()
            company = str(entry.get("companyName", "")).strip()
            if not title or not url or not company:
                skipped += 1
                continue
            description = str(entry.get("description", "") or "")
            if not description.strip():
                description = str(entry.get("excerpt", "") or "")
            records.append(
                RawJobRecord(
                    source=self.source,
                    external_id=str(entry.get("guid", "")).strip() or None,
                    title=title,
                    company=company,
                    location=", ".join(_string_list(entry.get("locationRestrictions"))[:3]),
                    url=url,
                    description=strip_html(description)[:20000],
                    employment_type=str(entry.get("employmentType", "") or "").strip(),
                    work_arrangement="remote",
                    experience_raw=", ".join(_string_list(entry.get("seniority"))[:3])[:200],
                    preferred_skills=_string_list(entry.get("categories"))[:20],
                    posted_at=parse_epoch_seconds(entry.get("pubDate")),
                    retrieval_method="himalayas_public_api",
                    source_metadata={
                        "company_slug": entry.get("companySlug"),
                        "seniority": _string_list(entry.get("seniority"))[:5],
                    },
                )
            )
        return records, skipped


class JobicyAdapter(FeedAdapter):
    source = SourceName.JOBICY
    display_name = "Jobicy"
    policy_basis = (
        "Jobicy publishes an unauthenticated feed at jobicy.com/api/v2/remote-jobs, "
        "documented at jobi.cy/apidocs. Its own payload asks that Jobicy be credited with "
        "a direct link to the source and that every apply button redirect to the original "
        "job URL in the feed, which is exactly what this application does."
    )
    limitations = (
        "Remote-only, with a coarse geography string such as 'USA' rather than a city.",
        "Cursor paging is used; the page budget governs how much of the feed is read.",
    )
    enable_var = "JA_JOBICY_ENABLED"
    max_pages = 10

    _PAGE_SIZE = 50

    def feed_url(self) -> str:
        return f"https://jobicy.com/api/v2/remote-jobs?count={self._PAGE_SIZE}"

    def next_page_url(self, payload: Any, page: int) -> str | None:
        if not isinstance(payload, dict) or not payload.get("hasMore"):
            return None
        cursor = payload.get("nextCursor")
        if not isinstance(cursor, str) or not cursor.strip():
            return None
        return (
            f"https://jobicy.com/api/v2/remote-jobs?count={self._PAGE_SIZE}"
            f"&cursor={quote(cursor.strip(), safe='')}"
        )

    def parse_feed(self, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'jobs' array")
        jobs = payload.get("jobs")
        if jobs is None:
            jobs = []
        if not isinstance(jobs, list):
            raise ValueError("'jobs' was present but was not an array")

        records: list[RawJobRecord] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("jobTitle", "")).strip()
            url = str(entry.get("url", "")).strip()
            company = str(entry.get("companyName", "")).strip()
            if not title or not url or not company:
                skipped += 1
                continue
            description = str(entry.get("jobDescription", "") or "")
            if not description.strip():
                description = str(entry.get("jobExcerpt", "") or "")
            records.append(
                RawJobRecord(
                    source=self.source,
                    external_id=str(entry.get("id", "")).strip() or None,
                    title=title,
                    company=company,
                    location=str(entry.get("jobGeo", "") or "").strip(),
                    url=url,
                    description=strip_html(description)[:20000],
                    employment_type=_first_text(entry.get("jobType")),
                    work_arrangement="remote",
                    experience_raw=str(entry.get("jobLevel", "") or "").strip()[:200],
                    preferred_skills=_string_list(entry.get("jobIndustry"))[:20],
                    posted_at=parse_iso(entry.get("pubDate")),
                    retrieval_method="jobicy_public_api_v2",
                    source_metadata={"job_level": entry.get("jobLevel")},
                )
            )
        return records, skipped


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _first_text(value: Any) -> str:
    items = _string_list(value)
    return items[0] if items else ""
