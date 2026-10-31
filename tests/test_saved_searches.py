"""Saved searches: criteria validation, watermark semantics and the on-demand digest.

The watermark is the part worth testing hardest. "New since you last looked" is the whole
value of a saved search, and it is easy to implement in a way that looks right and is not:
comparing against the posting date instead of the discovery date, or advancing the
watermark on a mere page render, both produce a digest that quietly reports nothing new.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Job, utcnow
from app.db.repositories import SavedSearchRepository, UnknownCriterionError
from app.db.repositories.jobs import JobQuery
from app.db.repositories.searches import ALLOWED_CRITERIA, criteria_from_query
from app.schemas.search import SavedSearchCriteria


def _profile(session: Session) -> CandidateProfile:
    profile = session.query(CandidateProfile).first()
    if profile is None:
        profile = CandidateProfile(full_name="Test Candidate")
        session.add(profile)
        session.flush()
    return profile


def _job(session: Session, title: str, *, discovered_days_ago: float = 0.0) -> Job:
    job = Job(
        title=title,
        company="Northwind Systems",
        company_normalized="northwind systems",
        location="Bengaluru, India",
        location_normalized="bengaluru, india",
        url=f"https://jobs.example.com/{title.replace(' ', '-').lower()}",
        fingerprint=f"fp-{title}",
        discovered_at=utcnow() - timedelta(days=discovered_days_ago),
    )
    session.add(job)
    session.flush()
    return job


# --------------------------------------------------------------------------------------
# Criteria validation
# --------------------------------------------------------------------------------------


def test_the_schema_and_the_repository_allowlist_stay_in_step() -> None:
    """Two places name the permitted filters; a field in one only is silently dropped."""
    schema_fields = set(SavedSearchCriteria.model_fields)
    assert schema_fields == set(ALLOWED_CRITERIA), (
        "SavedSearchCriteria and ALLOWED_CRITERIA have diverged: "
        f"schema-only={sorted(schema_fields - ALLOWED_CRITERIA)} "
        f"repository-only={sorted(ALLOWED_CRITERIA - schema_fields)}"
    )


def test_an_unknown_criterion_is_rejected_at_write_time(session: Session) -> None:
    """The blob is replayed into a database query, so it cannot be trusted at read time."""
    profile = _profile(session)
    with pytest.raises(UnknownCriterionError):
        SavedSearchRepository(session).create(profile.id, "bad", {"drop_table": "job"})


def test_an_unknown_band_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown band"):
        SavedSearchCriteria(bands=["excellent"])


def test_criteria_round_trip_from_a_live_query_keeps_only_storable_fields() -> None:
    query = JobQuery(search="python", min_score=70.0, limit=99, offset=10, profile_id=4)
    stored = criteria_from_query(query)
    assert stored == {
        "search": "python",
        "min_score": 70.0,
        "include_duplicates": False,
        "sort_by": "score",
        "descending": True,
    }
    assert "limit" not in stored and "profile_id" not in stored, (
        "pagination and the profile id are request-scoped, not part of a saved search"
    )


# --------------------------------------------------------------------------------------
# Watermark semantics
# --------------------------------------------------------------------------------------


def test_a_first_run_reports_every_match_as_new(session: Session) -> None:
    profile = _profile(session)
    _job(session, "Backend Developer")
    _job(session, "Frontend Developer")
    search = SavedSearchRepository(session).create(profile.id, "All", {})

    result = SavedSearchRepository(session).run(search, profile.id)
    assert result.previous_run_at is None
    assert result.total_matching == 2
    assert result.new_since_last_run == 2
    assert len(result.jobs) == 2


def test_a_second_run_reports_only_what_arrived_since(session: Session) -> None:
    profile = _profile(session)
    _job(session, "Backend Developer", discovered_days_ago=3)
    repository = SavedSearchRepository(session)
    search = repository.create(profile.id, "All", {})

    first = repository.run(search, profile.id)
    assert first.new_since_last_run == 1

    _job(session, "Platform Engineer")
    second = repository.run(search, profile.id)

    assert second.total_matching == 2, "the total is the whole feed, not just the new rows"
    assert second.new_since_last_run == 1
    assert [job.title for job in second.jobs] == ["Platform Engineer"]


def test_a_run_with_nothing_new_reports_zero_rather_than_repeating_itself(
    session: Session,
) -> None:
    profile = _profile(session)
    _job(session, "Backend Developer")
    repository = SavedSearchRepository(session)
    search = repository.create(profile.id, "All", {})

    repository.run(search, profile.id)
    again = repository.run(search, profile.id)
    assert again.new_since_last_run == 0
    assert again.jobs == []


def test_preview_does_not_consume_the_watermark(session: Session) -> None:
    """Rendering a page must not cost the user the record of what they had not seen."""
    profile = _profile(session)
    _job(session, "Backend Developer")
    repository = SavedSearchRepository(session)
    search = repository.create(profile.id, "All", {})

    repository.run(search, profile.id)
    marked = search.last_run_at
    _job(session, "Platform Engineer")

    preview = repository.run(search, profile.id, mark_seen=False)
    assert preview.new_since_last_run == 1
    assert search.last_run_at == marked, "preview moved the watermark"

    confirmed = repository.run(search, profile.id, mark_seen=True)
    assert confirmed.new_since_last_run == 1, "the row was still unseen until an explicit run"
    assert search.last_run_at != marked


def test_the_watermark_uses_discovery_not_posting_date(session: Session) -> None:
    """A job posted weeks ago is new to the user the day this app first sees it."""
    profile = _profile(session)
    repository = SavedSearchRepository(session)
    search = repository.create(profile.id, "All", {})
    repository.run(search, profile.id)

    stale_posting = _job(session, "Older Posting")
    stale_posting.posted_at = utcnow() - timedelta(days=40)
    session.flush()

    result = repository.run(search, profile.id)
    assert result.new_since_last_run == 1, (
        "a long-posted listing discovered today is still new to the user"
    )


def test_criteria_actually_narrow_the_digest(session: Session) -> None:
    profile = _profile(session)
    _job(session, "Backend Developer")
    _job(session, "Account Executive")
    repository = SavedSearchRepository(session)
    search = repository.create(profile.id, "Backend only", {"search": "Backend"})

    result = repository.run(search, profile.id)
    assert [job.title for job in result.jobs] == ["Backend Developer"]


# --------------------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------------------


def test_the_api_round_trips_a_saved_search(client: TestClient) -> None:
    created = client.post(
        "/api/searches",
        json={"name": "Fresher backend", "criteria": {"search": "backend", "bands": ["high"]}},
    )
    assert created.status_code == 201, created.text
    search_id = created.json()["id"]

    listed = client.get("/api/searches").json()
    assert [entry["name"] for entry in listed] == ["Fresher backend"]

    renamed = client.patch(f"/api/searches/{search_id}", json={"name": "Backend, high band"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Backend, high band"

    assert client.delete(f"/api/searches/{search_id}").status_code == 204
    assert client.get("/api/searches").json() == []


def test_a_duplicate_name_is_refused(client: TestClient) -> None:
    client.post("/api/searches", json={"name": "Dup", "criteria": {}})
    second = client.post("/api/searches", json={"name": "Dup", "criteria": {}})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_search"


def test_an_unknown_criterion_is_refused_by_the_api(client: TestClient) -> None:
    response = client.post(
        "/api/searches", json={"name": "Bad", "criteria": {"delete_everything": True}}
    )
    assert response.status_code == 422


def test_running_a_missing_search_is_a_clean_404(client: TestClient) -> None:
    response = client.post("/api/searches/9999/run")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_digest_endpoint_returns_scored_job_cards(client: TestClient, session: Session) -> None:
    """The digest must carry the match, not bare job rows, or it cannot be ranked or read."""
    _profile(session)
    _job(session, "Backend Developer")
    session.commit()

    created = client.post("/api/searches", json={"name": "All", "criteria": {}})
    digest = client.post(f"/api/searches/{created.json()['id']}/run").json()

    assert digest["total_matching"] == 1
    assert digest["new_since_last_run"] == 1
    assert "match" in digest["jobs"][0], "job cards in a digest need their score and band"


def test_the_new_search_writes_are_classified_for_demo_mode() -> None:
    from app.api.deps import DEMO_SESSION_SCOPED

    assert {"create_search", "update_search", "delete_search", "run_search"} <= set(
        DEMO_SESSION_SCOPED
    )


def test_no_search_route_runs_on_a_schedule() -> None:
    """Milestone requirement: the digest is pull-only, with no background-worker dependency."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("app/api/routes/searches.py").read_text(encoding="utf-8"))
    # Parsed rather than grepped: the module docstring explains *why* there is no
    # scheduler, so a text search for the word matches the explanation itself.
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not any("apscheduler" in name.lower() for name in imported), imported
    assert "BackgroundTasks" not in imported
    assert "app.scheduler" not in imported
    assert "add_job" not in called


def test_a_run_refreshes_the_header_instead_of_leaving_it_stale() -> None:
    """Measured in a browser: after Run the header still read "Never run".

    The page reads the search list before the click, so the ``last_run_at`` it renders is
    the pre-run value. The fix stashes the digest and reruns; this asserts both halves are
    present, because dropping either one restores the stale header or loses the results.
    """
    import ast
    from pathlib import Path

    source = Path("ui/views/searches_page.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "rerun" in calls, "a run must rerun so the header picks up the new watermark"
    assert "_digest_key" in source, "the digest must survive the rerun"
    assert "run_search" in source and "preview_search" in source
