"""Cross-source duplication analysis: rates, missed merges, false merges, provenance.

The analysis is read-only and advisory. These tests pin three guarantees that matter more
than the numbers themselves: merging preserves every sighting's own URL, merging never
removes an application record, and a merge that looks wrong is *reported* rather than
silently accepted.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, JobStatus, SourceName
from app.services.duplication import (
    FALSE_MERGE_TITLE_OVERLAP,
    MISSED_MERGE_TITLE_OVERLAP,
    _tokens,
    analyse_duplication,
    jaccard,
)
from app.services.ingest import JobIngestService
from tests.conftest import make_record


def _ingest(session: Session, *records, source: SourceName) -> None:
    JobIngestService(session).ingest(list(records), source=source)


def test_an_empty_database_reports_zero_rather_than_dividing_by_zero(session: Session) -> None:
    report = analyse_duplication(session)
    assert report.jobs_total == 0
    assert report.sightings_total == 0
    assert report.duplicate_rate == 0.0
    assert report.cross_source_duplicate_rate == 0.0
    assert report.is_healthy


def test_a_single_source_job_reports_no_duplication(session: Session) -> None:
    _ingest(session, make_record(), source=SourceName.LINKEDIN)
    report = analyse_duplication(session)
    assert report.jobs_total == 1
    assert report.sightings_total == 1
    assert report.merged_sightings == 0
    assert report.duplicate_rate == 0.0
    assert report.multi_source_jobs == 0


def test_the_same_job_on_two_platforms_counts_as_one_cross_source_duplicate(
    session: Session,
) -> None:
    _ingest(session, make_record(source=SourceName.LINKEDIN), source=SourceName.LINKEDIN)
    _ingest(
        session,
        make_record(
            source=SourceName.NAUKRI,
            external_id="NK-1",
            url="https://naukri.example.com/job/1",
        ),
        source=SourceName.NAUKRI,
    )

    report = analyse_duplication(session)
    assert report.jobs_total == 1
    assert report.sightings_total == 2
    assert report.merged_sightings == 1
    assert report.duplicate_rate == 0.5
    assert report.multi_source_jobs == 1
    assert report.cross_source_duplicate_rate == 1.0
    assert report.sources_seen == ["linkedin", "naukri"]
    assert report.source_pair_overlaps == {"linkedin+naukri": 1}


def test_exact_and_fuzzy_duplicates_are_counted_separately(session: Session) -> None:
    """A re-import matches on source id; another platform matches on the fingerprint."""
    service = JobIngestService(session)
    service.ingest([make_record()], source=SourceName.LINKEDIN)
    service.ingest([make_record()], source=SourceName.LINKEDIN)
    service.ingest(
        [
            make_record(
                source=SourceName.NAUKRI,
                external_id="NK-2",
                url="https://naukri.example.com/job/2",
            )
        ],
        source=SourceName.NAUKRI,
    )

    report = analyse_duplication(session)
    assert report.fuzzy_duplicate_sightings == 1
    assert report.sightings_by_rule.get("same_fingerprint") == 1
    assert report.sightings_by_rule.get("new") == 1


def test_every_sighting_keeps_its_own_url_and_external_id(session: Session) -> None:
    _ingest(session, make_record(), source=SourceName.LINKEDIN)
    _ingest(
        session,
        make_record(
            source=SourceName.NAUKRI,
            external_id="NK-3",
            url="https://naukri.example.com/job/3",
        ),
        source=SourceName.NAUKRI,
    )

    from app.db.models import Job

    job = session.query(Job).one()
    urls = {reference.url for reference in job.source_references}
    ids = {reference.external_id for reference in job.source_references}
    assert "https://jobs.example.com/view/1" in urls
    assert "https://naukri.example.com/job/3" in urls
    assert ids == {"LI-1", "NK-3"}


def test_merging_a_duplicate_does_not_remove_an_application_record(
    session: Session, profile: CandidateProfile
) -> None:
    """A second sighting enriches the job in place, so prepared work must survive it."""
    from app.services.application_prep import ApplicationPreparationService

    _ingest(session, make_record(), source=SourceName.LINKEDIN)
    from app.db.models import Job

    job = session.query(Job).one()
    job.status = JobStatus.SHORTLISTED
    session.flush()

    application = ApplicationPreparationService(session).prepare(job, profile).application
    application_id = application.id
    answer_count = len(application.answers)
    assert answer_count > 0

    _ingest(
        session,
        make_record(
            source=SourceName.NAUKRI,
            external_id="NK-4",
            url="https://naukri.example.com/job/4",
        ),
        source=SourceName.NAUKRI,
    )

    from app.db.models import Application

    survived = session.get(Application, application_id)
    assert survived is not None
    assert survived.job_id == job.id
    assert len(survived.answers) == answer_count

    report = analyse_duplication(session)
    assert report.jobs_with_application == 1
    assert report.multi_source_jobs_with_application == 1


def test_two_near_identical_jobs_at_one_company_are_flagged_as_a_possible_missed_merge(
    session: Session,
) -> None:
    """Different descriptions give different fingerprints, so they are not merged."""
    _ingest(
        session,
        make_record(
            external_id="LI-A",
            title="Backend Developer",
            description="Design and ship Python services. Kubernetes exposure welcome.",
            url="https://jobs.example.com/view/a",
        ),
        source=SourceName.LINKEDIN,
    )
    _ingest(
        session,
        make_record(
            external_id="LI-B",
            title="Developer Backend",
            description="Completely different wording about building distributed systems.",
            url="https://jobs.example.com/view/b",
        ),
        source=SourceName.LINKEDIN,
    )

    report = analyse_duplication(session)
    assert report.jobs_total == 2
    assert report.missed_merge_suspects
    suspect = report.missed_merge_suspects[0]
    assert suspect.title_overlap >= MISSED_MERGE_TITLE_OVERLAP
    assert "Acme Technologies" in suspect.company
    assert "same company" in suspect.reason


def test_distinct_roles_at_one_company_are_not_flagged(session: Session) -> None:
    _ingest(
        session,
        make_record(external_id="LI-C", title="Backend Developer"),
        source=SourceName.LINKEDIN,
    )
    _ingest(
        session,
        make_record(
            external_id="LI-D",
            title="Product Marketing Manager",
            description="Own go-to-market messaging and campaign planning.",
            url="https://jobs.example.com/view/d",
        ),
        source=SourceName.LINKEDIN,
    )

    report = analyse_duplication(session)
    assert report.jobs_total == 2
    assert not report.missed_merge_suspects


def test_a_merge_whose_sightings_disagree_is_reported_as_a_false_merge(
    session: Session,
) -> None:
    """A shared canonical URL is the one rule that can merge two genuinely different roles.

    The fingerprint cannot: it hashes the core title, so differing titles always produce
    different fingerprints. URL matching has no such protection, and a board that serves
    several postings behind one canonical URL would collapse them. The detector must catch
    that, because the merged job would hide a real listing.
    """
    shared_url = "https://jobs.example.com/view/shared"
    _ingest(
        session,
        make_record(external_id="LI-E", title="Backend Developer", url=shared_url),
        source=SourceName.LINKEDIN,
    )
    _ingest(
        session,
        make_record(
            source=SourceName.NAUKRI,
            external_id="NK-E",
            title="Finance Analyst",
            description="Prepare monthly management accounts and variance commentary.",
            url=shared_url,
        ),
        source=SourceName.NAUKRI,
    )

    report = analyse_duplication(session)
    assert report.jobs_total == 1, "the shared URL should have merged the two sightings"
    assert report.sightings_by_rule.get("same_url") == 1
    assert report.false_merge_suspects, "a disagreeing merge must be reported"

    suspect = report.false_merge_suspects[0]
    assert suspect.title_overlap < FALSE_MERGE_TITLE_OVERLAP
    assert set(suspect.observed_titles) == {"Backend Developer", "Finance Analyst"}
    assert suspect.sources == ("linkedin", "naukri")
    assert "overlap" in suspect.reason
    assert not report.is_healthy


def test_the_detector_does_not_reuse_the_dedup_core_title(session: Session) -> None:
    """Detection must stay independent of the function whose mistakes it looks for.

    An earlier version tokenised via ``dedup._core_title``. Two "PhD - <topic>" postings
    both reduced to the core "phd", so the detector scored their overlap at 100% and
    reported a genuine false merge as healthy.
    """
    from app.services.dedup import _core_title

    left = "PhD - Safety Contracts for Physical AI"
    right = "PhD - A Generator of Optimized Winding Schemes"
    assert jaccard(_tokens(left), _tokens(right)) < FALSE_MERGE_TITLE_OVERLAP

    shared_url = "https://jobs.example.com/view/phd"
    _ingest(
        session,
        make_record(external_id="A", title=left, url=shared_url),
        source=SourceName.LINKEDIN,
    )
    _ingest(
        session,
        make_record(source=SourceName.NAUKRI, external_id="B", title=right, url=shared_url),
        source=SourceName.NAUKRI,
    )

    report = analyse_duplication(session)
    assert report.jobs_total == 1
    assert report.false_merge_suspects, "a disagreeing merge must be reported"
    assert set(report.false_merge_suspects[0].observed_titles) == {left, right}
    assert _core_title(left) != _core_title(right), (
        "dedup must also keep these distinct; if this fails the false merge is real"
    )


def test_a_correct_cross_platform_merge_is_not_reported_as_a_false_merge(
    session: Session,
) -> None:
    _ingest(session, make_record(), source=SourceName.LINKEDIN)
    _ingest(
        session,
        make_record(
            source=SourceName.NAUKRI,
            external_id="NK-5",
            url="https://naukri.example.com/job/5",
        ),
        source=SourceName.NAUKRI,
    )

    report = analyse_duplication(session)
    assert report.multi_source_jobs == 1
    assert not report.false_merge_suspects
    assert report.is_healthy


def test_a_legal_suffix_difference_is_not_a_normalization_collision(session: Session) -> None:
    _ingest(
        session,
        make_record(external_id="LI-F", company="Acme Technologies Pvt Ltd"),
        source=SourceName.LINKEDIN,
    )
    _ingest(
        session,
        make_record(
            external_id="LI-G",
            company="Acme Technologies",
            title="Data Engineer",
            description="Build batch pipelines in Python with Airflow and Spark.",
            url="https://jobs.example.com/view/g",
        ),
        source=SourceName.LINKEDIN,
    )

    report = analyse_duplication(session)
    assert not report.normalization_collisions


def test_jaccard_handles_empty_token_sets() -> None:
    assert jaccard(frozenset(), frozenset({"a"})) == 0.0
    assert jaccard(frozenset({"a"}), frozenset()) == 0.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == 1 / 3


def test_the_duplication_endpoint_serves_the_report(client) -> None:
    client.post(
        "/api/jobs/import",
        json={
            "records": [
                {
                    "source": "linkedin",
                    "external_id": "DUP-1",
                    "title": "Backend Developer",
                    "company": "Acme Technologies",
                    "location": "Bengaluru",
                    "url": "https://jobs.example.com/dup/1",
                    "description": "Python and FastAPI services in Bengaluru.",
                }
            ]
        },
    )
    client.post(
        "/api/jobs/import",
        json={
            "records": [
                {
                    "source": "naukri",
                    "external_id": "DUP-2",
                    "title": "Backend Developer",
                    "company": "Acme Technologies",
                    "location": "Bengaluru",
                    "url": "https://naukri.example.com/dup/2",
                    "description": "Python and FastAPI services in Bengaluru.",
                }
            ]
        },
    )

    body = client.get("/api/metrics/duplication").json()
    assert body["jobs_total"] == 1
    assert body["sightings_total"] == 2
    assert body["multi_source_jobs"] == 1
    assert body["duplicate_rate"] == 0.5
    assert body["is_healthy"] is True
    assert "linkedin+naukri" in body["source_pair_overlaps"]
