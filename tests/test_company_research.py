"""Company research: every fact has a source, and nothing appears that no source states."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import CandidateProfile, CompanyProfile, utcnow
from app.services import company_research
from app.services.company_research import (
    NOT_STATED,
    ExternalResearchRefused,
    about_sections,
    build_company_profile,
    parse_page_head,
)
from tests.conftest import persist_job

ACME_DESCRIPTION = """About us
Acme is a B2B SaaS platform for logistics teams to track shipments in real time.

Responsibilities
- Build scalable APIs serving millions of requests
- Improve observability and monitoring of our services

Requirements
- Python and FastAPI
- PostgreSQL

Nice to have
- Docker, Kubernetes
"""

PLAIN_DESCRIPTION = """Responsibilities
- Write backend services in Python
Requirements
- Python, SQL
"""


def _acme(session: Session, **overrides: Any):
    values: dict[str, Any] = {
        "description": ACME_DESCRIPTION,
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
    }
    values.update(overrides)
    return persist_job(session, **values)


def _all_text(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if isinstance(data, dict):
        for value in data.values():
            out.extend(_all_text(value))
    elif isinstance(data, list):
        for value in data:
            out.extend(_all_text(value))
    elif isinstance(data, str):
        out.append(data)
    return out


def test_about_section_is_quoted_verbatim() -> None:
    sections = about_sections(ACME_DESCRIPTION)
    assert sections == [
        "Acme is a B2B SaaS platform for logistics teams to track shipments in real time."
    ]
    assert about_sections("About us: We build payment rails for small merchants.\nRole\n- x") == [
        "We build payment rails for small merchants."
    ]
    assert about_sections(PLAIN_DESCRIPTION) == []


def test_every_fact_carries_a_source(session: Session, profile: CandidateProfile) -> None:
    job = _acme(session)
    research = build_company_profile(session, "Acme Technologies Pvt Ltd", job=job, profile=profile)
    data = research.profile.data

    assert research.profile.company_normalized == "acme"
    assert data["listing_count"] == 1
    listing_source = data["listings"][0]["source"]
    assert listing_source["url"] == job.url
    assert listing_source["retrieved_at"]

    for fact in data["about"] + data["business_model"]["facts"] + data["products"]["facts"]:
        assert fact["source"]["url"] == job.url
        assert fact["source"]["retrieved_at"]
    for tech in data["technologies"]:
        assert tech["source_ids"] == [f"job:{job.id}"]
    for theme in data["engineering_focus"]:
        assert theme["evidence"] and all(e["source"]["url"] == job.url for e in theme["evidence"])
    assert research.profile.sources and research.profile.sources[0]["url"] == job.url


def test_nothing_appears_that_is_not_in_a_source(
    session: Session, profile: CandidateProfile
) -> None:
    job = _acme(session)
    data = build_company_profile(session, "Acme", job=job, profile=profile).profile.data
    description = job.description.lower()

    for fact in data["about"] + data["business_model"]["facts"] + data["products"]["facts"]:
        assert fact["quote"].lower() in " ".join(description.split())
    stated_skills = set(job.required_skills) | set(job.preferred_skills)
    for tech in data["technologies"]:
        assert tech["skill"] in stated_skills or tech["skill"] in description
    for theme in data["engineering_focus"]:
        for phrase in theme["phrases"]:
            assert phrase in description
        for evidence in theme["evidence"]:
            assert evidence["quote"].lower() in description

    labels = {fact["statement"] for fact in data["business_model"]["facts"]}
    assert labels == {"B2B", "SaaS"}
    assert data["products"]["stated"]
    assert "platform for logistics teams" in data["products"]["facts"][0]["statement"]


def test_business_model_not_stated_when_absent(session: Session, profile: CandidateProfile) -> None:
    persist_job(session, company="Quiet Corp", description=PLAIN_DESCRIPTION)
    data = build_company_profile(session, "Quiet Corp").profile.data
    assert data["business_model"] == {"stated": False, "facts": [], "message": NOT_STATED}
    assert data["products"]["message"] == NOT_STATED
    assert data["about"] == []
    assert data["website"] is None


def test_requirement_skill_mentioned_as_saas_is_not_business_model(session: Session) -> None:
    persist_job(
        session,
        company="Tools Inc",
        description="Requirements\n- Experience integrating SaaS products and marketplaces\n",
    )
    data = build_company_profile(session, "Tools Inc").profile.data
    assert not data["business_model"]["stated"]


def test_job_context_cites_requirements_and_your_projects(
    session: Session, profile: CandidateProfile
) -> None:
    profile.projects = [
        {
            "name": "Shipment Tracker",
            "description": "Real-time tracking API built with FastAPI and PostgreSQL.",
            "technologies": ["FastAPI"],
        },
        {"name": "Recipe App", "description": "A mobile app in Kotlin.", "technologies": []},
    ]
    job = _acme(session)
    context = build_company_profile(session, "Acme", job=job, profile=profile).job_context
    assert context is not None

    required = [fact["skill"] for fact in context["requirements"]["required_skills"]]
    assert required[:3] == ["python", "fastapi", "postgresql"]
    assert all(f["source"]["url"] == job.url for f in context["requirements"]["required_skills"])

    projects = context["relevant_projects"]
    assert [p["name"] for p in projects] == ["Shipment Tracker"]
    assert set(projects[0]["overlap"]) == {"fastapi", "postgresql"}
    assert projects[0]["source"]["label"] == "your profile"

    topics = context["interview_topics"]
    assert topics and all(topic["derived_from"] for topic in topics)
    assert any("python" in topic["topic"] for topic in topics)


def test_cache_is_reused_and_refreshed(session: Session) -> None:
    _acme(session)
    first = build_company_profile(session, "Acme")
    assert first.from_cache is False
    second = build_company_profile(session, "Acme")
    assert second.from_cache is True
    assert second.profile.id == first.profile.id

    refreshed = build_company_profile(session, "Acme", refresh=True)
    assert refreshed.from_cache is False
    assert session.scalars(select(CompanyProfile)).all() == [refreshed.profile]


def test_new_listing_invalidates_cache(session: Session) -> None:
    _acme(session)
    build_company_profile(session, "Acme")
    newer = _acme(
        session,
        external_id="LI-9",
        title="Data Engineer",
        url="https://jobs.example.com/view/9",
        description="Requirements\n- Kafka and Spark\n",
        required_skills=["Kafka"],
    )
    newer.discovered_at = utcnow() + timedelta(seconds=5)
    session.flush()

    research = build_company_profile(session, "Acme")
    assert research.from_cache is False
    assert research.profile.data["listing_count"] == 2
    assert "kafka" in {tech["skill"] for tech in research.profile.data["technologies"]}


def test_external_fetch_disabled_by_default(session: Session) -> None:
    _acme(session)
    assert get_settings().company_research_external is False
    with pytest.raises(ExternalResearchRefused) as excinfo:
        build_company_profile(
            session, "Acme", fetch_website=True, website="https://acme.example.com"
        )
    assert excinfo.value.code == "external_research_disabled"


def test_external_fetch_requires_a_supplied_website(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acme(session)
    monkeypatch.setattr(get_settings(), "company_research_external", True)

    def _no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no request may be made without a supplied URL")

    monkeypatch.setattr(company_research.requests, "get", _no_network)
    with pytest.raises(ExternalResearchRefused) as excinfo:
        build_company_profile(session, "Acme", fetch_website=True)
    assert excinfo.value.code == "website_unknown"

    with pytest.raises(ExternalResearchRefused) as excinfo:
        build_company_profile(session, "Acme", website="http://127.0.0.1/admin")
    assert excinfo.value.code == "unsafe_url"


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status_code = status
        self.ok = 200 <= status < 400
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._body = body

    def iter_content(self, chunk_size: int = 1024):
        yield self._body

    def close(self) -> None:
        pass


PAGE = (
    b"<html><head><title>Acme | Shipment tracking</title>"
    b'<meta name="description" content="Acme is a marketplace for freight capacity.">'
    b"</head><body>Ignored body text claiming 10,000 employees</body></html>"
)


def test_external_fetch_keeps_only_title_and_meta(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acme(session)
    monkeypatch.setattr(get_settings(), "company_research_external", True)
    calls: list[str] = []

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        if url == "https://acme.example.com":
            return _FakeResponse(301, headers={"Location": "https://www.acme.example.com/"})
        return _FakeResponse(200, PAGE)

    monkeypatch.setattr(company_research.requests, "get", _fake_get)
    research = build_company_profile(
        session, "Acme", fetch_website=True, website="https://acme.example.com"
    )
    site = research.profile.data["website"]
    assert calls == ["https://acme.example.com", "https://www.acme.example.com/"]
    assert site["title"] == "Acme | Shipment tracking"
    assert site["description"] == "Acme is a marketplace for freight capacity."
    assert site["fetched_at"] and site["url"] == "https://acme.example.com"
    assert "10,000" not in " ".join(_all_text(research.profile.data))

    marketplace = [
        f
        for f in research.profile.data["business_model"]["facts"]
        if f["statement"] == "marketplace"
    ]
    assert marketplace and marketplace[0]["source"]["kind"] == "website"
    assert research.profile.website == "https://acme.example.com"

    # The fetch is cached with its date; a later rebuild without fetching keeps it.
    monkeypatch.setattr(company_research.requests, "get", lambda *a, **k: 1 / 0)
    again = build_company_profile(session, "Acme", refresh=True)
    assert again.profile.data["website"]["fetched_at"] == site["fetched_at"]


def test_redirect_to_private_address_is_refused(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acme(session)
    monkeypatch.setattr(get_settings(), "company_research_external", True)
    monkeypatch.setattr(
        company_research.requests,
        "get",
        lambda url, **_: _FakeResponse(302, headers={"Location": "http://169.254.169.254/"}),
    )
    research = build_company_profile(
        session, "Acme", fetch_website=True, website="https://acme.example.com"
    )
    assert "unsafe url" in research.profile.data["website"]["error"]
    assert not research.profile.data["business_model"]["facts"] or all(
        f["source"]["kind"] != "website" for f in research.profile.data["business_model"]["facts"]
    )


def test_parse_page_head() -> None:
    title, description = parse_page_head(
        "<title>  Hello\n World </title><meta property='og:description' content='Hi there'>"
    )
    assert (title, description) == ("Hello World", "Hi there")


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------


def test_company_routes(client: TestClient, session: Session, profile: CandidateProfile) -> None:
    job = _acme(session)
    session.commit()

    body = client.get("/api/research/companies/Acme").json()
    assert body["company"] == "Acme Technologies"
    assert body["data"]["listing_count"] == 1
    assert body["from_cache"] is False
    assert client.get("/api/research/companies/Acme").json()["from_cache"] is True

    refreshed = client.post("/api/research/companies/Acme/refresh", json={})
    assert refreshed.status_code == 200 and refreshed.json()["from_cache"] is False

    with_site = client.post(
        "/api/research/companies/Acme/refresh", json={"website": "https://acme.example.com"}
    ).json()
    assert with_site["website"] == "https://acme.example.com"
    assert with_site["data"]["website"]["fetched_at"] is None

    refused = client.post(
        "/api/research/companies/Acme/refresh",
        json={"fetch_website": True, "website": "https://acme.example.com"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "external_research_disabled"

    job_body = client.get(f"/api/research/jobs/{job.id}/company").json()
    assert job_body["job_context"]["job_id"] == job.id
    assert client.get("/api/research/jobs/99999/company").status_code == 404


def test_external_fetch_refused_in_demo_mode(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acme(session)
    session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "company_research_external", True)
    response = client.post(
        "/api/research/companies/Acme/refresh",
        json={"fetch_website": True, "website": "https://acme.example.com"},
    )
    assert response.status_code == 403
    # Refused either way: without an isolated demo session every research write is
    # refused, and with one the website fetch itself is.
    assert response.json()["error"]["code"] in {
        "demo_mode_external_research_blocked",
        "demo_mode_write_disabled",
    }
