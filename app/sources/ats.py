"""ATS job-board adapters — the only sources with real automated discovery.

Greenhouse, Lever and Workable each publish an unauthenticated endpoint whose documented
purpose is to serve a company's own job board to anyone, which is what the companies'
careers pages themselves call. Reading it is the intended use, needs no credentials, and
bypasses nothing — so these three are the only adapters in the project with
``authorized_discovery_enabled``.

Verification status at the time of writing, established by calling each endpoint:

* **Greenhouse** — verified against a live board returning real postings, including the
  ``first_published`` field, which gives a genuine posting date rather than a discovery
  date.
* **Lever** — verified against a live board returning real postings.
* **Workable** — the endpoint responds with the documented envelope, but every account
  tried returned an empty ``jobs`` array, so the per-job field mapping below is written
  from the documented field names and has **not** been confirmed against a populated
  board. It is implemented defensively and reports zero jobs honestly rather than
  guessing.

Discovery is opt-in per company: nothing is fetched until you list board identifiers in
``JA_GREENHOUSE_BOARDS``, ``JA_LEVER_BOARDS`` or ``JA_WORKABLE_BOARDS``. There is no
built-in company list, because shipping one would turn a targeted lookup into a crawl.
"""

from __future__ import annotations

from typing import Any

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
from app.sources.http_fetch import (
    BoardFetch,
    build_record,
    fetch_json,
    parse_epoch_millis,
    parse_iso,
    usable_records,
)

logger = get_logger(__name__)


class AtsBoardAdapter(SourceAdapter):
    """Shared fetch loop for the public board APIs."""

    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=True,
        browser_assistance_enabled=False,
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def board_url(self, board: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        raise NotImplementedError  # pragma: no cover - overridden

    def next_page_url(self, board: str, payload: Any, page: int) -> str | None:
        """URL of the page after ``payload``, or ``None`` when the board is single-page.

        Returning ``None`` by default keeps every existing adapter at exactly one
        request per board; only adapters whose API documents paging override this.
        """
        return None

    def configured_boards(self, query: dict[str, object] | None) -> list[str]:
        requested = (query or {}).get("boards")
        if isinstance(requested, str):
            requested = [requested]
        if isinstance(requested, list | tuple):
            cleaned = [str(item).strip().strip("/") for item in requested]
            return [item for item in cleaned if item]
        return list(self._settings.board_tokens(self.source.value))

    def _fetch_url(self, url: str, board: str) -> BoardFetch:
        return fetch_json(
            url,
            board=board,
            display_name=self.display_name,
            timeout_seconds=self._settings.ats_timeout_seconds,
            max_attempts=self._settings.ats_max_attempts,
        )

    def _fetch(self, board: str) -> BoardFetch:
        return self._fetch_url(self.board_url(board), board)

    def _collect_board(self, board: str) -> tuple[list[RawJobRecord], int, str, int]:
        """Walk one board's pages, returning (records, skipped, error, pages_read)."""
        records: list[RawJobRecord] = []
        skipped = 0
        url: str | None = self.board_url(board)
        pages = 0
        max_pages = max(1, self._settings.ats_max_pages)
        while url and pages < max_pages:
            fetched = self._fetch_url(url, board)
            if fetched.error:
                if pages:
                    return records, skipped, "", pages
                return [], 0, fetched.error, 0
            pages += 1
            try:
                parsed, page_skipped = self.parse_board(board, fetched.payload)
            except (TypeError, ValueError, AttributeError) as exc:
                if pages > 1:
                    return records, skipped, "", pages
                return [], 0, f"the response shape was not understood ({exc})", 0
            records.extend(parsed)
            skipped += page_skipped
            if not parsed:
                break
            url = self.next_page_url(board, fetched.payload, pages)
        return records, skipped, "", pages

    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        if not self._settings.ats_discovery_enabled:
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                "ATS discovery is switched off. Set JA_ATS_DISCOVERY_ENABLED=true to use it.",
            )
        boards = self.configured_boards(query)
        if not boards:
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                f"No {self.display_name} boards are configured, so there is nothing to "
                f"fetch. List company board identifiers in {self.env_var}, for example "
                f"{self.env_var}={self.example_board}.",
            )

        records: list[RawJobRecord] = []
        errors: list[str] = []
        invalid = 0
        per_board: dict[str, int] = {}
        pages_per_board: dict[str, int] = {}

        for board in boards:
            board_records, skipped, error, pages = self._collect_board(board)
            if error:
                errors.append(f"{board}: {error}")
                continue
            records.extend(board_records)
            invalid += skipped
            per_board[board] = len(board_records)
            pages_per_board[board] = pages

        if not records and errors and len(errors) == len(boards):
            raise SourceUnavailable(
                self.source,
                f"every configured {self.display_name} board failed: " + "; ".join(errors[:4]),
            )

        logger.info(
            "ats discovery finished",
            extra={
                "source": self.source.value,
                "boards": len(boards),
                "records": len(records),
                "errors": len(errors),
                "pages": sum(pages_per_board.values()),
            },
        )
        return DiscoveryResult(
            records=records,
            errors=errors,
            invalid_count=invalid,
            metadata={
                "boards_requested": boards,
                "jobs_per_board": per_board,
                "pages_per_board": pages_per_board,
                "endpoint": self.board_url(boards[0]) if boards else "",
            },
        )

    env_var: str = ""
    example_board: str = ""


class GreenhouseAdapter(AtsBoardAdapter):
    source = SourceName.GREENHOUSE
    display_name = "Greenhouse"
    policy_basis = (
        "Greenhouse publishes an unauthenticated Job Board API at boards-api.greenhouse.io "
        "whose documented purpose is to serve a company's own board; it is the same "
        "endpoint the company's careers page uses. No credentials, no scraping, no "
        "circumvention."
    )
    limitations = (
        "Only companies whose board identifier you configure are queried; there is no "
        "directory lookup.",
        "The board API has no free-text search, so filtering happens locally after import.",
    )
    env_var = "JA_GREENHOUSE_BOARDS"
    example_board = "dropbox"

    def board_url(self, board: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        jobs = (payload or {}).get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("expected an object with a 'jobs' array")
        records: list[RawJobRecord | None] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("absolute_url", "")).strip()
            if not title or not url:
                skipped += 1
                continue
            location = entry.get("location") or {}
            offices = entry.get("offices") or []
            location_name = (
                str(location.get("name", "")).strip() if isinstance(location, dict) else ""
            )
            if not location_name and isinstance(offices, list) and offices:
                first = offices[0]
                if isinstance(first, dict):
                    location_name = str(first.get("name", "")).strip()
            records.append(
                build_record(
                    source=self.source,
                    external_id=str(entry.get("id") or entry.get("internal_job_id") or "").strip()
                    or None,
                    title=title,
                    company=str(entry.get("company_name", "")).strip() or board,
                    location=location_name,
                    url=url,
                    description=strip_html(str(entry.get("content", "")))[:20000],
                    posted_at=parse_iso(entry.get("first_published"))
                    or parse_iso(entry.get("updated_at")),
                    retrieval_method="greenhouse_job_board_api",
                    source_metadata={
                        "board": board,
                        "requisition_id": entry.get("requisition_id"),
                        "departments": [
                            str(dept.get("name", ""))
                            for dept in (entry.get("departments") or [])
                            if isinstance(dept, dict)
                        ][:5],
                    },
                )
            )
        return usable_records(records, skipped)


class LeverAdapter(AtsBoardAdapter):
    source = SourceName.LEVER
    display_name = "Lever"
    policy_basis = (
        "Lever publishes an unauthenticated Postings API at api.lever.co/v0/postings/<site> "
        "intended for a company to render or syndicate its own board. It requires no "
        "credentials and is the documented public interface."
    )
    limitations = (
        "Only the company sites you configure are queried.",
        "Lever returns a creation timestamp rather than a publish date; it is used as the "
        "posting date and is accurate for most boards.",
    )
    env_var = "JA_LEVER_BOARDS"
    example_board = "spotify"

    def board_url(self, board: str) -> str:
        return f"https://api.lever.co/v0/postings/{board}?mode=json"

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, list):
            raise ValueError("expected a JSON array of postings")
        records: list[RawJobRecord | None] = []
        skipped = 0
        for entry in payload:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("text", "")).strip()
            url = str(entry.get("hostedUrl") or entry.get("applyUrl") or "").strip()
            if not title or not url:
                skipped += 1
                continue
            categories = entry.get("categories") or {}
            if not isinstance(categories, dict):
                categories = {}
            description = str(entry.get("descriptionPlain") or entry.get("description") or "")
            extra = str(entry.get("additionalPlain") or "")
            records.append(
                build_record(
                    source=self.source,
                    external_id=str(entry.get("id", "")).strip() or None,
                    title=title,
                    company=board,
                    location=str(categories.get("location", "")).strip(),
                    url=url,
                    description=strip_html(f"{description}\n\n{extra}".strip())[:20000],
                    employment_type=str(categories.get("commitment", "")).strip(),
                    posted_at=parse_epoch_millis(entry.get("createdAt")),
                    retrieval_method="lever_postings_api",
                    source_metadata={
                        "board": board,
                        "team": categories.get("team"),
                        "department": categories.get("department"),
                        "workplace_type": entry.get("workplaceType"),
                    },
                )
            )
        return usable_records(records, skipped)


class WorkableAdapter(AtsBoardAdapter):
    source = SourceName.WORKABLE
    display_name = "Workable"
    policy_basis = (
        "Workable publishes an unauthenticated account widget endpoint at "
        "apply.workable.com/api/v1/widget/accounts/<subdomain> that companies embed in "
        "their own careers pages. No credentials and no circumvention are involved."
    )
    limitations = (
        "The endpoint responds correctly, but no populated board was available to verify "
        "the per-job field names, so this adapter is implemented from the documented "
        "fields and may report zero jobs on a board that actually has some. It never "
        "invents a listing.",
        "Only the subdomains you configure are queried.",
    )
    env_var = "JA_WORKABLE_BOARDS"
    example_board = "yourcompany"

    def board_url(self, board: str) -> str:
        return f"https://apply.workable.com/api/v1/widget/accounts/{board}?details=true"

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'jobs' array")
        jobs = payload.get("jobs")
        if jobs is None:
            jobs = []
        if not isinstance(jobs, list):
            raise ValueError("'jobs' was present but was not an array")
        company = str(payload.get("name", "")).strip() or board
        records: list[RawJobRecord | None] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(
                entry.get("url") or entry.get("shortlink") or entry.get("application_url") or ""
            ).strip()
            if not title or not url:
                skipped += 1
                continue
            records.append(
                build_record(
                    source=self.source,
                    external_id=str(entry.get("shortcode") or entry.get("code") or "").strip()
                    or None,
                    title=title,
                    company=company,
                    location=_workable_location(entry),
                    url=url,
                    description=strip_html(str(entry.get("description", "")))[:20000],
                    employment_type=str(entry.get("employment_type", "")).strip(),
                    work_arrangement="remote" if entry.get("telecommuting") else "",
                    experience_raw=str(entry.get("experience", "")).strip()[:200],
                    education_requirements=_workable_education(entry),
                    posted_at=parse_iso(entry.get("published_on") or entry.get("created_at")),
                    retrieval_method="workable_widget_api",
                    source_metadata={
                        "board": board,
                        "department": entry.get("department"),
                        "function": entry.get("function"),
                    },
                )
            )
        return usable_records(records, skipped)


def _workable_education(entry: dict[str, Any]) -> list[str]:
    """Workable sends the literal string "None" when no degree is required."""
    value = str(entry.get("education", "") or "").strip()
    if not value or value.lower() in {"none", "n/a", "not applicable"}:
        return []
    return [value[:200]]


def _workable_location(entry: dict[str, Any]) -> str:
    """Join a Workable job's place fields into one string.

    Workable does not nest location in an object: it exposes flat ``city``, ``state`` and
    ``country`` keys, plus a ``locations`` array for multi-site roles. Reading a
    ``location`` dict - which is what Greenhouse does - yielded an empty string for every
    Workable job, which silently zeroed location scoring and weakened deduplication.
    """
    parts = [
        str(entry.get(key, "")).strip()
        for key in ("city", "state", "country")
        if str(entry.get(key, "")).strip()
    ]
    if parts:
        return ", ".join(dict.fromkeys(parts))

    locations = entry.get("locations")
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            nested = [
                str(first.get(key, "") or "").strip()
                for key in ("city", "region", "country")
                if str(first.get(key, "") or "").strip()
            ]
            if nested:
                return ", ".join(dict.fromkeys(nested))
    return "Remote" if entry.get("telecommuting") else ""


#: Ashby publishes its own employment-type vocabulary. Only ``Intern`` fails to match the
#: hints in ``normalization._EMPLOYMENT_HINTS`` ("intern" alone is deliberately not a hint,
#: because it appears inside unrelated words), so it is mapped to the word that does.
_ASHBY_EMPLOYMENT = {"Intern": "internship"}


class AshbyAdapter(AtsBoardAdapter):
    source = SourceName.ASHBY
    display_name = "Ashby"
    policy_basis = (
        "Ashby publishes an unauthenticated Posting API at "
        "api.ashbyhq.com/posting-api/job-board/<slug> whose documented purpose is to let a "
        "company serve or syndicate its own job board; it is the same data the company's "
        "Ashby-hosted careers page renders. No credentials, no scraping, no circumvention."
    )
    limitations = (
        "Only companies whose board slug you configure are queried; there is no directory lookup.",
        "The API returns the whole board in one response and offers no server-side search, "
        "so filtering happens locally after import.",
        "Postings flagged isListed=false are skipped: the company has not published them.",
    )
    env_var = "JA_ASHBY_BOARDS"
    example_board = "ramp"

    def board_url(self, board: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{board}"

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'jobs' array")
        jobs = payload.get("jobs")
        if jobs is None:
            jobs = []
        if not isinstance(jobs, list):
            raise ValueError("'jobs' was present but was not an array")

        records: list[RawJobRecord | None] = []
        skipped = 0
        for entry in jobs:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("jobUrl") or entry.get("applyUrl") or "").strip()
            if not title or not url or entry.get("isListed") is False:
                skipped += 1
                continue
            employment = str(entry.get("employmentType", "")).strip()
            records.append(
                build_record(
                    source=self.source,
                    external_id=str(entry.get("id", "")).strip() or None,
                    title=title,
                    company=board,
                    location=_ashby_location(entry),
                    url=url,
                    description=_ashby_description(entry),
                    employment_type=_ASHBY_EMPLOYMENT.get(employment, employment),
                    work_arrangement=str(entry.get("workplaceType", "")).strip(),
                    posted_at=parse_iso(entry.get("publishedAt")),
                    retrieval_method="ashby_posting_api",
                    source_metadata={
                        "board": board,
                        "department": entry.get("department"),
                        "team": entry.get("team"),
                        "is_remote": entry.get("isRemote"),
                    },
                )
            )
        return usable_records(records, skipped)


def _ashby_description(entry: dict[str, Any]) -> str:
    plain = str(entry.get("descriptionPlain", "") or "").strip()
    if plain:
        return plain[:20000]
    return strip_html(str(entry.get("descriptionHtml", "") or ""))[:20000]


def _ashby_location(entry: dict[str, Any]) -> str:
    """Ashby's primary ``location`` is a flat string, with extra sites in a sibling array."""
    primary = str(entry.get("location", "") or "").strip()
    if primary:
        return primary
    secondary = entry.get("secondaryLocations")
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, dict):
                nested = str(item.get("location", "") or "").strip()
                if nested:
                    return nested
    return "Remote" if entry.get("isRemote") else ""


class SmartRecruitersAdapter(AtsBoardAdapter):
    source = SourceName.SMARTRECRUITERS
    display_name = "SmartRecruiters"
    policy_basis = (
        "SmartRecruiters publishes an unauthenticated Posting API at "
        "api.smartrecruiters.com/v1/companies/<identifier>/postings, documented as the "
        "public feed of a company's own advertised jobs and used by its own careers site. "
        "Only postings the company marked visibility=PUBLIC are read."
    )
    limitations = (
        "Only companies whose identifier you configure are queried.",
        "The postings list carries no job description; each one costs an extra request to "
        "the per-posting endpoint, so the number fetched per run is capped by "
        "JA_SMARTRECRUITERS_DETAIL_LIMIT. Postings beyond the cap are still imported, but "
        "with an empty description, and score as sparse rather than as a false match.",
    )
    env_var = "JA_SMARTRECRUITERS_BOARDS"
    example_board = "BoschGroup"

    _PAGE_SIZE = 100

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        self._details_remaining = 0

    def board_url(self, board: str) -> str:
        return (
            f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
            f"?limit={self._PAGE_SIZE}&offset=0"
        )

    def next_page_url(self, board: str, payload: Any, page: int) -> str | None:
        if not isinstance(payload, dict):
            return None
        total = payload.get("totalFound")
        offset = page * self._PAGE_SIZE
        if not isinstance(total, int) or offset >= total:
            return None
        return (
            f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
            f"?limit={self._PAGE_SIZE}&offset={offset}"
        )

    def _collect_board(self, board: str) -> tuple[list[RawJobRecord], int, str, int]:
        self._details_remaining = self._settings.smartrecruiters_detail_limit
        return super()._collect_board(board)

    def parse_board(self, board: str, payload: Any) -> tuple[list[RawJobRecord], int]:
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object with a 'content' array")
        postings = payload.get("content")
        if postings is None:
            postings = []
        if not isinstance(postings, list):
            raise ValueError("'content' was present but was not an array")

        records: list[RawJobRecord | None] = []
        skipped = 0
        for entry in postings:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = str(entry.get("name", "")).strip()
            posting_id = str(entry.get("id", "")).strip()
            visibility = str(entry.get("visibility", "PUBLIC")).strip().upper()
            if not title or not posting_id or visibility != "PUBLIC":
                skipped += 1
                continue
            company = entry.get("company") or {}
            identifier = (
                str(company.get("identifier", "")).strip() if isinstance(company, dict) else ""
            ) or board
            company_name = (
                str(company.get("name", "")).strip() if isinstance(company, dict) else ""
            ) or board
            location = entry.get("location") or {}
            if not isinstance(location, dict):
                location = {}
            records.append(
                build_record(
                    source=self.source,
                    external_id=posting_id,
                    title=title,
                    company=company_name,
                    location=_smartrecruiters_location(location),
                    url=f"https://jobs.smartrecruiters.com/{identifier}/{posting_id}",
                    description=self._fetch_description(identifier, posting_id),
                    employment_type=_label_of(entry.get("typeOfEmployment")),
                    work_arrangement=_smartrecruiters_arrangement(location),
                    experience_raw=_label_of(entry.get("experienceLevel"))[:200],
                    posted_at=parse_iso(entry.get("releasedDate")),
                    retrieval_method="smartrecruiters_posting_api",
                    source_metadata={
                        "board": board,
                        "function": _label_of(entry.get("function")),
                        "industry": _label_of(entry.get("industry")),
                        "ref_number": entry.get("refNumber"),
                    },
                )
            )
        return usable_records(records, skipped)

    def _fetch_description(self, identifier: str, posting_id: str) -> str:
        """Pull one posting's advert text, within the per-run request budget."""
        if self._details_remaining <= 0:
            return ""
        self._details_remaining -= 1
        url = f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{posting_id}"
        fetched = self._fetch_url(url, identifier)
        if fetched.error or not isinstance(fetched.payload, dict):
            return ""
        sections = ((fetched.payload.get("jobAd") or {}).get("sections")) or {}
        if not isinstance(sections, dict):
            return ""
        parts: list[str] = []
        for key in ("jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key)
            if isinstance(section, dict):
                text = strip_html(str(section.get("text", "") or "")).strip()
                if text:
                    parts.append(text)
        return "\n\n".join(parts)[:20000]


def _label_of(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("label", "") or "").strip()
    return ""


def _smartrecruiters_location(location: dict[str, Any]) -> str:
    """Build a readable place string from a SmartRecruiters posting.

    ``fullLocation`` is preferred because its last segment is the country *name*, whereas
    the sibling ``country`` field is an ISO-2 code: taking the code produced
    ``"bangalore, in"``, which matches no human-entered location preference and silently
    zeroed location scoring for every Indian listing. ``fullLocation`` arrives as
    ``"bangalore, , India"`` when the region is unset, and that blank middle segment has to
    be dropped or it breaks the comma-splitting that location normalization relies on.
    """
    full = str(location.get("fullLocation", "") or "")
    segments = [segment.strip() for segment in full.split(",") if segment.strip()]
    if segments:
        return ", ".join(dict.fromkeys(segments))
    parts = [
        str(location.get(key, "") or "").strip()
        for key in ("city", "region", "country")
        if str(location.get(key, "") or "").strip()
    ]
    return ", ".join(dict.fromkeys(parts))


def _smartrecruiters_arrangement(location: dict[str, Any]) -> str:
    if location.get("remote"):
        return "remote"
    if location.get("hybrid"):
        return "hybrid"
    return ""
