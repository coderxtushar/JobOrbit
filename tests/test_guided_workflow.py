"""The guided application journey.

The milestone these cover is not "a button exists" but "the user is never left guessing
what to do next, and nothing claims a submission that did not happen". The second half is
the compliance guarantee, so it is asserted structurally as well as behaviourally.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ApplicationStatus, CandidateProfile
from app.services.tracking import (
    OPENED_EVENT_DETAIL,
    ApplicationTracker,
    TransitionRequest,
    next_action,
    was_opened,
)
from tests.conftest import persist_job


def _prepare(client, session: Session, external_id: str = "NA-1") -> dict:
    job = persist_job(
        session, external_id=external_id, url=f"https://jobs.example.com/{external_id}"
    )
    session.commit()
    response = client.post("/api/applications/prepare", json={"job_id": job.id})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_prepared_application_tells_the_user_to_answer_what_is_outstanding(
    client, session: Session
) -> None:
    application = _prepare(client, session)

    assert application["status"] == "READY_FOR_REVIEW"
    assert application["blocking_questions"]
    assert "Answer" in application["next_action"]
    assert "never drafted for you" in application["next_action"]


def test_the_next_action_is_present_on_every_listed_application(client, session: Session) -> None:
    _prepare(client, session, "NA-2")

    page = client.get("/api/applications")

    assert page.status_code == 200
    items = page.json()["items"]
    assert items
    for item in items:
        assert item["next_action"], "an application with no stated next action is a dead end"


def test_opening_the_employer_page_is_recorded_without_changing_the_status(
    client, session: Session
) -> None:
    application = _prepare(client, session, "NA-3")
    before = application["status"]

    response = client.post(f"/api/applications/{application['id']}/record-opened")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == before, "opening a page must never advance the state machine"
    assert body["employer_page_opened"] is True
    assert any(event["detail"] == OPENED_EVENT_DETAIL for event in body["events"])


def test_recording_an_opened_page_is_idempotent(client, session: Session) -> None:
    application = _prepare(client, session, "NA-4")

    first = client.post(f"/api/applications/{application['id']}/record-opened").json()
    second = client.post(f"/api/applications/{application['id']}/record-opened").json()

    opened_events = [event for event in second["events"] if event["detail"] == OPENED_EVENT_DETAIL]
    assert len(opened_events) == 1
    assert len(second["events"]) == len(first["events"])


def test_an_opened_page_never_implies_a_submission(client, session: Session) -> None:
    application = _prepare(client, session, "NA-5")

    body = client.post(f"/api/applications/{application['id']}/record-opened").json()

    assert body["submitted_at"] is None
    assert body["submitted_by"] == ""
    assert body["confirmation_evidence"] in (None, "")
    assert body["status"] != "SUBMITTED"


def test_recording_an_opened_page_for_a_missing_application_is_a_404(client) -> None:
    response = client.post("/api/applications/999999/record-opened")

    assert response.status_code == 404


def test_the_next_action_changes_once_the_page_has_been_opened(
    session: Session, profile: CandidateProfile
) -> None:
    from app.llm.null_provider import NullProvider
    from app.services.application_prep import ApplicationPreparationService

    job = persist_job(session, external_id="NA-6")
    service = ApplicationPreparationService(session, NullProvider())
    application = service.prepare(job, profile, include_cover_letter=True).application
    session.flush()

    for answer in application.answers:
        answer.answer = answer.answer or "provided"
    application.user_approved = True
    ApplicationTracker(session).transition(
        application, TransitionRequest(target=ApplicationStatus.APPROVED)
    )

    assert "Open the employer's own page" in next_action(application)
    assert not was_opened(application)

    from app.db.models import ApplicationEvent

    application.events.append(
        ApplicationEvent(
            from_status=application.status,
            to_status=application.status,
            actor="user",
            detail=OPENED_EVENT_DETAIL,
        )
    )
    session.flush()

    assert was_opened(application)
    assert "Record whether you submitted it" in next_action(application)


def test_a_submitted_application_is_told_a_click_is_not_a_confirmation(
    session: Session, profile: CandidateProfile
) -> None:
    from app.db.models import Application

    application = Application(
        job_id=1,
        profile_id=profile.id,
        platform="manual_json",
        status=ApplicationStatus.SUBMITTED,
    )

    assert "not a confirmation" in next_action(application)


def test_a_confirmed_application_asks_for_the_outcome_not_another_submission(
    profile: CandidateProfile,
) -> None:
    from app.db.models import Application

    application = Application(
        job_id=1,
        profile_id=profile.id,
        platform="manual_json",
        status=ApplicationStatus.CONFIRMED,
    )

    action = next_action(application)
    assert "Confirmed" in action
    assert "submit" not in action.lower()


def test_no_application_status_produces_an_empty_next_action(profile: CandidateProfile) -> None:
    from app.db.models import Application

    for status in ApplicationStatus:
        application = Application(
            job_id=1, profile_id=profile.id, platform="manual_json", status=status
        )
        assert next_action(application).strip(), f"{status.value} has no stated next action"


def test_the_record_opened_route_contains_no_submission_capability() -> None:
    """A route that records a browser action must not be able to record a submission."""
    import inspect

    from app.api.routes import applications

    source = inspect.getsource(applications.record_opened)
    assert "SUBMITTED" not in source
    assert "submitted_by" not in source
    assert "TransitionRequest" not in source
