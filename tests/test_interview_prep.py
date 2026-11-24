"""Interview preparation: grounded questions, rule-based practice, user-owned rounds."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Application, CandidateProfile, InterviewRound, Outcome
from app.services.interview_prep import (
    FEEDBACK_DISCLAIMER,
    SECTION_ORDER,
    build_prep,
    create_round,
    delete_round,
    is_interview_stage,
    list_rounds,
    next_practice_question,
    record_practice,
    update_round,
)
from tests.conftest import persist_job

DESCRIPTION = """About us
Acme is a B2B SaaS platform for logistics teams.

Responsibilities
- Design and build REST APIs for shipment tracking
- Improve monitoring of production services

Requirements
- Python, FastAPI and PostgreSQL
- Kubernetes

Nice to have
- Redis
"""


def _application(session: Session, profile: CandidateProfile, **job_overrides: Any) -> Application:
    values: dict[str, Any] = {
        "title": "Backend Engineer",
        "description": DESCRIPTION,
        "required_skills": ["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
        "preferred_skills": ["Redis"],
    }
    values.update(job_overrides)
    job = persist_job(session, **values)
    application = Application(job_id=job.id, profile_id=profile.id, platform="manual")
    session.add(application)
    session.flush()
    return application


def _with_projects(profile: CandidateProfile) -> CandidateProfile:
    profile.projects = [
        {
            "name": "Shipment Tracker",
            "description": "Tracking API built with FastAPI and PostgreSQL.",
            "technologies": ["FastAPI", "PostgreSQL"],
        }
    ]
    profile.education = [{"degree": "B.Tech", "institution": "NIT Trichy"}]
    profile.years_experience = 1.0
    return profile


def _items(prep, section: str) -> list[dict[str, Any]]:
    return prep.content["sections"][section]


def test_prep_has_every_section_and_each_item_says_where_it_came_from(
    session: Session, profile: CandidateProfile
) -> None:
    application = _application(session, _with_projects(profile))
    prep = build_prep(session, application)

    assert list(prep.content["sections"]) == list(SECTION_ORDER)
    assert prep.content["generated_by"] == "rule_based"
    for section in SECTION_ORDER:
        items = _items(prep, section)
        assert items, f"section {section} is empty"
        for item in items:
            assert item["id"] and item["question"] and item["derived_from"]


def test_technical_questions_come_from_listing_skills(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, profile))
    technical = _items(prep, "technical")
    skills = {item.get("skill") for item in technical}
    assert {"python", "fastapi", "postgresql", "kubernetes", "redis"} <= skills
    responsibilities = [
        item["question"] for item in technical if "responsibilities" in item["derived_from"]
    ]
    assert len(responsibilities) == 2
    assert not any("PostgreSQL" in question for question in responsibilities)
    assert all(
        "listing" in item["derived_from"] or "responsibilities" in item["derived_from"]
        for item in technical
    )


def test_project_questions_use_only_stated_project_details(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, _with_projects(profile)))
    projects = _items(prep, "projects")
    assert projects
    for item in projects:
        assert item["project"] == "Shipment Tracker"
        assert "your project 'Shipment Tracker'" in item["derived_from"]
    stated = {"fastapi", "postgresql"}
    for item in projects:
        if item.get("skill"):
            assert item["skill"] in stated


def test_no_projects_means_no_project_questions(
    session: Session, profile: CandidateProfile
) -> None:
    profile.projects = []
    prep = build_prep(session, _application(session, profile))
    assert _items(prep, "projects") == []
    assert any("No projects" in note for note in prep.content["notes"])


def test_resume_questions_come_from_profile_facts(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, _with_projects(profile)))
    resume = _items(prep, "resume")
    derived = " ".join(item["derived_from"] for item in resume)
    assert "your profile's skills" in derived
    assert "education in your profile" in derived
    assert "years of experience" in derived
    # Only skills the profile has can be asked about as "your profile lists".
    for item in resume:
        if item.get("skill"):
            assert item["skill"] in profile.technical_skills


def test_skill_gaps_are_topics_not_claims(session: Session, profile: CandidateProfile) -> None:
    prep = build_prep(session, _application(session, profile))
    gaps = {item["skill"]: item for item in _items(prep, "skill_gaps")}
    assert set(gaps) == {"kubernetes", "redis"}
    for item in gaps.values():
        assert item["question"].startswith("Prepare ")
        assert "does not list it" in item["question"]
    assert gaps["kubernetes"]["level"] == "required"
    # A gap skill is never phrased as something the candidate has done.
    resume_skills = {item.get("skill") for item in _items(prep, "resume")}
    assert not resume_skills & set(gaps)


def test_company_topics_cite_profile_and_flag_unstated(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, profile))
    company = _items(prep, "company")
    text = " ".join(item["question"] for item in company)
    assert "Acme is a B2B SaaS platform for logistics teams." in text
    assert any(
        item["derived_from"] == "stated business model in a cited source" for item in company
    )

    quiet = _application(
        session,
        profile,
        company="Quiet Corp",
        title="Python Developer",
        description="Requirements\n- Python\n",
        required_skills=["Python"],
        preferred_skills=[],
    )
    quiet_prep = build_prep(session, quiet)
    quiet_text = " ".join(item["question"] for item in _items(quiet_prep, "company"))
    assert "not stated in the available sources" in quiet_text


def test_behavioural_and_coding_are_tailored_by_family(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, profile))
    assert prep.content["job"]["family"] == "backend"
    assert any(
        "job family 'backend'" in item["derived_from"] for item in _items(prep, "behavioural")
    )
    assert any("SQL joins" in item["question"] for item in _items(prep, "coding"))


def test_prep_is_stored_and_regenerated_keeping_practice(
    session: Session, profile: CandidateProfile
) -> None:
    application = _application(session, profile)
    prep = build_prep(session, application)
    question = next_practice_question(prep)
    assert question is not None
    record_practice(session, prep, question["id"], "An answer.")

    assert build_prep(session, application).id == prep.id
    regenerated = build_prep(session, application, regenerate=True)
    assert regenerated.id == prep.id
    assert len(regenerated.practice) == 1
    # Stable ids: the practised question is still the same item after regeneration.
    assert any(
        item["id"] == question["id"]
        for section in regenerated.content["sections"].values()
        for item in section
    )


# --------------------------------------------------------------------------------------
# Mock interview
# --------------------------------------------------------------------------------------


def test_next_question_interleaves_and_prefers_unanswered(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, _with_projects(profile)))
    first = next_practice_question(prep)
    assert first is not None and first["kind"] == "technical"
    record_practice(session, prep, first["id"], "answer")
    second = next_practice_question(prep)
    assert second is not None and second["id"] != first["id"]
    assert second["times_practised"] == 0
    behavioural = next_practice_question(prep, kind="behavioural")
    assert behavioural is not None and behavioural["kind"] == "behavioural"
    assert next_practice_question(prep, kind="nonexistent") is None


def test_behavioural_feedback_checks_star(session: Session, profile: CandidateProfile) -> None:
    prep = build_prep(session, _application(session, profile))
    question = next_practice_question(prep, kind="behavioural")
    assert question is not None

    weak = record_practice(session, prep, question["id"], "I am a hard worker.")
    assert weak["disclaimer"] == FEEDBACK_DISCLAIMER
    assert weak["checks"]["word_count"] == 5
    assert any("short" in point for point in weak["points"])
    assert any("STAR structure: no clear signal" in point for point in weak["points"])

    strong_answer = (
        "During my final-year project the situation was that our API kept timing out "
        "under load. My task was to find the cause before the demo, so I had to work "
        "quickly. I added logging, I used a profiler and I found an N+1 query, then I "
        "implemented a join and added an index. As a result, response time was reduced "
        "from 4 seconds to 300 ms, and I learned to measure before optimising. "
    ) * 1
    strong = record_practice(session, prep, question["id"], strong_answer)
    assert all(strong["checks"]["star"].values())
    assert any("all appear" in point for point in strong["points"])
    assert len(prep.practice) == 2
    assert prep.practice[-1]["answer"] == strong_answer


def test_technical_feedback_checks_skill_mentions(
    session: Session, profile: CandidateProfile
) -> None:
    prep = build_prep(session, _application(session, profile))
    question = next(item for item in _items(prep, "technical") if item.get("skill") == "python")
    missing = record_practice(session, prep, question["id"], "Lists use more memory than tuples.")
    assert any("never names it" in point for point in missing["points"])
    good = record_practice(
        session,
        prep,
        question,
        "In Python, for example, a generator yields lazily so it uses less memory; in my "
        "project I used one with FastAPI to stream rows from PostgreSQL.",
    )
    assert {"python", "fastapi", "postgresql"} <= set(good["checks"]["skills_mentioned"])
    assert good["checks"]["has_example"] is True


def test_record_practice_unknown_question(session: Session, profile: CandidateProfile) -> None:
    prep = build_prep(session, _application(session, profile))
    with pytest.raises(KeyError):
        record_practice(session, prep, "technical-doesnotexist", "x")


# --------------------------------------------------------------------------------------
# Rounds and stage
# --------------------------------------------------------------------------------------


def test_round_crud_and_interview_stage(session: Session, profile: CandidateProfile) -> None:
    application = _application(session, profile)
    assert is_interview_stage(application) is False

    when = datetime(2026, 12, 1, 10, 30, tzinfo=UTC)
    record = create_round(
        session,
        application,
        {"round_name": "Technical 1", "scheduled_at": when, "questions_asked": ["  ", "SQL joins"]},
    )
    assert record.questions_asked == ["SQL joins"]
    assert record.feedback == "" and record.next_steps == ""  # nothing generated
    assert is_interview_stage(application) is True

    update_round(session, record, {"feedback": "Went well, they said.", "bogus": "ignored"})
    assert record.feedback == "Went well, they said."
    assert [r.id for r in list_rounds(session, application.id)] == [record.id]

    with pytest.raises(ValueError):
        update_round(session, record, {"scheduled_at": datetime(2026, 12, 1)})

    delete_round(session, record)
    assert list_rounds(session, application.id) == []
    assert is_interview_stage(application) is False

    application.outcome = Outcome.SCREENING
    assert is_interview_stage(application) is True
    application.outcome = Outcome.INTERVIEWING
    assert is_interview_stage(application) is True
    application.outcome = Outcome.REJECTED
    assert is_interview_stage(application) is False


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------


def test_interview_prep_routes(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    application = _application(session, profile)
    session.commit()
    base = f"/api/research/applications/{application.id}"

    missing = client.get(f"{base}/interview-prep")
    assert missing.status_code == 404
    assert client.get(f"{base}/interview-prep/next-question").json() == {"question": None}
    early = client.post(f"{base}/interview-prep/practice", json={"question_id": "x", "answer": ""})
    assert early.status_code == 409

    created = client.post(f"{base}/interview-prep", json={})
    assert created.status_code == 200
    body = created.json()
    assert body["application_id"] == application.id
    assert body["interview_stage"] is False
    question = body["next_question"]
    assert question["kind"] == "technical"

    assert client.get(f"{base}/interview-prep").json()["id"] == body["id"]
    regenerated = client.post(f"{base}/interview-prep", json={"regenerate": True})
    assert regenerated.status_code == 200

    practice = client.post(
        f"{base}/interview-prep/practice",
        json={"question_id": question["id"], "answer": "I used Python for example."},
    )
    assert practice.status_code == 200
    result = practice.json()
    assert result["feedback"]["disclaimer"] == FEEDBACK_DISCLAIMER
    assert result["practice_count"] == 1
    assert result["next_question"]["id"] != question["id"]

    unknown = client.post(
        f"{base}/interview-prep/practice", json={"question_id": "nope", "answer": "x"}
    )
    assert unknown.status_code == 404

    nxt = client.get(f"{base}/interview-prep/next-question", params={"kind": "behavioural"})
    assert nxt.json()["question"]["kind"] == "behavioural"

    assert client.get("/api/research/applications/99999/interview-prep").status_code == 404


def test_round_routes(client: TestClient, session: Session, profile: CandidateProfile) -> None:
    application = _application(session, profile)
    session.commit()
    base = f"/api/research/applications/{application.id}/rounds"

    assert client.get(base).json() == []
    naive = client.post(base, json={"round_name": "HR", "scheduled_at": "2026-12-01T10:00:00"})
    assert naive.status_code == 422

    created = client.post(
        base,
        json={
            "round_name": "HR",
            "scheduled_at": "2026-12-01T10:00:00+05:30",
            "questions_asked": ["Why us?"],
        },
    )
    assert created.status_code == 201
    round_id = created.json()["id"]
    assert created.json()["feedback"] == ""

    patched = client.patch(f"/api/research/rounds/{round_id}", json={"next_steps": "Wait a week"})
    assert patched.status_code == 200
    assert patched.json()["next_steps"] == "Wait a week"
    assert patched.json()["round_name"] == "HR"

    prep = client.post(f"/api/research/applications/{application.id}/interview-prep").json()
    assert prep["interview_stage"] is True

    assert client.delete(f"/api/research/rounds/{round_id}").status_code == 204
    assert client.delete(f"/api/research/rounds/{round_id}").status_code == 404
    assert client.patch("/api/research/rounds/99999", json={}).status_code == 404
    assert session.query(InterviewRound).count() == 0


# --------------------------------------------------------------------------------------
# UI smoke test: the research page renders against the real API
# --------------------------------------------------------------------------------------


def test_research_page_renders_all_tabs(
    client: TestClient,
    session: Session,
    profile: CandidateProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ui.api_client import ApiClient, ApiClientError
    from ui.views import research_page

    application = _application(session, _with_projects(profile), salary_raw="12-18 LPA")
    session.commit()
    client.post(f"/api/research/applications/{application.id}/interview-prep")

    class _Proxy(ApiClient):
        def _request(self, method: str, path: str, **kwargs: Any) -> Any:
            response = client.request(method, path, **kwargs)
            if response.status_code >= 400:
                error = response.json().get("error", {})
                raise ApiClientError(error.get("message", ""), code=error.get("code", ""))
            return response.json() if response.content else None

    monkeypatch.setattr(research_page, "get_client", lambda: _Proxy(base_url="http://test"))
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_string(
        f"import sys\nsys.path.insert(0, {str(root)!r})\n"
        "from ui.views import research_page\nresearch_page.render()\n"
    )
    app.run(timeout=30)
    assert not app.exception
    text = " ".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.info, app.subheader)
        for element in collection
    )
    assert "Acme is a B2B SaaS platform for logistics teams." in text
    assert "Shipment Tracker" in text
    assert "Your own records" in text
    assert "LPA = lakh per annum" in text

    answer_box = next(box for box in app.text_area if box.label == "Your answer")
    answer_box.input("I used Python, for example in my project.")
    next(button for button in app.button if button.label == "Submit answer").click()
    app.run(timeout=30)
    assert not app.exception
    feedback = " ".join(str(element.value) for element in app.caption)
    assert "rule-based feedback" in feedback
    prep = client.get(f"/api/research/applications/{application.id}/interview-prep").json()
    assert len(prep["practice"]) == 1
