"""Tests for the discovery sources added after the three original ATS boards.

Covers Ashby and SmartRecruiters (per-company boards) and the five open job feeds. No test
touches the network: ``requests.get`` is replaced in every case, because the default suite
must prove these adapters work with no credentials and no connectivity. Every payload
below is a trimmed copy of a response actually observed from the endpoint it names,
including the quirks that broke a first implementation.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings, reset_settings_cache
from app.db.models import SourceName
from app.sources.aggregators import (
    ArbeitnowAdapter,
    HimalayasAdapter,
    JobicyAdapter,
    RemoteOkAdapter,
    RemotiveAdapter,
)
from app.sources.ats import AshbyAdapter, SmartRecruitersAdapter
from app.sources.base import CapabilityNotAvailable, SourceUnavailable

ASHBY_PAYLOAD = {
    "apiVersion": 1,
    "jobs": [
        {
            "id": "7458d4e9-da2e-47bd-98cb-adfda43d42b2",
            "title": "Software Engineer, Backend",
            "department": "Engineering",
            "team": "Platform",
            "employmentType": "FullTime",
            "location": "Remote - European Union",
            "secondaryLocations": [{"location": "Spain"}],
            "publishedAt": "2026-09-08T16:27:26.694+00:00",
            "isListed": True,
            "isRemote": True,
            "workplaceType": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/ashby/7458d4e9",
            "applyUrl": "https://jobs.ashbyhq.com/ashby/7458d4e9/application",
            "descriptionPlain": "Build backend services in Python.",
            "descriptionHtml": "<p>Build backend services in <b>Python</b>.</p>",
        },
        {
            "id": "intern-1",
            "title": "Engineering Intern",
            "employmentType": "Intern",
            "location": "",
            "secondaryLocations": [{"location": "New York"}],
            "publishedAt": "2026-10-01T10:00:00.000+00:00",
            "isListed": True,
            "isRemote": False,
            "workplaceType": "OnSite",
            "jobUrl": "https://jobs.ashbyhq.com/ashby/intern-1",
            "descriptionPlain": "",
            "descriptionHtml": "<p>Summer programme in <b>Go</b>.</p>",
        },
        {
            "id": "hidden-1",
            "title": "Confidential Role",
            "isListed": False,
            "jobUrl": "https://jobs.ashbyhq.com/ashby/hidden-1",
        },
        {"title": "No URL Role", "isListed": True},
    ],
}

SMARTRECRUITERS_PAGE_1: dict[str, Any] = {
    "offset": 0,
    "limit": 100,
    "totalFound": 150,
    "content": [
        {
            "id": "744000158499259",
            "name": "Software Development Engineer",
            "uuid": "2f2adfb6-b9cf-40c3-a819-e50c34bd6f51",
            "refNumber": "REF299473O",
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
            "releasedDate": "2026-10-29T11:49:12.971Z",
            "location": {
                "city": "bangalore",
                "country": "in",
                "remote": False,
                "hybrid": False,
                "fullLocation": "bangalore, , India",
            },
            "industry": {"id": "computer_software", "label": "Computer Software"},
            "function": {"id": "information_technology", "label": "Information Technology"},
            "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
            "experienceLevel": {"id": "associate", "label": "Associate"},
            "visibility": "PUBLIC",
        },
        {
            "id": "744000158499999",
            "name": "Internal Only Role",
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
            "location": {"fullLocation": "Stuttgart, , Germany"},
            "visibility": "INTERNAL",
        },
    ],
}

SMARTRECRUITERS_PAGE_2: dict[str, Any] = {
    "offset": 100,
    "limit": 100,
    "totalFound": 150,
    "content": [
        {
            "id": "744000158499546",
            "name": "SAP IT Functional Consultant",
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
            "releasedDate": "2026-10-29T11:47:28.935Z",
            "location": {
                "city": "Timișoara",
                "region": "TM",
                "country": "ro",
                "remote": True,
                "fullLocation": "Timișoara, TM, Romania",
            },
            "typeOfEmployment": {"label": "Full-time"},
            "experienceLevel": {"label": "Mid-Senior Level"},
            "visibility": "PUBLIC",
        }
    ],
}

SMARTRECRUITERS_DETAIL: dict[str, Any] = {
    "id": "744000158499259",
    "name": "Software Development Engineer",
    "applyUrl": "https://jobs.smartrecruiters.com/BoschGroup/744000158499259-software",
    "jobAd": {
        "sections": {
            "companyDescription": {"title": "Company Description", "text": "<p>About us.</p>"},
            "jobDescription": {"title": "Job Description", "text": "<p>Write <b>Python</b>.</p>"},
            "qualifications": {"title": "Qualifications", "text": "<p>B.Tech required.</p>"},
        }
    },
}

ARBEITNOW_PAGE_1: dict[str, Any] = {
    "data": [
        {
            "slug": "backend-engineer-328",
            "company_name": "Capco",
            "title": "Backend Engineer",
            "description": "<p>Work with <strong>Python</strong> and FastAPI.</p>",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/companies/capco/backend-engineer-328",
            "tags": ["python", "fastapi"],
            "job_types": ["Unbefristeter arbeitsvertrag"],
            "location": "Berlin",
            "created_at": 1793267716,
        },
        {"title": "No URL Role", "company_name": "Capco"},
        {"title": "No Company Role", "url": "https://www.arbeitnow.com/jobs/x"},
    ],
    "links": {
        "first": "https://www.arbeitnow.com/api/job-board-api?page=1",
        "last": None,
        "prev": None,
        "next": "https://www.arbeitnow.com/api/job-board-api?page=2",
    },
    "meta": {"current_page": 1, "per_page": 300},
}

ARBEITNOW_PAGE_2: dict[str, Any] = {
    "data": [
        {
            "slug": "python-dev-99",
            "company_name": "Zalando",
            "title": "Python Developer",
            "description": "<p>Django services.</p>",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/companies/zalando/python-dev-99",
            "tags": ["python"],
            "job_types": [],
            "location": "",
            "created_at": 1793267000,
        }
    ],
    "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=3"},
    "meta": {"current_page": 2},
}

REMOTEOK_PAYLOAD: list[Any] = [
    {
        "last_updated": 1793224395,
        "legal": "API Terms of Service: Please link back to the URL on Remote OK.",
    },
    {
        "id": "1137573",
        "slug": "remote-backend-engineer-huzzle-1137573",
        "epoch": 1793001612,
        "date": "2026-10-26T08:00:12+00:00",
        "company": "Huzzle",
        "position": "Backend Engineer",
        "tags": ["python", "django"],
        "location": "",
        "salary_min": 60000,
        "salary_max": 90000,
        "url": "https://remoteOK.com/remote-jobs/remote-backend-engineer-huzzle-1137573",
        "apply_url": "https://remoteOK.com/remote-jobs/remote-backend-engineer-huzzle-1137573",
        "description": "<p>Build APIs in <b>Python</b>.</p>",
    },
    {"position": "No URL Role", "company": "Huzzle"},
]

REMOTIVE_PAYLOAD: dict[str, Any] = {
    "0-legal-notice": "Please link back to the URL found on Remotive AND mention Remotive.",
    "job-count": 1,
    "total-job-count": 1,
    "jobs": [
        {
            "id": 2091135,
            "url": "https://remotive.com/remote-jobs/software-development/senior-be-2091135",
            "title": "Senior Back-end Developer",
            "company_name": "Lemon.io",
            "category": "Software Development",
            "job_type": "full_time",
            "publication_date": "2026-10-27T12:56:13",
            "candidate_required_location": "Europe, USA, Canada",
            "salary": "",
            "tags": ["python", "sql"],
            "description": "<p>Backend work in <b>Python</b>.</p>",
        }
    ],
}

HIMALAYAS_PAGE_1: dict[str, Any] = {
    "offset": 0,
    "limit": 20,
    "totalCount": 127889,
    "nextCursor": "MjAyNi0xMC0yOVQwOTozMToyNC43MTI3MzNafDI0ODA1MTk=",
    "jobs": [
        {
            "guid": "https://himalayas.app/companies/acme/jobs/python-engineer",
            "title": "Python Engineer",
            "companyName": "Acme",
            "companySlug": "acme",
            "applicationLink": "https://himalayas.app/companies/acme/jobs/python-engineer",
            "pubDate": 1793266305,
            "employmentType": "Full Time",
            "seniority": ["Entry-level"],
            "locationRestrictions": ["India"],
            "categories": ["Software Engineering"],
            "description": "<p>Write <b>Python</b> services.</p>",
            "excerpt": "Python role",
        },
        {"title": "No Company Role", "applicationLink": "https://himalayas.app/x"},
    ],
}

HIMALAYAS_PAGE_2: dict[str, Any] = {
    "nextCursor": None,
    "jobs": [
        {
            "guid": "https://himalayas.app/companies/beta/jobs/sre",
            "title": "Site Reliability Engineer",
            "companyName": "Beta",
            "applicationLink": "https://himalayas.app/companies/beta/jobs/sre",
            "pubDate": 1793266000,
            "employmentType": "Full Time",
            "seniority": ["Senior"],
            "locationRestrictions": ["United States"],
            "description": "",
            "excerpt": "Kubernetes and Terraform",
        }
    ],
}

JOBICY_PAGE_1: dict[str, Any] = {
    "apiVersion": "2",
    "jobCount": 1,
    "hasMore": True,
    "nextCursor": "AgAAAABq4zJrAAAAAGrjB2g=",
    "friendlyNotice": "Please ensure Jobicy is clearly credited with a direct link.",
    "jobs": [
        {
            "id": 157809,
            "url": "https://jobicy.com/jobs/157809-backend-engineer",
            "jobSlug": "157809-backend-engineer",
            "jobTitle": "Backend Engineer",
            "companyName": "Thumbtack",
            "jobGeo": "USA",
            "jobLevel": "Senior",
            "jobType": ["Full-Time"],
            "jobIndustry": ["Engineering"],
            "pubDate": "2026-10-29T08:45:02+00:00",
            "jobDescription": "<p>Backend in <b>Go</b>.</p>",
            "jobExcerpt": "Backend role",
        },
        {"jobTitle": "No URL Role", "companyName": "Thumbtack"},
    ],
}

JOBICY_PAGE_2: dict[str, Any] = {
    "hasMore": False,
    "nextCursor": None,
    "jobs": [
        {
            "id": 157803,
            "url": "https://jobicy.com/jobs/157803-devops",
            "jobTitle": "DevOps Engineer",
            "companyName": "Thumbtack",
            "jobGeo": "Anywhere",
            "jobLevel": "Mid",
            "jobType": ["Full-Time"],
            "pubDate": "2026-10-28T08:45:02+00:00",
            "jobDescription": "",
            "jobExcerpt": "Terraform and AWS",
        }
    ],
}


class _Response:
    def __init__(self, payload: Any, status_code: int = 200, valid_json: bool = True) -> None:
        self._payload = payload
        self.status_code = status_code
        self._valid_json = valid_json

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if not self._valid_json:
            raise ValueError("not json")
        return self._payload


def _route(monkeypatch: pytest.MonkeyPatch, table: dict[str, Any], calls: list[str]) -> None:
    """Serve a stub response per URL, failing loudly on an unexpected request."""

    def _get(url: str, **kwargs: Any) -> Any:
        calls.append(url)
        for fragment, response in table.items():
            if fragment in url:
                return response
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _get)


def _stub(monkeypatch: pytest.MonkeyPatch, response: Any, calls: list[str] | None = None) -> None:
    def _get(url: str, **kwargs: Any) -> Any:
        if calls is not None:
            calls.append(url)
        return response() if callable(response) else response

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _get)


def _enable_feeds(monkeypatch: pytest.MonkeyPatch, name: str, pages: int = 5) -> None:
    monkeypatch.setenv("JA_FEED_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv(f"JA_{name.upper()}_ENABLED", "true")
    monkeypatch.setenv("JA_FEED_MAX_PAGES", str(pages))
    reset_settings_cache()


# --------------------------------------------------------------------------------------
# Ashby
# --------------------------------------------------------------------------------------


def test_ashby_maps_a_real_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_ASHBY_BOARDS", "ashby")
    reset_settings_cache()
    calls: list[str] = []
    _stub(monkeypatch, _Response(ASHBY_PAYLOAD), calls)

    result = AshbyAdapter(get_settings()).discover()

    assert calls == ["https://api.ashbyhq.com/posting-api/job-board/ashby"]
    assert len(result.records) == 2
    record = result.records[0]
    assert record.source is SourceName.ASHBY
    assert record.title == "Software Engineer, Backend"
    assert record.company == "ashby"
    assert record.location == "Remote - European Union"
    assert record.external_id == "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
    assert record.url == "https://jobs.ashbyhq.com/ashby/7458d4e9"
    assert record.employment_type == "FullTime"
    assert record.work_arrangement == "Remote"
    assert record.retrieval_method == "ashby_posting_api"
    assert record.posted_at is not None
    assert (record.posted_at.year, record.posted_at.month) == (2026, 9)
    assert record.description == "Build backend services in Python."
    assert result.metadata["jobs_per_board"] == {"ashby": 2}
    assert result.metadata["pages_per_board"] == {"ashby": 1}
    reset_settings_cache()


def test_ashby_skips_unlisted_and_urlless_postings(monkeypatch: pytest.MonkeyPatch) -> None:
    """An isListed=false posting is not published by the company, so it is not a job."""
    monkeypatch.setenv("JA_ASHBY_BOARDS", "ashby")
    reset_settings_cache()
    _stub(monkeypatch, _Response(ASHBY_PAYLOAD))

    result = AshbyAdapter(get_settings()).discover()

    titles = [record.title for record in result.records]
    assert "Confidential Role" not in titles
    assert "No URL Role" not in titles
    assert result.invalid_count == 2
    reset_settings_cache()


def test_ashby_intern_maps_to_the_word_normalization_understands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_ASHBY_BOARDS", "ashby")
    reset_settings_cache()
    _stub(monkeypatch, _Response(ASHBY_PAYLOAD))

    intern = AshbyAdapter(get_settings()).discover().records[1]

    assert intern.employment_type == "internship"
    assert intern.location == "New York"
    assert intern.description == "Summer programme in Go."
    reset_settings_cache()


def test_ashby_reports_an_empty_board_without_inventing_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_ASHBY_BOARDS", "deel")
    reset_settings_cache()
    _stub(monkeypatch, _Response({"apiVersion": 1, "jobs": []}))

    result = AshbyAdapter(get_settings()).discover()

    assert result.records == []
    assert result.errors == []
    assert result.metadata["jobs_per_board"] == {"deel": 0}
    reset_settings_cache()


def test_ashby_rejects_an_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_ASHBY_BOARDS", "ashby")
    reset_settings_cache()
    _stub(monkeypatch, _Response({"apiVersion": 1, "jobs": "not-an-array"}))

    with pytest.raises(SourceUnavailable, match="not an array"):
        AshbyAdapter(get_settings()).discover()
    reset_settings_cache()


def test_ashby_needs_a_board_before_it_fetches_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a test attempted a real HTTP request")

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _forbidden)
    reset_settings_cache()
    with pytest.raises(CapabilityNotAvailable, match="JA_ASHBY_BOARDS"):
        AshbyAdapter(get_settings()).discover()


# --------------------------------------------------------------------------------------
# SmartRecruiters
# --------------------------------------------------------------------------------------


def test_smartrecruiters_uses_the_country_name_not_its_iso_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: reading ``location.country`` produced "bangalore, in".

    The ISO-2 code matches no human-entered location preference, so location scoring was
    silently zeroed for every Indian listing. ``fullLocation`` carries the country name.
    """
    monkeypatch.setenv("JA_SMARTRECRUITERS_BOARDS", "BoschGroup")
    monkeypatch.setenv("JA_SMARTRECRUITERS_DETAIL_LIMIT", "0")
    reset_settings_cache()
    _route(
        monkeypatch,
        {
            "offset=0": _Response(SMARTRECRUITERS_PAGE_1),
            "offset=100": _Response(SMARTRECRUITERS_PAGE_2),
        },
        [],
    )

    records = SmartRecruitersAdapter(get_settings()).discover().records

    assert [record.location for record in records] == [
        "bangalore, India",
        "Timișoara, TM, Romania",
    ]
    assert "in" not in [record.location for record in records]
    reset_settings_cache()


def test_smartrecruiters_maps_a_real_payload_and_skips_internal_postings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_SMARTRECRUITERS_BOARDS", "BoschGroup")
    monkeypatch.setenv("JA_SMARTRECRUITERS_DETAIL_LIMIT", "0")
    reset_settings_cache()
    _route(
        monkeypatch,
        {
            "offset=0": _Response(SMARTRECRUITERS_PAGE_1),
            "offset=100": _Response(SMARTRECRUITERS_PAGE_2),
        },
        [],
    )

    result = SmartRecruitersAdapter(get_settings()).discover()

    titles = [record.title for record in result.records]
    assert "Internal Only Role" not in titles
    assert result.invalid_count == 1
    record = result.records[0]
    assert record.source is SourceName.SMARTRECRUITERS
    assert record.company == "Bosch Group"
    assert record.url == "https://jobs.smartrecruiters.com/BoschGroup/744000158499259"
    assert record.employment_type == "Full-time"
    assert record.experience_raw == "Associate"
    assert record.retrieval_method == "smartrecruiters_posting_api"
    assert record.posted_at is not None
    assert record.source_metadata["function"] == "Information Technology"
    assert result.records[1].work_arrangement == "remote"
    reset_settings_cache()


def test_smartrecruiters_follows_offset_pages_and_stops_at_total_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_SMARTRECRUITERS_BOARDS", "BoschGroup")
    monkeypatch.setenv("JA_SMARTRECRUITERS_DETAIL_LIMIT", "0")
    reset_settings_cache()
    calls: list[str] = []
    _route(
        monkeypatch,
        {
            "offset=0": _Response(SMARTRECRUITERS_PAGE_1),
            "offset=100": _Response(SMARTRECRUITERS_PAGE_2),
        },
        calls,
    )

    result = SmartRecruitersAdapter(get_settings()).discover()

    assert len(calls) == 2
    assert "offset=0" in calls[0]
    assert "offset=100" in calls[1]
    assert result.metadata["pages_per_board"] == {"BoschGroup": 2}
    reset_settings_cache()


def test_smartrecruiters_description_fetches_are_bounded_by_the_detail_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_SMARTRECRUITERS_BOARDS", "BoschGroup")
    monkeypatch.setenv("JA_SMARTRECRUITERS_DETAIL_LIMIT", "1")
    reset_settings_cache()
    calls: list[str] = []
    _route(
        monkeypatch,
        {
            "offset=0": _Response(SMARTRECRUITERS_PAGE_1),
            "offset=100": _Response(SMARTRECRUITERS_PAGE_2),
            "postings/744000158499259": _Response(SMARTRECRUITERS_DETAIL),
        },
        calls,
    )

    records = SmartRecruitersAdapter(get_settings()).discover().records

    detail_calls = [url for url in calls if "postings/7440001584" in url]
    assert len(detail_calls) == 1
    assert "Write Python." in records[0].description
    assert "B.Tech required." in records[0].description
    assert records[1].description == ""
    reset_settings_cache()


def test_smartrecruiters_keeps_the_posting_when_its_description_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed detail call must not drop the job; it scores as sparse instead."""
    monkeypatch.setenv("JA_SMARTRECRUITERS_BOARDS", "BoschGroup")
    monkeypatch.setenv("JA_SMARTRECRUITERS_DETAIL_LIMIT", "5")
    monkeypatch.setenv("JA_ATS_MAX_ATTEMPTS", "1")
    reset_settings_cache()
    _route(
        monkeypatch,
        {
            "offset=0": _Response(SMARTRECRUITERS_PAGE_1),
            "offset=100": _Response(SMARTRECRUITERS_PAGE_2),
            "postings/744000158499259": _Response(None, status_code=500),
            "postings/744000158499546": _Response(None, status_code=500),
        },
        [],
    )

    records = SmartRecruitersAdapter(get_settings()).discover().records

    assert len(records) == 2
    assert all(record.description == "" for record in records)
    reset_settings_cache()


# --------------------------------------------------------------------------------------
# Open job feeds
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("adapter_class", "name"),
    [
        (ArbeitnowAdapter, "arbeitnow"),
        (RemoteOkAdapter, "remoteok"),
        (RemotiveAdapter, "remotive"),
        (HimalayasAdapter, "himalayas"),
        (JobicyAdapter, "jobicy"),
    ],
)
def test_every_feed_is_off_until_both_switches_are_on(
    monkeypatch: pytest.MonkeyPatch, adapter_class: Any, name: str
) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a test attempted a real HTTP request")

    monkeypatch.setattr("app.sources.http_fetch.requests.get", _forbidden)
    reset_settings_cache()
    with pytest.raises(CapabilityNotAvailable, match="switched off"):
        adapter_class(get_settings()).discover()

    monkeypatch.setenv(f"JA_{name.upper()}_ENABLED", "true")
    reset_settings_cache()
    with pytest.raises(CapabilityNotAvailable, match="switched off"):
        adapter_class(get_settings()).discover()
    reset_settings_cache()


def test_arbeitnow_maps_a_real_payload_and_follows_the_next_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_feeds(monkeypatch, "arbeitnow", pages=2)
    calls: list[str] = []
    _route(
        monkeypatch,
        {"page=2": _Response(ARBEITNOW_PAGE_2), "job-board-api": _Response(ARBEITNOW_PAGE_1)},
        calls,
    )

    result = ArbeitnowAdapter(get_settings()).discover()

    assert len(calls) == 2
    assert calls[1].endswith("page=2")
    assert result.metadata["pages_read"] == 2
    assert len(result.records) == 2
    assert result.invalid_count == 2
    record = result.records[0]
    assert record.source is SourceName.ARBEITNOW
    assert record.title == "Backend Engineer"
    assert record.company == "Capco"
    assert record.location == "Berlin"
    assert record.work_arrangement == "remote"
    assert record.preferred_skills == ["python", "fastapi"]
    assert record.posted_at is not None and record.posted_at.year == 2026
    assert "Work with Python and FastAPI." in record.description
    reset_settings_cache()


def test_arbeitnow_stops_at_the_page_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The feed is effectively endless, so the budget is what keeps a run from crawling."""
    _enable_feeds(monkeypatch, "arbeitnow", pages=1)
    calls: list[str] = []
    _route(monkeypatch, {"job-board-api": _Response(ARBEITNOW_PAGE_1)}, calls)

    result = ArbeitnowAdapter(get_settings()).discover()

    assert len(calls) == 1
    assert result.metadata["pages_read"] == 1
    assert result.metadata["page_budget"] == 1
    reset_settings_cache()


def test_remoteok_skips_the_legal_header_without_counting_it_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote OK's first array element is a terms object, not a job."""
    _enable_feeds(monkeypatch, "remoteok")
    _stub(monkeypatch, _Response(REMOTEOK_PAYLOAD))

    result = RemoteOkAdapter(get_settings()).discover()

    assert len(result.records) == 1
    assert result.invalid_count == 1
    record = result.records[0]
    assert record.title == "Backend Engineer"
    assert record.company == "Huzzle"
    assert record.external_id == "1137573"
    assert record.work_arrangement == "remote"
    assert record.posted_at is not None
    assert record.source_metadata["salary_max"] == 90000
    reset_settings_cache()


def test_remoteok_is_never_paginated(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_feeds(monkeypatch, "remoteok", pages=10)
    calls: list[str] = []
    _stub(monkeypatch, _Response(REMOTEOK_PAYLOAD), calls)

    RemoteOkAdapter(get_settings()).discover()

    assert calls == ["https://remoteok.com/api"]
    reset_settings_cache()


def test_remotive_makes_exactly_one_request_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remotive's own notice advises about four requests a day, so it never paginates."""
    _enable_feeds(monkeypatch, "remotive", pages=10)
    calls: list[str] = []
    _stub(monkeypatch, _Response(REMOTIVE_PAYLOAD), calls)

    result = RemotiveAdapter(get_settings()).discover()

    assert calls == ["https://remotive.com/api/remote-jobs"]
    assert RemotiveAdapter.max_pages == 1
    record = result.records[0]
    assert record.title == "Senior Back-end Developer"
    assert record.employment_type == "full time"
    assert record.location == "Europe, USA, Canada"
    assert record.posted_at is not None
    reset_settings_cache()


def test_himalayas_walks_cursor_pages_and_url_encodes_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_feeds(monkeypatch, "himalayas", pages=5)
    calls: list[str] = []
    _route(
        monkeypatch,
        {"cursor=": _Response(HIMALAYAS_PAGE_2), "jobs/api?limit": _Response(HIMALAYAS_PAGE_1)},
        calls,
    )

    result = HimalayasAdapter(get_settings()).discover()

    assert len(calls) == 2
    assert "%3D" in calls[1], "the base64 cursor must be percent-encoded"
    assert result.metadata["pages_read"] == 2
    assert len(result.records) == 2
    record = result.records[0]
    assert record.company == "Acme"
    assert record.location == "India"
    assert record.experience_raw == "Entry-level"
    assert record.external_id == "https://himalayas.app/companies/acme/jobs/python-engineer"
    assert record.posted_at is not None
    assert "Kubernetes and Terraform" in result.records[1].description
    reset_settings_cache()


def test_jobicy_stops_when_the_feed_reports_no_more_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_feeds(monkeypatch, "jobicy", pages=10)
    calls: list[str] = []
    _route(
        monkeypatch,
        {"cursor=": _Response(JOBICY_PAGE_2), "remote-jobs?count": _Response(JOBICY_PAGE_1)},
        calls,
    )

    result = JobicyAdapter(get_settings()).discover()

    assert len(calls) == 2, "hasMore=false on page 2 must end the walk"
    assert len(result.records) == 2
    assert result.invalid_count == 1
    record = result.records[0]
    assert record.title == "Backend Engineer"
    assert record.location == "USA"
    assert record.experience_raw == "Senior"
    assert record.employment_type == "Full-Time"
    assert "Terraform and AWS" in result.records[1].description
    reset_settings_cache()


def test_a_feed_with_an_unexpected_shape_is_reported_not_crashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_feeds(monkeypatch, "jobicy")
    _stub(monkeypatch, _Response({"jobs": "not-an-array"}))

    with pytest.raises(SourceUnavailable, match="not an array"):
        JobicyAdapter(get_settings()).discover()
    reset_settings_cache()


def test_a_feed_retries_a_transient_failure_and_then_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_feeds(monkeypatch, "jobicy")
    monkeypatch.setenv("JA_ATS_MAX_ATTEMPTS", "3")
    reset_settings_cache()
    sleeps: list[float] = []
    monkeypatch.setattr("app.sources.http_fetch.time.sleep", lambda delay: sleeps.append(delay))
    calls: list[str] = []
    _stub(monkeypatch, _Response(None, status_code=503), calls)

    with pytest.raises(SourceUnavailable, match="gave up after 3 attempt"):
        JobicyAdapter(get_settings()).discover()

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    reset_settings_cache()


def test_malformed_json_from_a_feed_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_feeds(monkeypatch, "remotive")
    _stub(monkeypatch, _Response(None, valid_json=False))

    with pytest.raises(SourceUnavailable, match="not valid JSON"):
        RemotiveAdapter(get_settings()).discover()
    reset_settings_cache()
