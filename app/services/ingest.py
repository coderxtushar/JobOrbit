"""Job ingestion pipeline.

Takes validated :class:`RawJobRecord` objects from any adapter and lands them in the
database, resolving duplicates and recording an :class:`ImportRun` for every attempt.

Duplicate resolution order (most to least reliable):

1. ``(source, external_id)`` — same posting, same platform. Refresh it in place.
2. ``canonical_url`` — same posting reached by a different link.
3. ``fingerprint`` — same posting on a *different* platform. The existing ``Job`` gains a
   new :class:`JobSourceReference` so the user sees both platforms, and no second row is
   created.

A duplicate never overwrites a known ``posted_at`` with ``None``, and a later sighting
never moves ``discovered_at`` backwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    EmploymentType,
    ImportRun,
    ImportStatus,
    Job,
    JobSourceReference,
    JobStatus,
    SourceName,
    WorkArrangement,
    utcnow,
)
from app.db.repositories import AuditRepository, ImportRunRepository, JobRepository
from app.logging_conf import get_logger
from app.schemas.job import RawJobRecord
from app.services.dedup import DedupDecision, MatchKind, fingerprint_for_values
from app.services.normalization import normalize_record

logger = get_logger(__name__)

_FILL_IF_EMPTY_FIELDS = (
    "title",
    "location",
    "location_normalized",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_raw",
    "experience_min_years",
    "experience_max_years",
    "experience_raw",
    "application_method",
)

_UNION_LIST_FIELDS = ("required_skills", "preferred_skills", "education_requirements")

_UNKNOWN_ENUM_FIELDS = (
    ("work_arrangement", WorkArrangement.UNKNOWN),
    ("employment_type", EmploymentType.UNKNOWN),
)


@dataclass(slots=True)
class IngestReport:
    import_run_id: int
    source: SourceName
    status: ImportStatus
    records_received: int = 0
    records_invalid: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    duplicates_detected: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_job_ids: list[int] = field(default_factory=list)
    message: str = ""


class JobIngestService:
    """Persists normalized jobs and maintains duplicate relationships."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = JobRepository(session)
        self._runs = ImportRunRepository(session)
        self._audit = AuditRepository(session)

    def _classify(self, record: RawJobRecord, values: dict[str, Any]) -> DedupDecision:
        if record.external_id:
            existing = self._jobs.find_by_source_id(record.source, record.external_id)
            if existing is not None:
                return DedupDecision(
                    MatchKind.SAME_SOURCE_ID,
                    existing.id,
                    f"{record.source.value} id {record.external_id} is already stored",
                )

        canonical = values.get("canonical_url") or ""
        if canonical:
            existing = self._jobs.find_by_canonical_url(canonical)
            if existing is not None:
                return DedupDecision(
                    MatchKind.SAME_URL, existing.id, "the same canonical url is already stored"
                )

        existing = self._jobs.find_by_fingerprint(values["fingerprint"])
        if existing is not None:
            return DedupDecision(
                MatchKind.SAME_FINGERPRINT,
                existing.id,
                "title, company, location and description match an existing listing",
            )
        return DedupDecision(MatchKind.NEW)

    def _refresh(self, job: Job, values: dict[str, Any]) -> bool:
        """Enrich an existing job with a new sighting. Returns True if anything changed.

        Enrichment is strictly additive. Two platforms describe the same role with
        different detail, and whichever is imported second must not overwrite the richer
        version: doing so makes the stored title and skill list depend on import order and
        flip on every re-import. So a scalar is only filled when it is currently empty,
        skill lists are unioned, and the longest description wins. The consequence worth
        relying on is that re-importing an unchanged file is a true no-op.
        """
        changed = False

        for name in _FILL_IF_EMPTY_FIELDS:
            new_value = values.get(name)
            if new_value in (None, "", [], {}):
                continue
            if getattr(job, name) in (None, "", [], {}):
                setattr(job, name, new_value)
                changed = True

        for name, unknown in _UNKNOWN_ENUM_FIELDS:
            new_value = values.get(name)
            if new_value is not None and new_value is not unknown and getattr(job, name) is unknown:
                setattr(job, name, new_value)
                changed = True

        for name in _UNION_LIST_FIELDS:
            incoming = values.get(name) or []
            if not incoming:
                continue
            existing = list(getattr(job, name) or [])
            merged = list(dict.fromkeys(existing + list(incoming)))
            if merged != existing:
                setattr(job, name, merged)
                changed = True

        incoming_posted = values.get("posted_at")
        if incoming_posted is not None and (
            job.posted_at is None
            or (job.posted_at_is_approximate and not values.get("posted_at_is_approximate"))
        ):
            job.posted_at = incoming_posted
            job.posted_at_is_approximate = bool(values.get("posted_at_is_approximate"))
            changed = True

        new_description = values.get("description") or ""
        if len(new_description) > len(job.description or ""):
            job.description = new_description
            changed = True

        if not job.url and values.get("url"):
            job.url = values["url"]
            job.canonical_url = values.get("canonical_url", "")
            changed = True
        return changed

    def ingest(
        self,
        records: list[RawJobRecord],
        *,
        source: SourceName,
        trigger: str = "manual",
        invalid_count: int = 0,
        adapter_errors: list[str] | None = None,
        retrieved_at: datetime | None = None,
        import_run: ImportRun | None = None,
        run_metadata: dict[str, Any] | None = None,
    ) -> IngestReport:
        """Normalize, deduplicate and store a batch of records."""
        retrieved_at = retrieved_at or utcnow()
        run = import_run or self._runs.create(
            ImportRun(
                source=source,
                trigger=trigger,
                status=ImportStatus.RUNNING,
                started_at=retrieved_at,
                run_metadata=run_metadata or {},
            )
        )

        report = IngestReport(
            import_run_id=run.id,
            source=source,
            status=ImportStatus.RUNNING,
            records_received=len(records),
            records_invalid=invalid_count,
            errors=list(adapter_errors or []),
        )

        for index, record in enumerate(records, start=1):
            try:
                self._ingest_one(record, retrieved_at, run, report)
            except Exception as exc:
                report.records_invalid += 1
                if len(report.errors) < 50:
                    report.errors.append(f"record {index}: {type(exc).__name__}: {exc}")
                logger.exception("failed to ingest a job record", extra={"record_index": index})

        # Duplicates count as progress. A re-import of an unchanged file creates nothing
        # and updates nothing, yet every row was handled correctly; without counting
        # duplicates here that successful no-op was reported as FAILED and inflated the
        # import-failure metric on the dashboard.
        processed = report.jobs_created + report.jobs_updated + report.duplicates_detected
        if report.records_invalid and processed:
            report.status = ImportStatus.PARTIAL
        elif report.records_invalid and not processed:
            report.status = ImportStatus.FAILED
        else:
            report.status = ImportStatus.SUCCESS

        report.message = (
            f"{report.jobs_created} new, {report.jobs_updated} updated, "
            f"{report.duplicates_detected} duplicate, {report.records_invalid} invalid"
        )

        run.status = report.status
        run.finished_at = utcnow()
        run.records_received = report.records_received
        run.records_invalid = report.records_invalid
        run.jobs_created = report.jobs_created
        run.jobs_updated = report.jobs_updated
        run.duplicates_detected = report.duplicates_detected
        run.errors = report.errors[:50]
        run.message = report.message

        self._audit.record(
            "jobs.import",
            entity_type="import_run",
            entity_id=run.id,
            actor=trigger,
            detail={
                "source": source.value,
                "created": report.jobs_created,
                "updated": report.jobs_updated,
                "duplicates": report.duplicates_detected,
                "invalid": report.records_invalid,
                "status": report.status.value,
            },
        )
        self._session.flush()
        return report

    def _ingest_one(
        self,
        record: RawJobRecord,
        retrieved_at: datetime,
        run: ImportRun,
        report: IngestReport,
    ) -> None:
        normalized = normalize_record(record, retrieved_at)
        values = normalized.values
        values["fingerprint"] = fingerprint_for_values(values)
        report.warnings.extend(normalized.warnings[:3])

        decision = self._classify(record, values)

        if decision.kind is MatchKind.NEW:
            job = self._jobs.add(Job(**values, status=JobStatus.DISCOVERED))
            report.jobs_created += 1
            report.created_job_ids.append(job.id)
        else:
            existing = self._jobs.get(decision.existing_job_id or 0)
            if existing is None:
                raise RuntimeError(f"duplicate pointed at missing job {decision.existing_job_id}")
            job = existing
            report.duplicates_detected += 1
            if self._refresh(job, values):
                report.jobs_updated += 1

        if not self._jobs.has_source_reference(job.id, record.source, record.external_id):
            self._jobs.add_source_reference(
                JobSourceReference(
                    job_id=job.id,
                    source=record.source,
                    external_id=record.external_id,
                    url=values.get("url", ""),
                    retrieved_at=retrieved_at,
                    retrieval_method=record.retrieval_method,
                    import_run_id=run.id,
                    source_metadata={
                        **normalized.source_metadata,
                        "dedup": decision.kind.value,
                        "normalization_warnings": normalized.warnings[:5],
                    },
                )
            )
