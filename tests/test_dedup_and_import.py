"""Deduplication and import: source ids, URLs, cross-platform duplicates, invalid rows."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.db.models import ImportStatus, SourceName
from app.db.repositories import JobQuery, JobRepository
from app.services.dedup import compute_fingerprint, description_signature
from app.services.ingest import JobIngestService
from app.sources.manual_import import ImportParseError, parse_payload
from tests.conftest import make_record

DESCRIPTION = "Build REST APIs with Python and FastAPI on PostgreSQL. Hybrid in Bengaluru."


def test_fingerprint_ignores_title_decoration_and_legal_suffixes() -> None:
    left = compute_fingerprint(
        "Backend Developer (Python)",
        "Acme Technologies Pvt Ltd",
        "Bengaluru, Karnataka, India",
        DESCRIPTION,
    )
    right = compute_fingerprint(
        "Backend Developer (Python) - Bengaluru | Urgent",
        "Acme Technologies",
        "Bengaluru",
        DESCRIPTION,
    )
    assert left == right


def test_fingerprint_distinguishes_genuinely_different_jobs() -> None:
    left = compute_fingerprint("Backend Developer", "Acme", "Bengaluru", DESCRIPTION)
    right = compute_fingerprint(
        "Frontend Developer", "Acme", "Bengaluru", "Build React interfaces."
    )
    assert left != right


def test_description_signature_is_order_independent() -> None:
    first = description_signature("Python FastAPI PostgreSQL Docker Kubernetes")
    second = description_signature("Kubernetes Docker PostgreSQL FastAPI Python")
    assert first == second


def test_same_source_id_is_a_duplicate_not_a_new_job(session: Session) -> None:
    service = JobIngestService(session)
    first = service.ingest([make_record(external_id="LI-9")], source=SourceName.LINKEDIN)
    second = service.ingest([make_record(external_id="LI-9")], source=SourceName.LINKEDIN)

    assert first.jobs_created == 1
    assert second.jobs_created == 0
    assert second.duplicates_detected == 1


def test_same_canonical_url_with_different_tracking_params_is_a_duplicate(session: Session) -> None:
    service = JobIngestService(session)
    service.ingest(
        [make_record(external_id=None, url="https://jobs.example.com/view/5")],
        source=SourceName.LINKEDIN,
    )
    report = service.ingest(
        [
            make_record(
                external_id=None,
                url="https://www.jobs.example.com/view/5?utm_source=mail&trk=x",
                title="Totally Different Title",
                company="Totally Different Company",
            )
        ],
        source=SourceName.INDEED,
    )
    assert report.jobs_created == 0
    assert report.duplicates_detected == 1


def test_cross_platform_duplicate_collapses_into_one_job_with_all_sources(
    session: Session,
) -> None:
    report = JobIngestService(session).ingest(
        [
            make_record(
                source=SourceName.LINKEDIN,
                external_id="LI-1",
                title="Backend Developer (Python)",
                company="Acme Technologies Pvt Ltd",
                location="Bengaluru, Karnataka, India",
                url="https://linkedin.example.com/jobs/1",
                description=DESCRIPTION,
            ),
            make_record(
                source=SourceName.NAUKRI,
                external_id="NK-2",
                title="Backend Developer (Python) - Bengaluru | Urgent",
                company="Acme Technologies",
                location="Bengaluru",
                url="https://naukri.example.com/jobs/2",
                description=DESCRIPTION,
            ),
            make_record(
                source=SourceName.INDEED,
                external_id="IN-3",
                title="Backend Developer - Python",
                company="Acme Tech",
                location="Bengaluru, India",
                url="https://indeed.example.com/jobs/3",
                description=DESCRIPTION,
            ),
        ],
        source=SourceName.MANUAL,
    )

    assert report.jobs_created == 1
    assert report.duplicates_detected == 2

    jobs = JobRepository(session).list(JobQuery(limit=10, sort_by="discovered_at"))
    assert len(jobs) == 1
    assert sorted(reference.source.value for reference in jobs[0].source_references) == [
        "indeed",
        "linkedin",
        "naukri",
    ]


def test_duplicate_enriches_rather_than_overwrites(session: Session) -> None:
    """A later, sparser sighting must not degrade a richer stored job."""
    service = JobIngestService(session)
    service.ingest(
        [
            make_record(
                source=SourceName.LINKEDIN,
                external_id="LI-1",
                title="Backend Developer (Python)",
                location="Bengaluru, Karnataka, India",
                required_skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
                posted_at="2026-10-01",
                description=DESCRIPTION,
            )
        ],
        source=SourceName.LINKEDIN,
    )
    service.ingest(
        [
            make_record(
                source=SourceName.NAUKRI,
                external_id="NK-1",
                title="Backend Developer (Python) - Bengaluru | Urgent",
                location="Bengaluru",
                required_skills=["Python", "Redis"],
                posted_at=None,
                description=DESCRIPTION,
            )
        ],
        source=SourceName.NAUKRI,
    )

    job = JobRepository(session).list(JobQuery(limit=5, sort_by="discovered_at"))[0]
    assert job.title == "Backend Developer (Python)"
    assert job.location == "Bengaluru, Karnataka, India"
    assert job.posted_at is not None
    assert set(job.required_skills) == {"python", "fastapi", "postgresql", "docker", "redis"}


def test_reimporting_identical_records_is_a_no_op(session: Session) -> None:
    service = JobIngestService(session)
    records = [
        make_record(
            external_id=f"LI-{index}",
            title=f"Backend Developer {index}",
            company=f"Company {index}",
            url=f"https://jobs.example.com/view/{index}",
            description=f"Distinct role number {index} building services with Python.",
        )
        for index in range(4)
    ]
    first = service.ingest(records, source=SourceName.LINKEDIN)
    second = service.ingest(records, source=SourceName.LINKEDIN)

    assert first.jobs_created == 4
    assert second.jobs_created == 0
    assert second.jobs_updated == 0
    assert second.duplicates_detected == 4


# --------------------------------------------------------------------------------------
# Payload parsing
# --------------------------------------------------------------------------------------


def test_json_list_import() -> None:
    payload = json.dumps(
        [
            {
                "source": "linkedin",
                "title": "Backend Developer",
                "company": "Acme",
                "url": "https://example.com/1",
            }
        ]
    ).encode()
    result = parse_payload(payload, filename="jobs.json")
    assert len(result.records) == 1
    assert result.records[0].source is SourceName.LINKEDIN


def test_json_wrapped_in_an_object_is_accepted() -> None:
    payload = json.dumps(
        {"jobs": [{"title": "Dev", "company": "Acme", "url": "https://example.com/1"}]}
    ).encode()
    assert len(parse_payload(payload, filename="jobs.json").records) == 1


def test_csv_import_maps_synonym_columns() -> None:
    payload = (
        b"Job Title,Company Name,Job Location,Apply URL,Key Skills,Date Posted\n"
        b"Python Developer,Acme Technologies,Bengaluru,https://example.com/1,Python|Flask,2026-10-01\n"
    )
    result = parse_payload(payload, filename="jobs.csv")
    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "Python Developer"
    assert record.company == "Acme Technologies"
    assert record.required_skills == ["Python", "Flask"]


def test_csv_import_counts_and_reports_invalid_rows_by_number() -> None:
    payload = (
        b"Job Title,Company Name,Link\n"
        b"Good Developer,Acme,https://example.com/1\n"
        b",Missing Title Inc,https://example.com/2\n"
        b"No Link Developer,Acme,\n"
    )
    result = parse_payload(payload, filename="jobs.csv")
    assert len(result.records) == 1
    assert result.invalid_count == 2
    assert any(error.startswith("row 2") for error in result.errors)
    assert any(error.startswith("row 3") for error in result.errors)


def test_tab_separated_file_is_detected() -> None:
    payload = b"Job Title\tCompany Name\tLink\nDev\tAcme\thttps://example.com/1\n"
    assert len(parse_payload(payload, filename="jobs.tsv").records) == 1


def test_unknown_columns_are_preserved_as_source_metadata() -> None:
    payload = b"Job Title,Company Name,Link,Recruiter Name\nDev,Acme,https://example.com/1,Asha\n"
    record = parse_payload(payload, filename="jobs.csv").records[0]
    assert record.source_metadata.get("recruiter name") == "Asha"


def test_empty_payload_is_rejected_with_a_clear_message() -> None:
    with pytest.raises(ImportParseError):
        parse_payload(b"", filename="jobs.csv")


def test_invalid_json_is_rejected_with_a_line_number() -> None:
    with pytest.raises(ImportParseError) as error:
        parse_payload(b'[{"title": "Dev",}]', filename="jobs.json")
    assert "line" in str(error.value)


def test_headerless_csv_is_rejected() -> None:
    with pytest.raises(ImportParseError):
        parse_payload(b"", filename="jobs.csv")


def test_import_run_records_a_partial_status_when_some_rows_fail(session: Session) -> None:
    report = JobIngestService(session).ingest(
        [make_record(external_id="LI-1")],
        source=SourceName.LINKEDIN,
        invalid_count=2,
        adapter_errors=["row 7: title: must not be blank"],
    )
    assert report.status is ImportStatus.PARTIAL
    assert report.records_invalid == 2
    assert report.errors


# --------------------------------------------------------------------------------------
# Import status honesty (release-hardening regressions)
# --------------------------------------------------------------------------------------


def test_a_binary_file_is_rejected_not_imported_as_zero_jobs() -> None:
    """Regression: a binary file decoded to a header-only document and reported SUCCESS."""
    with pytest.raises(ImportParseError, match="binary"):
        parse_payload(b"\x00\x01\x02 binary garbage", filename="jobs.csv")


def test_a_header_only_file_is_rejected() -> None:
    with pytest.raises(ImportParseError, match="no job rows"):
        parse_payload(b"Job Title,Company Name,Link\n", filename="jobs.csv")


def test_an_empty_json_list_is_rejected() -> None:
    with pytest.raises(ImportParseError, match="no job rows"):
        parse_payload(b"[]", filename="jobs.json")


def test_reimporting_a_file_with_one_bad_row_is_partial_not_failed(
    session: Session,
) -> None:
    """Regression: a successful idempotent re-import was reported FAILED.

    Duplicates are progress. Without counting them, a re-import that correctly recognised
    every row created nothing, updated nothing, and so fell through to FAILED, which also
    inflated the import-failure metric on the dashboard.
    """
    service = JobIngestService(session)
    records = [
        make_record(
            external_id=f"ST-{index}",
            title=f"Developer {index}",
            company=f"Company {index}",
            url=f"https://jobs.example.com/st/{index}",
            description=f"Distinct role {index} building Python services.",
        )
        for index in range(3)
    ]

    first = service.ingest(records, source=SourceName.LINKEDIN, invalid_count=1)
    assert first.status is ImportStatus.PARTIAL
    assert first.jobs_created == 3

    second = service.ingest(records, source=SourceName.LINKEDIN, invalid_count=1)
    assert second.jobs_created == 0
    assert second.duplicates_detected == 3
    assert second.status is ImportStatus.PARTIAL, "a clean re-import must never be FAILED"


def test_an_import_with_no_bad_rows_is_success(session: Session) -> None:
    report = JobIngestService(session).ingest(
        [make_record(external_id="OK-1")], source=SourceName.LINKEDIN
    )
    assert report.status is ImportStatus.SUCCESS


def test_an_import_where_nothing_could_be_processed_is_failed(session: Session) -> None:
    report = JobIngestService(session).ingest([], source=SourceName.LINKEDIN, invalid_count=4)
    assert report.status is ImportStatus.FAILED
