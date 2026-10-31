"""Dashboard: API client error translation, helpers, and page empty states.

Pages are rendered headlessly with Streamlit's ``AppTest`` against a stub client, so empty
states and error states are exercised without a running server or a browser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests
from streamlit.testing.v1 import AppTest

from ui.api_client import ApiClient, ApiClientError
from ui.components import (
    band_badge,
    confidence_badge,
    evidence_block,
    local_date,
    local_time,
    skill_chips,
    unassessable_fields,
)
from ui.theme import CONFIDENCE_TONES

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EMPTY_METRICS: dict[str, Any] = {
    "jobs_total": 0,
    "jobs_by_status": {},
    "jobs_imported": 0,
    "records_invalid": 0,
    "duplicates_detected": 0,
    "jobs_filtered_out": 0,
    "match_bands": {},
    "review_queue_size": 0,
    "applications_by_status": {},
    "applications_by_outcome": {},
    "applications_prepared": 0,
    "applications_submitted": 0,
    "applications_confirmed": 0,
    "import_failures": 0,
    "audit_entries": 0,
}


class StubClient:
    """A client that answers every call with an empty result set."""

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "test",
            "database": "ok",
            "database_dialect": "sqlite",
            "llm_provider": "none",
            "llm_enabled": False,
            "scheduler_enabled": False,
            "loopback_only": True,
            "automated_submission_supported": False,
        }

    def metrics(self) -> dict:
        return dict(EMPTY_METRICS)

    def estimated_metrics(self) -> dict:
        return {"estimated_minutes_saved": 0, "basis": "Estimate only: 0 prepared."}

    def import_runs(self, limit: int = 25) -> dict:
        return {"items": [], "total": 0, "limit": limit, "offset": 0}

    def list_jobs(self, **_: Any) -> dict:
        return {"items": [], "total": 0, "limit": 10, "offset": 0}

    def list_applications(self, **_: Any) -> dict:
        return {"items": [], "total": 0, "limit": 25, "offset": 0}

    def list_resumes(self) -> dict:
        return {"items": [], "total": 0, "limit": 25, "offset": 0}

    def list_searches(self) -> list:
        return []

    def get_profile(self) -> dict:
        return {
            "id": 1,
            "full_name": "",
            "email": "",
            "phone": "",
            "links": [],
            "headline": "",
            "experience_level": "fresher",
            "years_experience": 0.0,
            "target_titles": [],
            "technical_skills": [],
            "soft_skills": [],
            "education": [],
            "graduation_date": None,
            "projects": [],
            "certifications": [],
            "preferred_locations": [],
            "work_arrangements": [],
            "employment_types": [],
            "open_to_relocation": None,
            "salary_expectation_min": None,
            "salary_expectation_max": None,
            "salary_currency": "INR",
            "notice_period_days": None,
            "work_authorization": None,
            "requires_sponsorship": None,
            "excluded_companies": [],
            "excluded_keywords": [],
            "minimum_match_score": 65.0,
            "max_job_age_days": 30,
            "scoring_weights": {},
            "extra_answers": {},
            "created_at": "2026-10-28T00:00:00+00:00",
            "updated_at": "2026-10-28T00:00:00+00:00",
            "unanswered_sensitive_fields": ["work_authorization", "notice_period_days"],
        }

    def list_batches(self, limit: int = 20, offset: int = 0) -> dict:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    def action_inbox(self, limit: int = 100) -> list[dict]:
        return []

    def list_answers(self) -> list[dict]:
        return []

    def preview_batch(self, payload: dict) -> dict:
        return {"job_ids": [], "total": 0}

    def list_sources(self) -> list[dict]:
        capabilities = {
            "manual_import_enabled": True,
            "authorized_discovery_enabled": False,
            "browser_assistance_enabled": True,
            "automated_submission_enabled": False,
        }
        return [
            {
                "source": "linkedin",
                "display_name": "LinkedIn",
                "enabled": True,
                "capabilities": capabilities,
                "effective_capabilities": capabilities,
                "rate_limit_per_hour": 30,
                "last_run_at": None,
                "last_error": "",
                "consecutive_failures": 0,
                "policy_basis": "LinkedIn's User Agreement prohibits scrapers and bots.",
                "limitations": ["No automated discovery."],
                "status_detail": "manual import is available",
            }
        ]

    def diagnostics(self) -> dict:
        return {
            "entries": [
                {
                    "source": "linkedin",
                    "display_name": "LinkedIn",
                    "healthy": True,
                    "reason": "No automated discovery: the User Agreement prohibits it.",
                    "detail": "this source has never run",
                    "last_run_at": None,
                    "jobs_last_run": None,
                }
            ],
            "llm_provider": "none",
            "llm_enabled": False,
            "scheduler_enabled": False,
            "database_dialect": "sqlite",
            "api_bound_to_loopback": True,
            "display_timezone": "Asia/Kolkata",
        }

    def audit_logs(self, limit: int = 50, offset: int = 0, action: str | None = None) -> dict:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    def get_platform(self, key: str) -> dict:
        return {
            "key": key,
            "display_name": "LinkedIn" if key == "linkedin" else key.title(),
            "tagline": "Import-only.",
            "homepage": "https://www.linkedin.com/jobs",
            "search_url_template": "https://www.linkedin.com/jobs/search/?keywords={query}",
            "how_jobs_arrive": "You bring listings here by URL or CSV. Section 8.2 applies.",
            "notes": ["Alert emails can be ingested."],
            "source_count": 1,
            "discovery_source_count": 0,
            "jobs_stored": 0,
            "applications": 0,
            "supports_automated_discovery": False,
            "supports_automated_submission": False,
            "actions": [
                {
                    "key": "automated_discovery",
                    "label": "Fetch new jobs automatically",
                    "description": "Not available: its terms prohibit automated access.",
                    "available": False,
                },
                {
                    "key": "automated_submission",
                    "label": "Submit the application for you",
                    "description": "Never available on any platform.",
                    "available": False,
                },
                {
                    "key": "import_url",
                    "label": "Add a saved job by URL",
                    "description": "Paste a listing you found yourself.",
                    "available": True,
                },
            ],
            "sources": [
                {
                    "source": "linkedin",
                    "display_name": "LinkedIn",
                    "enabled": True,
                    "capabilities": _CAPS,
                    "effective_capabilities": _CAPS,
                    "policy_basis": "User Agreement s.8.2 prohibits bots and scrapers.",
                    "limitations": ["No jobseeker search API."],
                    "last_run_at": None,
                    "last_error": "",
                    "jobs_stored": 0,
                }
            ],
            "jobs_by_status": {},
            "applications_by_status": {},
        }

    def duplication_metrics(self, suspect_limit: int = 25) -> dict:
        return {
            "jobs_total": 0,
            "sightings_total": 0,
            "merged_sightings": 0,
            "duplicate_rate": 0.0,
            "exact_duplicate_sightings": 0,
            "fuzzy_duplicate_sightings": 0,
            "sightings_by_rule": {},
            "multi_source_jobs": 0,
            "cross_source_duplicate_rate": 0.0,
            "sources_seen": [],
            "source_pair_overlaps": {},
            "jobs_with_application": 0,
            "multi_source_jobs_with_application": 0,
            "missed_merge_suspects": [],
            "false_merge_suspects": [],
            "normalization_collisions": [],
            "buckets_skipped": [],
            "is_healthy": True,
        }


_CAPS: dict = {
    "manual_import_enabled": True,
    "authorized_discovery_enabled": False,
    "browser_assistance_enabled": True,
    "automated_submission_enabled": False,
}


@pytest.fixture
def stub_pages(monkeypatch: pytest.MonkeyPatch) -> StubClient:
    """Point every page at the stub client."""
    stub = StubClient()
    import ui.components as components

    monkeypatch.setattr(components, "get_client", lambda: stub)
    for module in (
        "overview_page",
        "jobs_page",
        "discovery_page",
        "review_page",
        "applications_page",
        "settings_page",
        "diagnostics_page",
        "job_detail_page",
        "resume_page",
        "platform_page",
    ):
        page = __import__(f"ui.views.{module}", fromlist=["render"])
        monkeypatch.setattr(page, "get_client", lambda: stub, raising=False)
    return stub


# --------------------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------------------


def test_a_connection_error_becomes_an_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError()

    monkeypatch.setattr(requests, "request", _refuse)
    with pytest.raises(ApiClientError) as error:
        ApiClient(base_url="http://127.0.0.1:8000").health()

    assert "Cannot reach the API" in error.value.message
    assert "uvicorn" in error.value.message
    assert error.value.code == "connection_error"


def test_a_timeout_becomes_a_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(*_args, **_kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(requests, "request", _timeout)
    with pytest.raises(ApiClientError, match="did not respond"):
        ApiClient(base_url="http://127.0.0.1:8000").health()


def test_the_servers_error_envelope_is_surfaced_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 409
        content = b"{}"

        def json(self) -> dict:
            return {
                "error": {
                    "code": "duplicate_application",
                    "message": "an application already exists",
                    "field_errors": {"job_id": ["already used"]},
                }
            }

    monkeypatch.setattr(requests, "request", lambda *a, **k: Response())
    with pytest.raises(ApiClientError) as error:
        ApiClient(base_url="http://x").get_profile()

    assert error.value.code == "duplicate_application"
    assert error.value.message == "an application already exists"
    assert error.value.field_errors == {"job_id": ["already used"]}


def test_a_token_is_sent_as_a_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self) -> dict:
            return {}

    def _capture(method, url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(requests, "request", _capture)
    ApiClient(base_url="http://x", token="secret").health()
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_no_token_means_no_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self) -> dict:
            return {}

    monkeypatch.setattr(
        requests, "request", lambda method, url, **kwargs: (captured.update(kwargs), Response())[1]
    )
    ApiClient(base_url="http://x").health()
    assert captured["headers"] == {}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def test_utc_timestamps_render_in_the_display_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_DISPLAY_TIMEZONE", "Asia/Kolkata")
    assert local_time("2026-10-28T00:00:00+00:00") == "28 Oct 2026, 05:30"
    assert local_date("2026-10-28T20:00:00Z") == "29 Oct 2026"


def test_a_missing_timestamp_renders_as_unknown() -> None:
    assert local_time(None) == "unknown"
    assert local_time("") == "unknown"


def test_an_unparseable_timestamp_is_returned_unchanged() -> None:
    assert local_time("not a date") == "not a date"


def test_an_unknown_timezone_falls_back_to_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_DISPLAY_TIMEZONE", "Mars/Olympus_Mons")
    assert local_time("2026-10-28T00:00:00+00:00") == "28 Oct 2026, 00:00"


def test_band_badge_and_skill_chips_render_safely() -> None:
    assert "High match" in band_badge("high", 91.0)
    assert "Unscored" in band_badge("", 0.0)
    assert "none" in skill_chips([], "#fff")
    assert "python" in skill_chips(["python"], "#fff")


# --------------------------------------------------------------------------------------
# Page empty states
# --------------------------------------------------------------------------------------


def _messages(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.info, app.markdown, app.caption, app.warning, app.error, app.success):
        parts.extend(str(element.value) for element in collection)
    return " ".join(parts)


def _render(module_name: str) -> AppTest:
    """Run one page headlessly.

    ``AppTest.from_function`` re-executes the function body in a bare namespace, which
    loses the page module's imports. Running a harness script that imports the page keeps
    the real module object, so the monkeypatched client is the one the page uses.
    """
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        f"from ui.views import {module_name}\n"
        f"{module_name}.render()\n"
    )
    app = AppTest.from_string(script)
    app.run(timeout=30)
    return app


def test_the_overview_shows_an_actionable_empty_state(stub_pages: StubClient) -> None:
    app = _render("overview_page")
    assert not app.exception
    text = _messages(app)
    assert "No jobs yet" in text
    assert "Job discovery" in text


def test_the_job_feed_shows_an_empty_state_and_no_crash(stub_pages: StubClient) -> None:
    app = _render("jobs_page")
    assert not app.exception
    assert "No jobs" in _messages(app)


def test_the_review_queue_shows_an_empty_state(stub_pages: StubClient) -> None:
    app = _render("review_page")
    assert not app.exception
    assert "Nothing waiting for review" in _messages(app)


def test_the_tracker_shows_an_empty_state(stub_pages: StubClient) -> None:
    app = _render("applications_page")
    assert not app.exception
    assert "No applications tracked yet" in _messages(app)


def test_the_job_detail_page_shows_an_empty_state(stub_pages: StubClient) -> None:
    app = _render("job_detail_page")
    assert not app.exception
    assert "No jobs to inspect" in _messages(app)


def test_the_discovery_page_explains_why_discovery_is_unavailable(
    stub_pages: StubClient,
) -> None:
    app = _render("discovery_page")
    assert not app.exception
    assert "No source currently has automated discovery enabled" in _messages(app)


def test_the_settings_page_states_that_submission_is_permanently_off(
    stub_pages: StubClient,
) -> None:
    app = _render("settings_page")
    assert not app.exception
    text = _messages(app)
    assert "permanently off for every source" in text
    assert "No LLM is configured" in text


def test_the_diagnostics_page_renders_with_no_audit_entries(stub_pages: StubClient) -> None:
    app = _render("diagnostics_page")
    assert not app.exception
    assert "No audit entries match" in _messages(app)


def test_the_diagnostics_page_reports_duplication_rates_and_suspects(
    stub_pages: StubClient,
) -> None:
    """The panel must show the rates and both failure directions, not just a headline."""
    stub_pages.duplication_metrics = lambda suspect_limit=25: {  # type: ignore[method-assign]
        "jobs_total": 7791,
        "sightings_total": 8070,
        "merged_sightings": 279,
        "duplicate_rate": 0.0346,
        "exact_duplicate_sightings": 0,
        "fuzzy_duplicate_sightings": 279,
        "sightings_by_rule": {"new": 7791, "same_fingerprint": 279},
        "multi_source_jobs": 10,
        "cross_source_duplicate_rate": 0.0013,
        "sources_seen": ["greenhouse", "lever", "arbeitnow"],
        "source_pair_overlaps": {"arbeitnow+greenhouse": 8},
        "jobs_with_application": 14,
        "multi_source_jobs_with_application": 1,
        "missed_merge_suspects": [
            {
                "job_ids": [756, 757],
                "titles": ["Account Executive", "Account Executive (Bengaluru, India)"],
                "company": "Figma",
                "sources": ["greenhouse"],
                "title_overlap": 1.0,
                "reason": "titles overlap by 100% at the same company",
            }
        ],
        "false_merge_suspects": [
            {
                "job_id": 2845,
                "stored_title": "PhD - Safety Contracts for Physical AI",
                "observed_titles": ["PhD - Safety Contracts", "PhD - Winding Schemes"],
                "observed_companies": ["Bosch Group"],
                "sources": ["smartrecruiters"],
                "title_overlap": 0.05,
                "reason": "sighting titles overlap by only 5%",
            }
        ],
        "normalization_collisions": [],
        "buckets_skipped": [],
        "is_healthy": False,
    }

    app = _render("diagnostics_page")
    assert not app.exception
    text = _messages(app)
    assert "3.5%" in text, "the duplicate rate must be shown"
    assert "sightings disagree" in text, "the false-merge warning must be shown"
    assert "never deletes a job" in text, "the additive-merge guarantee must be stated"

    tables = "".join(str(frame.value) for frame in app.dataframe)
    assert "2845" in tables, "a false-merge suspect must be tabulated"
    assert "Figma" in tables, "a missed-merge suspect must be tabulated"
    assert "arbeitnow + greenhouse" in tables, "the overlapping source pair must be tabulated"


def test_the_resume_page_warns_about_unanswered_sensitive_fields(
    stub_pages: StubClient,
) -> None:
    app = _render("resume_page")
    assert not app.exception
    text = _messages(app)
    assert "never guessed" in text
    assert "work_authorization" in text


def test_the_bulk_preparation_page_shows_an_empty_state(stub_pages: StubClient) -> None:
    app = _render("batch_page")
    assert not app.exception
    text = _messages(app)
    assert "No bulk run yet" in text
    assert "never submits" in text


def test_the_action_inbox_shows_an_empty_state(stub_pages: StubClient) -> None:
    app = _render("inbox_page")
    assert not app.exception
    text = _messages(app)
    assert "Nothing is waiting on you" in text


def test_no_page_offers_to_submit_an_application(stub_pages: StubClient) -> None:
    """A new page must not introduce a submit control the backend cannot honour."""
    for module in ("batch_page", "inbox_page", "review_page"):
        app = _render(module)
        assert not app.exception
        labels = [button.label.lower() for button in app.button]
        assert not any(
            label in {"submit", "apply", "submit application", "auto apply"} for label in labels
        ), f"{module} exposes a submit-like control: {labels}"


def test_the_inbox_save_control_lives_in_a_form(stub_pages: StubClient) -> None:
    """One click must save, so the control cannot be a bare button next to a text area.

    Streamlit commits a text area on blur, so a plain button spends the first click
    committing the typed text and discards it — the user has to click twice and the
    answer appears not to save. A form submits both together. ``AppTest.button`` lists
    only non-form buttons, so an empty result here is the guarantee.
    """
    app = _render("inbox_page")
    assert not app.exception
    labels = [button.label for button in app.button]
    assert "Save answer" not in labels
    assert "Update" not in labels


# --------------------------------------------------------------------------------------
# Matching confidence on the dashboard
# --------------------------------------------------------------------------------------

LOW_CONFIDENCE_MATCH: dict[str, Any] = {
    "total_score": 88.4,
    "band": "review",
    "evidence_coverage": 0.6,
    "confidence": "low",
    "confidence_reasons": [
        "only 60% of the scoring weight could be assessed from this listing",
        "the employer published no requirements list, so skills were inferred",
    ],
    "category_scores": {
        "skills": {"score": 75.0, "weight": 0.58, "assessable": True, "detail": "2 inferred"},
        "title": {"score": 100.0, "weight": 0.42, "assessable": True, "detail": "exact overlap"},
        "freshness": {
            "score": 0.0,
            "weight": 0.0,
            "assessable": False,
            "detail": "the source gave no posting date",
        },
        "location": {
            "score": 0.0,
            "weight": 0.0,
            "assessable": False,
            "detail": "the listing stated no location",
        },
    },
    "weights_used": {},
    "matched_skills": ["python"],
    "missing_required_skills": [],
    "missing_preferred_skills": [],
    "uncertain_requirements": ["fastapi"],
    "explanation": ["Evidence confidence: low - only 60% of the scoring weight could be assessed."],
    "filtered_out": False,
    "filter_reasons": [],
    "scorer": "rule_based_v1",
    "scored_at": "2026-10-30T00:00:00+00:00",
}

SCORED_JOB: dict[str, Any] = {
    "id": 7,
    "title": "Software Engineer",
    "company": "Terse Listings Inc",
    "location": None,
    "work_arrangement": "unknown",
    "employment_type": "full_time",
    "status": "SCORED",
    "posted_at": None,
    "posted_at_is_approximate": False,
    "discovered_at": "2026-10-30T00:00:00+00:00",
    "salary_raw": "",
    "experience_raw": "",
    "url": "https://example.com/jobs/7",
    "description": "We are hiring a software engineer. Apply now.",
    "fingerprint": "abcdef0123456789abcdef",
    "application_method": "external",
    "source_references": [
        {
            "source": "greenhouse",
            "external_id": "7",
            "url": "https://example.com/jobs/7",
            "retrieved_at": "2026-10-30T00:00:00+00:00",
            "retrieval_method": "api",
        }
    ],
    "match": LOW_CONFIDENCE_MATCH,
}


class ScoredStubClient(StubClient):
    """A stub holding one scored job whose evidence is deliberately weak."""

    def list_jobs(self, **_: Any) -> dict:
        return {"items": [dict(SCORED_JOB)], "total": 1, "limit": 10, "offset": 0}

    def get_job(self, job_id: int) -> dict:
        return dict(SCORED_JOB)


@pytest.fixture
def scored_pages(monkeypatch: pytest.MonkeyPatch) -> ScoredStubClient:
    stub = ScoredStubClient()
    import ui.components as components

    monkeypatch.setattr(components, "get_client", lambda: stub)
    for module in ("jobs_page", "job_detail_page"):
        page = __import__(f"ui.views.{module}", fromlist=["render"])
        monkeypatch.setattr(page, "get_client", lambda: stub, raising=False)
    return stub


def test_confidence_badge_names_the_level_and_the_coverage() -> None:
    html = confidence_badge("low", 0.6)
    assert "Low confidence" in html
    assert "60% evidence" in html
    assert "High confidence" in confidence_badge("high", 1.0)
    assert "Unknown confidence" in confidence_badge("", None)


def test_confidence_badge_never_uses_an_error_colour() -> None:
    """Low confidence describes the listing's evidence, not a fault, so it is never red."""
    for level in ("high", "medium", "low"):
        tone = CONFIDENCE_TONES[level]
        assert tone in {"green", "amber", "slate"}


def test_unassessable_fields_names_each_gap_with_its_reason() -> None:
    gaps = unassessable_fields(LOW_CONFIDENCE_MATCH["category_scores"])
    assert any("freshness" in gap and "no posting date" in gap for gap in gaps)
    assert any("location" in gap and "stated no location" in gap for gap in gaps)
    assert not any("skills" in gap for gap in gaps)


def test_evidence_block_lists_reasons_gaps_and_uncertain_fields() -> None:
    html = evidence_block(LOW_CONFIDENCE_MATCH)
    assert "Low confidence" in html
    assert "Why this confidence level" in html
    assert "only 60% of the scoring weight could be assessed" in html
    assert "Information this listing did not provide" in html
    assert "Uncertain fields" in html
    assert "fastapi" in html


def test_evidence_block_escapes_untrusted_reason_text() -> None:
    html = evidence_block(
        {
            "confidence": "low",
            "evidence_coverage": 0.5,
            "confidence_reasons": ["<script>alert(1)</script>"],
            "category_scores": {},
            "uncertain_requirements": [],
        }
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_evidence_block_states_when_everything_was_assessable() -> None:
    html = evidence_block(
        {
            "confidence": "high",
            "evidence_coverage": 1.0,
            "confidence_reasons": [],
            "category_scores": {"skills": {"score": 90.0, "weight": 0.35, "assessable": True}},
            "uncertain_requirements": [],
        }
    )
    assert "Every scoring category could be assessed" in html


def test_evidence_block_is_empty_for_an_unscored_job() -> None:
    assert evidence_block({}) == ""


def test_the_job_feed_shows_confidence_on_every_card(scored_pages: ScoredStubClient) -> None:
    app = _render("jobs_page")
    assert not app.exception
    text = _messages(app)
    assert "Low confidence" in text
    assert "60% evidence" in text
    assert "only 60% of the scoring weight could be assessed" in text
    assert "no posting date" in text


def test_the_job_feed_still_shows_the_score_and_band(scored_pages: ScoredStubClient) -> None:
    """Confidence is added alongside the score; it must not replace or alter it."""
    app = _render("jobs_page")
    text = _messages(app)
    assert "88" in text
    assert "Worth a look" in text


def test_the_job_detail_page_reports_confidence_and_coverage(
    scored_pages: ScoredStubClient,
) -> None:
    app = _render("job_detail_page")
    assert not app.exception
    text = _messages(app)
    assert "Confidence" in text
    assert "Evidence coverage" in text
    assert "60%" in text
    assert "Why this confidence level" in text
    assert "stated no location" in text


# --------------------------------------------------------------------------------------
# Platform assistant pages
# --------------------------------------------------------------------------------------


def _render_platform(key: str) -> AppTest:
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "from ui.views import platform_page\n"
        f"platform_page.render({key!r})\n"
    )
    app = AppTest.from_string(script)
    app.run(timeout=40)
    return app


@pytest.mark.parametrize("key", ["naukri", "linkedin", "indeed", "wellfound", "ats"])
def test_every_platform_page_renders(stub_pages: StubClient, key: str) -> None:
    app = _render_platform(key)
    assert not app.exception


def test_a_platform_page_states_how_jobs_arrive_and_what_is_unavailable(
    stub_pages: StubClient,
) -> None:
    app = _render_platform("linkedin")
    assert not app.exception
    text = _messages(app)
    assert "How jobs get in" in text
    assert "8.2" in text, "the policy basis must reach the user, not just the docs"
    assert "import-only by policy" in text, "an honest label, not a missing feature"
    assert "Never available on any platform" in text


def test_a_platform_page_with_no_jobs_shows_an_empty_state_not_a_fake_count(
    stub_pages: StubClient,
) -> None:
    app = _render_platform("naukri")
    assert not app.exception
    text = _messages(app)
    assert "Nothing stored from this platform yet" in text
    assert "No applications prepared for this platform yet" in text


# --------------------------------------------------------------------------------------
# Saved searches
# --------------------------------------------------------------------------------------


def test_saved_searches_shows_an_empty_state_and_no_crash(stub_pages: StubClient) -> None:
    app = _render("searches_page")
    assert not app.exception
    text = _messages(app)
    assert "No saved searches yet" in text


def test_saved_searches_states_that_nothing_runs_in_the_background(
    stub_pages: StubClient,
) -> None:
    """The page must not imply alerts arrive on their own; there is no background worker."""
    app = _render("searches_page")
    assert not app.exception
    assert "background" in _messages(app).lower()


def test_the_saved_search_inputs_are_wrapped_in_a_form() -> None:
    """A text input commits on blur, so a bare button needs two clicks to register a value.

    Asserted structurally rather than through ``AppTest.button``, which lists form-submit
    buttons alongside plain ones in this Streamlit version and so cannot tell them apart.
    """
    import ast

    source = (PROJECT_ROOT / "ui" / "views" / "searches_page.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    submit_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "form_submit_button"
    ]
    plain_buttons_with_save = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "button"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and "Save" in str(node.args[0].value)
    ]
    assert submit_calls, "the create form must submit through st.form_submit_button"
    assert not plain_buttons_with_save, (
        "a plain st.button next to a text input needs two clicks to save"
    )
