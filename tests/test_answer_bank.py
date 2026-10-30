"""Answer bank, action inbox and application-artifact tests.

The behaviour under test is the one that makes a bulk run tractable without making it
dishonest: an answer given once is reused everywhere, an answer nobody gave is never
invented, and an application already sent to an employer is never rewritten.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    ApplicationArtifact,
    ApplicationStatus,
    CandidateProfile,
    SavedAnswer,
)
from app.db.repositories import (
    ProfileRepository,
    SavedAnswerRepository,
    UnbankableAnswerError,
)
from app.services.answer_bank import AnswerBankService
from app.services.application_prep import ApplicationPreparationService
from tests.conftest import make_record, persist_job


def _prepare(session: Session, profile: CandidateProfile, **job_overrides):
    job = persist_job(session, **job_overrides)
    return ApplicationPreparationService(session).prepare(job, profile)


def test_an_ai_draft_can_never_enter_the_answer_bank(
    session: Session, profile: CandidateProfile
) -> None:
    bank = SavedAnswerRepository(session)
    with pytest.raises(UnbankableAnswerError, match="ai_draft"):
        bank.upsert(
            profile_id=profile.id,
            question_key="why_this_role",
            question="Why do you want this role?",
            answer="Because I am passionate about synergy.",
            provenance=AnswerProvenance.AI_DRAFT,
        )
    assert bank.list(profile.id) == []


def test_needs_user_input_can_never_enter_the_answer_bank(
    session: Session, profile: CandidateProfile
) -> None:
    with pytest.raises(UnbankableAnswerError):
        SavedAnswerRepository(session).upsert(
            profile_id=profile.id,
            question_key="work_authorization",
            question="Are you authorised to work?",
            answer="",
            provenance=AnswerProvenance.NEEDS_USER_INPUT,
        )


def test_the_database_rejects_an_unverified_provenance_directly(
    session: Session, profile: CandidateProfile
) -> None:
    """The guarantee is a CHECK constraint, not only a Python branch."""
    from sqlalchemy.exc import IntegrityError

    session.add(
        SavedAnswer(
            profile_id=profile.id,
            question_key="smuggled",
            answer="x",
            provenance=AnswerProvenance.AI_DRAFT,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_one_answer_backfills_every_open_application(
    session: Session, profile: CandidateProfile
) -> None:
    for index in range(4):
        _prepare(
            session,
            profile,
            record=make_record(
                external_id=f"LI-{index}",
                company=f"Acme {index} Technologies",
                url=f"https://jobs.example.com/{index}",
            ),
        )
    session.commit()

    service = AnswerBankService(session)
    inbox = service.inbox(profile)
    notice = next(entry for entry in inbox if entry.question_key == "notice_period")
    assert notice.occurrences == 4
    assert notice.is_sensitive is True

    result = service.resolve_from_inbox(
        profile, question_key="notice_period", answer="30 days", question=notice.question
    )
    session.commit()

    assert result.applications_updated == 4
    remaining = {entry.question_key for entry in service.inbox(profile)}
    assert "notice_period" not in remaining

    rows = SavedAnswerRepository(session).open_answers_for_key(profile.id, "notice_period")
    assert len(rows) == 4
    for row in rows:
        assert row.answer == "30 days"
        assert row.provenance is AnswerProvenance.USER_ENTERED
        assert row.requires_user_input is False
        assert row.source_field == "answer_bank:notice_period"


def test_a_submitted_application_is_never_backfilled(
    session: Session, profile: CandidateProfile
) -> None:
    from app.services.tracking import ApplicationTracker, TransitionRequest

    open_app = _prepare(
        session,
        profile,
        record=make_record(external_id="OPEN-1", company="Open Systems"),
    ).application
    sent = _prepare(
        session,
        profile,
        record=make_record(
            external_id="SENT-1",
            company="Sent Systems",
            url="https://jobs.example.com/sent",
        ),
    ).application

    tracker = ApplicationTracker(session)
    for answer in sent.answers:
        answer.answer = answer.answer or "provided by hand"
        answer.provenance = AnswerProvenance.USER_ENTERED
        answer.requires_user_input = False
    session.flush()
    tracker.transition(sent, TransitionRequest(ApplicationStatus.READY_FOR_REVIEW))
    sent.user_approved = True
    session.flush()
    tracker.transition(sent, TransitionRequest(ApplicationStatus.APPROVED, detail="approved"))
    tracker.transition(
        sent,
        TransitionRequest(
            ApplicationStatus.SUBMITTED,
            actor="user",
            submitted_by="user",
            detail="submitted by hand",
        ),
    )
    session.commit()
    before = {answer.question_key: answer.answer for answer in sent.answers}

    result = AnswerBankService(session).resolve_from_inbox(
        profile, question_key="notice_period", answer="15 days"
    )
    session.commit()

    assert result.applications_updated == 1
    session.refresh(sent)
    assert {answer.question_key: answer.answer for answer in sent.answers} == before
    updated = next(a for a in open_app.answers if a.question_key == "notice_period")
    assert updated.answer == "15 days"


def test_preparation_reuses_a_banked_answer_without_being_asked(
    session: Session, profile: CandidateProfile
) -> None:
    AnswerBankService(session).save(
        profile, question_key="notice_period", answer="Immediately available"
    )
    session.commit()

    prepared = _prepare(session, profile)
    session.commit()

    assert prepared.reused_answers >= 1
    answer = next(a for a in prepared.application.answers if a.question_key == "notice_period")
    assert answer.answer == "Immediately available"
    assert answer.requires_user_input is False
    assert "notice_period" not in [q.lower() for q in prepared.blocking_questions]

    banked = SavedAnswerRepository(session).get(profile.id, "notice_period")
    assert banked is not None
    assert banked.times_used >= 1
    assert banked.last_used_at is not None


def test_an_unbanked_question_is_still_flagged_not_guessed(
    session: Session, profile: CandidateProfile
) -> None:
    prepared = _prepare(session, profile)
    session.commit()
    authorization = next(
        a for a in prepared.application.answers if a.question_key == "work_authorization"
    )
    assert authorization.answer == ""
    assert authorization.requires_user_input is True
    assert authorization.provenance is AnswerProvenance.NEEDS_USER_INPUT


def test_a_blank_answer_is_refused(session: Session, profile: CandidateProfile) -> None:
    with pytest.raises(ValueError, match="cannot be blank"):
        AnswerBankService(session).resolve_from_inbox(
            profile, question_key="notice_period", answer="   "
        )


def test_artifacts_snapshot_the_exact_material_and_deduplicate_by_hash(
    session: Session, profile: CandidateProfile
) -> None:
    from app.db.models import Resume

    session.add(
        Resume(
            profile_id=profile.id,
            label="Primary",
            original_filename="cv.pdf",
            stored_path="cv.pdf",
            content_type="application/pdf",
            file_size_bytes=10,
            sha256="deadbeef",
            extracted_text="Priya Nair\nPython, FastAPI, AWS",
            is_primary=True,
        )
    )
    session.flush()

    prepared = _prepare(session, profile)
    session.commit()
    artifacts = (
        session.query(ApplicationArtifact)
        .filter(ApplicationArtifact.application_id == prepared.application.id)
        .all()
    )
    kinds = {artifact.kind for artifact in artifacts}
    assert "cover_letter" in kinds
    letter = next(a for a in artifacts if a.kind == "cover_letter")
    assert letter.content == prepared.application.cover_letter
    assert len(letter.content_sha256) == 64
    assert letter.byte_size == len(letter.content.encode("utf-8"))

    job = session.get(type(prepared.application.job), prepared.application.job_id)
    assert job is not None
    ApplicationPreparationService(session).prepare(job, profile, include_cover_letter=False)
    session.commit()
    again = (
        session.query(ApplicationArtifact)
        .filter(
            ApplicationArtifact.application_id == prepared.application.id,
            ApplicationArtifact.kind == "cover_letter",
        )
        .count()
    )
    assert again == 1


def test_answer_bank_endpoints_round_trip(client: TestClient, engine) -> None:
    from app.db.base import session_scope

    with session_scope() as session:
        created = ProfileRepository(session).get_or_create_default()
        ProfileRepository(session).update(created, {"full_name": "Test Candidate"})
        prepared_profile_id = created.id
        job = persist_job(session)
        job_id = job.id
    assert prepared_profile_id

    prepared = client.post("/api/applications/prepare", json={"job_id": job_id})
    assert prepared.status_code == 201, prepared.text

    inbox = client.get("/api/answers/inbox")
    assert inbox.status_code == 200
    keys = {entry["question_key"]: entry for entry in inbox.json()}
    assert "work_authorization" in keys
    assert keys["work_authorization"]["is_sensitive"] is True
    assert keys["work_authorization"]["has_saved_answer"] is False

    saved = client.put(
        "/api/answers/work_authorization",
        json={"answer": "Yes - Indian citizen, no sponsorship needed"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["applications_updated"] == 1
    assert body["answer"]["provenance"] == "user_entered"
    assert body["answer"]["is_sensitive"] is True

    listed = client.get("/api/answers").json()
    assert [entry["question_key"] for entry in listed] == ["work_authorization"]

    after = {entry["question_key"] for entry in client.get("/api/answers/inbox").json()}
    assert "work_authorization" not in after

    assert client.delete("/api/answers/work_authorization").status_code == 204
    assert client.delete("/api/answers/work_authorization").status_code == 404


def test_a_blank_answer_is_rejected_by_the_api(client: TestClient, engine) -> None:
    response = client.put("/api/answers/notice_period", json={"answer": ""})
    assert response.status_code == 422
