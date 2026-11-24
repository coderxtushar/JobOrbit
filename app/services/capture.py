"""User-initiated job capture.

A listing captured by the browser extension enters the same pipeline as a file import:
it becomes a :class:`RawJobRecord`, :class:`JobIngestService` deduplicates and stores it
with a :class:`JobSourceReference`, and :class:`ScoringService` scores it against the
profile. Nothing here fetches a page: the only content is what the user's own browser
showed them and what they chose to send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, EmploymentType, Job, SourceName, utcnow
from app.db.repositories import AuditRepository, JobRepository, MatchRepository
from app.schemas.capture import CaptureRequest, CaptureResult
from app.schemas.job import RawJobRecord
from app.services.dedup import fingerprint_for_values
from app.services.ingest import JobIngestService
from app.services.normalization import normalize_record
from app.services.scoring import ScoringService

RETRIEVAL_METHOD = "user_capture"
TRIGGER = "browser_extension"
EXPLANATION_LINES = 5

#: Host suffix -> source. A host matches when it equals the suffix or ends with
#: ``.<suffix>``, so ``in.linkedin.com`` is LinkedIn but ``notlinkedin.com`` is not.
_HOST_SOURCES: tuple[tuple[str, SourceName], ...] = (
    ("linkedin.com", SourceName.LINKEDIN),
    ("naukri.com", SourceName.NAUKRI),
    ("wellfound.com", SourceName.WELLFOUND),
    ("angel.co", SourceName.WELLFOUND),
    ("instahyre.com", SourceName.INSTAHYRE),
    ("cutshort.io", SourceName.CUTSHORT),
    ("hirist.tech", SourceName.HIRIST),
    ("hirist.com", SourceName.HIRIST),
    ("greenhouse.io", SourceName.GREENHOUSE),
    ("lever.co", SourceName.LEVER),
    ("workable.com", SourceName.WORKABLE),
    ("ashbyhq.com", SourceName.ASHBY),
    ("smartrecruiters.com", SourceName.SMARTRECRUITERS),
    ("myworkdayjobs.com", SourceName.WORKDAY),
)

_EMPLOYMENT_SYNONYMS: dict[str, EmploymentType] = {
    "full_time": EmploymentType.FULL_TIME,
    "fulltime": EmploymentType.FULL_TIME,
    "permanent": EmploymentType.FULL_TIME,
    "part_time": EmploymentType.PART_TIME,
    "parttime": EmploymentType.PART_TIME,
    "intern": EmploymentType.INTERNSHIP,
    "internship": EmploymentType.INTERNSHIP,
    "contract": EmploymentType.CONTRACT,
    "contractor": EmploymentType.CONTRACT,
    "freelance": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "temp": EmploymentType.TEMPORARY,
    "seasonal": EmploymentType.TEMPORARY,
}


def infer_source(url: str) -> SourceName:
    """The platform a URL belongs to, or ``COMPANY_SITE`` for any other site."""
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for suffix, source in _HOST_SOURCES:
        if host == suffix or host.endswith(f".{suffix}"):
            return source
    # Indeed runs one site per country: indeed.com, in.indeed.com, indeed.co.uk, ...
    if re.search(r"(^|\.)indeed\.[a-z.]+$", host):
        return SourceName.INDEED
    return SourceName.COMPANY_SITE


def infer_external_id(source: SourceName, url: str) -> str | None:
    """The platform's own posting id, when the URL carries one unambiguously.

    With it, a second capture of the same posting through a different link (a search page
    with ``currentJobId`` versus the job view) is resolved by ``(source, external_id)``,
    the most reliable duplicate rule the ingest pipeline has.
    """
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if source is SourceName.LINKEDIN:
        found = re.search(r"/jobs/view/(?:[^/]*?-)?(\d{6,})", parts.path)
        if found:
            return found.group(1)
        current = query.get("currentJobId", [""])[0]
        return current if current.isdigit() else None
    if source is SourceName.INDEED:
        value = (query.get("jk") or query.get("vjk") or [""])[0]
        return value if re.fullmatch(r"[0-9a-f]{8,32}", value) else None
    if source is SourceName.NAUKRI:
        found = re.search(r"-(\d{9,})/?$", parts.path)
        return found.group(1) if found else None
    return None


def map_employment_type(raw: str) -> str | None:
    """Map schema.org (``FULL_TIME``) or visible ("Full-time") wording to the enum value.

    ``None`` leaves the decision to normalization, which reads the description.
    """
    for part in re.split(r"[,/|;]", raw or ""):
        key = re.sub(r"[\s\-]+", "_", part.strip().lower())
        if key in _EMPLOYMENT_SYNONYMS:
            return _EMPLOYMENT_SYNONYMS[key].value
    return None


def build_record(payload: CaptureRequest) -> RawJobRecord:
    source = infer_source(payload.url)
    captured_at = payload.captured_at or utcnow()
    metadata: dict[str, Any] = {
        "captured_at": captured_at.isoformat(),
        "extension_version": payload.extension_version,
        "extraction_method": payload.extraction.method,
        "extraction_confidence": payload.extraction.confidence,
        "missing_fields": payload.extraction.missing,
        "field_sources": payload.extraction.field_sources,
        "page_url": payload.page_url or payload.url,
        "source_hint": payload.source_hint,
        "employment_type_raw": payload.employment_type,
        "posted_at_raw": payload.posted_at,
    }
    return RawJobRecord(
        source=source,
        external_id=infer_external_id(source, payload.url),
        title=payload.title,
        company=payload.company,
        location=payload.location,
        url=payload.url,
        employment_type=map_employment_type(payload.employment_type),
        description=payload.description,
        posted_at=payload.posted_at or None,
        retrieval_method=RETRIEVAL_METHOD,
        source_metadata=metadata,
    )


@dataclass(slots=True)
class _Resolved:
    job: Job
    created: bool


class CaptureService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = JobRepository(session)

    def _resolve(self, record: RawJobRecord, created_ids: list[int]) -> _Resolved:
        """Find the job the record landed on, using the ingest pipeline's own order."""
        if created_ids:
            job = self._jobs.get(created_ids[0])
            if job is not None:
                return _Resolved(job, True)

        found: Job | None = None
        if record.external_id:
            found = self._jobs.find_by_source_id(record.source, record.external_id)
        if found is None:
            values = normalize_record(record).values
            found = self._jobs.find_by_canonical_url(values.get("canonical_url") or "")
            if found is None:
                found = self._jobs.find_by_fingerprint(fingerprint_for_values(values))
        if found is None:
            raise RuntimeError("the captured listing was not stored")
        return _Resolved(found, False)

    def capture(self, payload: CaptureRequest, profile: CandidateProfile) -> CaptureResult:
        record = build_record(payload)
        report = JobIngestService(self._session).ingest(
            [record],
            source=record.source,
            trigger=TRIGGER,
            run_metadata={
                "capture": True,
                "extension_version": payload.extension_version,
                "extraction_method": payload.extraction.method,
            },
        )
        if report.records_invalid:
            raise ValueError("; ".join(report.errors[:3]) or "the listing could not be stored")

        resolved = self._resolve(record, report.created_job_ids)
        job = resolved.job

        ScoringService(self._session).score_many(profile, job_ids=[job.id])
        match = MatchRepository(self._session).get_for_job(job.id, profile.id)

        duplicate_of = None if resolved.created else (job.duplicate_of_id or job.id)
        AuditRepository(self._session).record(
            "jobs.captured",
            entity_type="job",
            entity_id=job.id,
            actor=TRIGGER,
            detail={
                "source": record.source.value,
                "created": resolved.created,
                "extraction_method": payload.extraction.method,
                "extension_version": payload.extension_version,
            },
        )

        if resolved.created:
            message = f"Added to JobOrbit as job {job.id}."
        else:
            message = (
                f"Already in JobOrbit as job {duplicate_of}; this capture was merged into it "
                "instead of creating a second copy."
            )
        return CaptureResult(
            job_id=job.id,
            created=resolved.created,
            duplicate_of=duplicate_of,
            source=record.source.value,
            score=match.total_score if match is not None else None,
            band=match.band if match is not None else None,
            confidence=match.confidence if match is not None else None,
            filtered_out=bool(match.filtered_out) if match is not None else False,
            filter_reasons=list(match.filter_reasons or [])[:5] if match is not None else [],
            explanation=list(match.explanation or [])[:EXPLANATION_LINES]
            if match is not None
            else [],
            dashboard_path=f"/job?job_id={job.id}",
            message=message,
            warnings=report.warnings[:5],
        )
