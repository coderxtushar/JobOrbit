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
from ui.components import band_badge, local_date, local_time, skill_chips

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
