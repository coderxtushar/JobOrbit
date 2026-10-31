"""ATS board adapter tests.

No test touches the network. Each one replaces ``requests.get`` with a stub, because the
default suite must prove the adapters work with no credentials and no connectivity. The
payload fixtures are trimmed copies of real responses from each endpoint.
"""

from __future__ import annotations

import pytest

from app.config import get_settings, reset_settings_cache
from app.db.models import SourceName
from app.sources.ats import GreenhouseAdapter, LeverAdapter, WorkableAdapter
from app.sources.base import CapabilityNotAvailable, SourceUnavailable
from app.sources.registry import DISCOVERY_SOURCES, get_adapter

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 8159652,
            "title": "Backend Engineer",
            "absolute_url": "https://jobs.dropbox.com/listing/8159652",
            "company_name": "Dropbox",
            "location": {"name": "Remote - US"},
            "first_published": "2026-09-01T09:20:17-04:00",
            "updated_at": "2026-10-23T10:22:11-04:00",
            "requisition_id": "R1234",
            "departments": [{"name": "Engineering"}],
            "content": "&lt;p&gt;Build APIs in &lt;strong&gt;Python&lt;/strong&gt;.&lt;/p&gt;",
        },
        {"title": "", "absolute_url": "https://example.com/x"},
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "2a55d6c9-c564-443a-be3e-a3851db5a93b",
        "text": "Python Developer",
        "hostedUrl": "https://jobs.lever.co/spotify/2a55d6c9",
        "applyUrl": "https://jobs.lever.co/spotify/2a55d6c9/apply",
        "categories": {
            "location": "New York, NY",
            "commitment": "Full-time",
            "team": "Platform",
            "department": "Engineering",
        },
        "createdAt": 1761231640768,
        "descriptionPlain": "Work on backend services.",
        "additionalPlain": "Python and SQL required.",
        "workplaceType": "hybrid",
    },
    {"text": "No URL Role", "categories": {}},
]

WORKABLE_PAYLOAD = {
    "name": "Trail of Bits",
    "description": "Security research.",
    "jobs": [
        {
            "title": "Security Engineer I, Application Security",
            "shortcode": "BA9F2FCDA6",
            "code": "",
            "url": "https://apply.workable.com/j/BA9F2FCDA6",
            "shortlink": "https://apply.workable.com/j/BA9F2FCDA6",
            "application_url": "https://apply.workable.com/j/BA9F2FCDA6/apply",
            "city": "",
            "state": "",
            "country": "United States",
            "locations": [
                {"country": "United States", "countryCode": "US", "city": "", "region": None}
            ],
            "department": "Assurance",
            "function": "",
            "employment_type": "Full-time",
            "experience": "Entry level",
            "education": "None",
            "telecommuting": True,
            "created_at": "2026-09-24",
            "published_on": "2026-09-24",
            "description": "<p>Audit smart contracts using <strong>Python</strong>.</p>",
        },
        {
            "title": "ML Engineer - EMEA",
            "shortcode": "81B46579FE",
            "url": "https://apply.workable.com/j/81B46579FE",
            "city": "Paris",
            "state": "Île-de-France",
            "country": "France",
            "employment_type": "Full-time",
            "experience": "Director",
            "education": "Bachelor's Degree",
            "telecommuting": True,
            "published_on": "2026-05-29",
            "description": "<p>Open-source ML.</p>",
        },
        {"title": "No URL Role", "city": "Remote"},
    ],
}


class _Response:
    def __init__(self, payload, status_code: int = 200, valid_json: bool = True) -> None:
        self._payload = payload
        self.status_code = status_code
        self._valid_json = valid_json

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if not self._valid_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Fail loudly if a test reaches the network instead of using a stub."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("a test attempted a real HTTP request")

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _forbidden)
    return monkeypatch


def _stub(monkeypatch: pytest.MonkeyPatch, response, calls: list[str] | None = None) -> None:
    def _get(url, **kwargs):
        if calls is not None:
            calls.append(url)
        return response() if callable(response) else response

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _get)


def test_every_discovery_source_is_a_mailbox_or_a_published_api() -> None:
    assert set(DISCOVERY_SOURCES) == {
        SourceName.EMAIL_ALERT,
        SourceName.GREENHOUSE,
        SourceName.LEVER,
        SourceName.WORKABLE,
        SourceName.ASHBY,
        SourceName.SMARTRECRUITERS,
        SourceName.ARBEITNOW,
        SourceName.REMOTEOK,
        SourceName.REMOTIVE,
        SourceName.HIMALAYAS,
        SourceName.JOBICY,
    }
    for source in (
        SourceName.GREENHOUSE,
        SourceName.LEVER,
        SourceName.WORKABLE,
        SourceName.ASHBY,
        SourceName.SMARTRECRUITERS,
    ):
        adapter = get_adapter(source)
        assert adapter.capabilities.authorized_discovery_enabled is True
        assert adapter.capabilities.automated_submission_enabled is False
        assert adapter.policy_basis
        assert adapter.limitations


def test_nothing_is_fetched_until_a_board_is_configured(no_network) -> None:
    for adapter_class in (GreenhouseAdapter, LeverAdapter, WorkableAdapter):
        adapter = adapter_class()
        with pytest.raises(CapabilityNotAvailable) as exc:
            adapter.discover()
        assert "configured" in str(exc.value)
        assert adapter.env_var in str(exc.value)


def test_discovery_can_be_switched_off_entirely(
    monkeypatch: pytest.MonkeyPatch, no_network
) -> None:
    monkeypatch.setenv("JA_ATS_DISCOVERY_ENABLED", "false")
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "dropbox")
    reset_settings_cache()
    with pytest.raises(CapabilityNotAvailable, match="switched off"):
        GreenhouseAdapter(get_settings()).discover()
    reset_settings_cache()


def test_board_tokens_are_parsed_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", " dropbox , stripe ;dropbox, ")
    reset_settings_cache()
    assert get_settings().board_tokens("greenhouse") == ("dropbox", "stripe")
    assert get_settings().board_tokens("lever") == ()
    reset_settings_cache()


def test_greenhouse_maps_a_real_payload_including_the_posting_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "dropbox")
    reset_settings_cache()
    calls: list[str] = []
    _stub(monkeypatch, _Response(GREENHOUSE_PAYLOAD), calls)

    result = GreenhouseAdapter(get_settings()).discover()

    assert calls == ["https://boards-api.greenhouse.io/v1/boards/dropbox/jobs?content=true"]
    assert len(result.records) == 1
    assert result.invalid_count == 1
    record = result.records[0]
    assert record.source is SourceName.GREENHOUSE
    assert record.title == "Backend Engineer"
    assert record.company == "Dropbox"
    assert record.location == "Remote - US"
    assert record.external_id == "8159652"
    assert record.retrieval_method == "greenhouse_job_board_api"
    assert record.posted_at is not None
    assert record.posted_at.year == 2026 and record.posted_at.month == 9
    assert "Build APIs in Python." in record.description
    assert "<p>" not in record.description
    assert result.metadata["jobs_per_board"] == {"dropbox": 1}
    reset_settings_cache()


def test_one_pathological_posting_does_not_discard_the_whole_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single over-long field must cost one posting, never the whole company board.

    Observed on Greenhouse's live ``databricks`` board: one role's location is a
    300-plus character list of US states. Before the fix a parse failure was reported
    per board, so that one row discarded every other posting the board published.
    """
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "databricks")
    reset_settings_cache()
    long_location = ", ".join(["California"] * 40)
    assert len(long_location) > 300
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Pathological Role",
                "absolute_url": "https://example.com/1",
                "company_name": "Databricks",
                "location": {"name": long_location},
            },
            {
                "id": 2,
                "title": "Healthy Role",
                "absolute_url": "https://example.com/2",
                "company_name": "Databricks",
                "location": {"name": "Bengaluru, India"},
            },
        ]
    }
    _stub(monkeypatch, _Response(payload))

    result = GreenhouseAdapter(get_settings()).discover()

    titles = {record.title for record in result.records}
    assert "Healthy Role" in titles, "a sibling posting was lost to an unrelated bad row"
    assert result.errors == []
    clipped = next(r for r in result.records if r.title == "Pathological Role")
    assert len(clipped.location or "") <= 300
    assert (clipped.location or "").startswith("California")
    reset_settings_cache()


def test_an_over_long_url_skips_only_that_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL is never clipped — a truncated link is broken — so the row is skipped instead."""
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "databricks")
    reset_settings_cache()
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Unreachable Role",
                "absolute_url": "https://example.com/" + ("x" * 3000),
                "company_name": "Databricks",
                "location": {"name": "Remote"},
            },
            {
                "id": 2,
                "title": "Healthy Role",
                "absolute_url": "https://example.com/2",
                "company_name": "Databricks",
                "location": {"name": "Remote"},
            },
        ]
    }
    _stub(monkeypatch, _Response(payload))

    result = GreenhouseAdapter(get_settings()).discover()

    assert [record.title for record in result.records] == ["Healthy Role"]
    assert result.invalid_count == 1
    assert result.errors == []
    reset_settings_cache()


def test_lever_maps_a_real_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_LEVER_BOARDS", "spotify")
    reset_settings_cache()
    _stub(monkeypatch, _Response(LEVER_PAYLOAD))

    result = LeverAdapter(get_settings()).discover()

    assert len(result.records) == 1
    assert result.invalid_count == 1
    record = result.records[0]
    assert record.title == "Python Developer"
    assert record.company == "spotify"
    assert record.location == "New York, NY"
    assert record.employment_type == "Full-time"
    assert record.posted_at is not None
    assert "Python and SQL required." in record.description
    reset_settings_cache()


def test_workable_maps_the_shape_verified_against_a_live_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Field names here were read off three real Workable boards, not guessed.

    The earlier mapping expected a nested ``location`` object, which is Greenhouse's shape,
    not Workable's. Workable exposes flat city/state/country, so every Workable job was
    being stored with an empty location.
    """
    monkeypatch.setenv("JA_WORKABLE_BOARDS", "trailofbits")
    reset_settings_cache()
    _stub(monkeypatch, _Response(WORKABLE_PAYLOAD))

    result = WorkableAdapter(get_settings()).discover()

    assert len(result.records) == 2
    assert result.invalid_count == 1

    first = result.records[0]
    assert first.title == "Security Engineer I, Application Security"
    assert first.company == "Trail of Bits"
    assert first.location == "United States"
    assert first.work_arrangement == "remote"
    assert first.external_id == "BA9F2FCDA6"
    assert first.employment_type == "Full-time"
    assert first.experience_raw == "Entry level"
    assert first.education_requirements == [], "the literal string 'None' is not a requirement"
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert "Python" in first.description and "<p>" not in first.description

    second = result.records[1]
    assert second.location == "Paris, Île-de-France, France"
    assert second.education_requirements == ["Bachelor's Degree"]
    assert second.experience_raw == "Director"
    reset_settings_cache()


def test_a_workable_seniority_label_makes_experience_assessable() -> None:
    """A label instead of a year range must still produce an eligibility bound.

    Otherwise the experience category is unassessable, its weight is redistributed, and a
    director-level posting receives no seniority penalty whatsoever.
    """
    from app.services.normalization import parse_experience

    assert parse_experience("Entry level") == (0.0, None)
    assert parse_experience("Internship") == (0.0, 1.0)
    assert parse_experience("Associate") == (1.0, 3.0)
    assert parse_experience("Mid-Senior level") == (3.0, 8.0)
    assert parse_experience("Director") == (8.0, None)
    assert parse_experience("Executive") == (10.0, None)
    assert parse_experience("0-1 years") == (0.0, 1.0)


def test_an_empty_board_reports_zero_jobs_rather_than_inventing_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_WORKABLE_BOARDS", "example")
    reset_settings_cache()
    _stub(monkeypatch, _Response({"name": "Example Co", "jobs": []}))
    result = WorkableAdapter(get_settings()).discover()
    assert result.records == []
    assert result.errors == []
    reset_settings_cache()


def test_a_wrong_board_identifier_is_reported_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "nope,dropbox")
    reset_settings_cache()
    calls: list[str] = []

    def _responder():
        url = calls[-1]
        if "nope" in url:
            return _Response(None, status_code=404)
        return _Response(GREENHOUSE_PAYLOAD)

    _stub(monkeypatch, _responder, calls)
    result = GreenhouseAdapter(get_settings()).discover()

    assert len(calls) == 2
    assert len(result.records) == 1
    assert any("nope" in error and "404" in error for error in result.errors)
    reset_settings_cache()


def test_a_transient_failure_is_retried_with_backoff_and_then_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "dropbox")
    monkeypatch.setenv("JA_ATS_MAX_ATTEMPTS", "3")
    reset_settings_cache()
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr("app.sources.http_fetch.time.sleep", lambda delay: sleeps.append(delay))
    _stub(monkeypatch, _Response(None, status_code=503), calls)

    with pytest.raises(SourceUnavailable, match="every configured"):
        GreenhouseAdapter(get_settings()).discover()

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    reset_settings_cache()


def test_a_recoverable_board_keeps_the_run_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "flaky,dropbox")
    monkeypatch.setenv("JA_ATS_MAX_ATTEMPTS", "2")
    reset_settings_cache()
    calls: list[str] = []
    monkeypatch.setattr("app.sources.http_fetch.time.sleep", lambda _delay: None)

    def _responder():
        if "flaky" in calls[-1]:
            return _Response(None, status_code=500)
        return _Response(GREENHOUSE_PAYLOAD)

    _stub(monkeypatch, _responder, calls)
    result = GreenhouseAdapter(get_settings()).discover()

    assert len(result.records) == 1
    assert any("flaky" in error for error in result.errors)
    reset_settings_cache()


def test_malformed_json_is_reported_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_LEVER_BOARDS", "spotify")
    reset_settings_cache()
    _stub(monkeypatch, _Response(None, valid_json=False))
    with pytest.raises(SourceUnavailable, match="not valid JSON"):
        LeverAdapter(get_settings()).discover()
    reset_settings_cache()


def test_an_unexpected_shape_is_reported_against_the_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_LEVER_BOARDS", "spotify,other")
    reset_settings_cache()
    calls: list[str] = []

    def _responder():
        if "other" in calls[-1]:
            return _Response(LEVER_PAYLOAD)
        return _Response({"unexpected": "object"})

    _stub(monkeypatch, _responder, calls)
    result = LeverAdapter(get_settings()).discover()

    assert len(result.records) == 1
    assert any("not understood" in error for error in result.errors)
    reset_settings_cache()


def test_a_job_description_cannot_smuggle_markup_through_the_stripper() -> None:
    """Imported text is untrusted: no tag may survive, however it is encoded."""
    from app.services.text import strip_html

    hostile = "&lt;script&gt;alert(1)&lt;/script&gt;<img src=x onerror=alert(2)>"
    cleaned = strip_html(hostile)
    assert "<" not in cleaned
    assert "onerror" not in cleaned


def test_a_board_query_can_override_the_configured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_GREENHOUSE_BOARDS", "configured")
    reset_settings_cache()
    calls: list[str] = []
    _stub(monkeypatch, _Response(GREENHOUSE_PAYLOAD), calls)

    GreenhouseAdapter(get_settings()).discover(query={"boards": ["explicit"]})

    assert calls == ["https://boards-api.greenhouse.io/v1/boards/explicit/jobs?content=true"]
    reset_settings_cache()


def test_import_only_platforms_state_their_basis_and_refuse_discovery() -> None:
    for source in (
        SourceName.INSTAHYRE,
        SourceName.CUTSHORT,
        SourceName.HIRIST,
        SourceName.WORKDAY,
        SourceName.COMPANY_SITE,
    ):
        adapter = get_adapter(source)
        assert adapter.capabilities.authorized_discovery_enabled is False
        assert adapter.capabilities.automated_submission_enabled is False
        assert len(adapter.policy_basis) > 40
        assert adapter.limitations
        with pytest.raises(CapabilityNotAvailable):
            adapter.discover()


def test_workday_explains_why_a_reachable_endpoint_is_deliberately_unused() -> None:
    """The refusal must name the reason, because the endpoint plainly exists."""
    adapter = get_adapter(SourceName.WORKDAY)
    basis = adapter.policy_basis.lower()
    assert "credentials" in basis
    assert "internal" in basis
    joined = " ".join(adapter.limitations).lower()
    assert "technically reachable" in joined
