"""Application artifacts: versioned while drafted, immutable once sent."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ApplicationArtifact, ApplicationStatus, SourceName
from tests.conftest import persist_job


def _prepared(client, session: Session) -> int:
    job = persist_job(
        session, source=SourceName.GREENHOUSE, external_id="ART-1", title="Backend Developer"
    )
    session.commit()
    response = client.post("/api/applications/prepare", json={"job_id": job.id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_preparation_snapshots_the_profile_it_was_based_on(client, session: Session) -> None:
    application_id = _prepared(client, session)
    kinds = {
        row["kind"] for row in client.get(f"/api/applications/{application_id}/artifacts").json()
    }
    assert "profile_snapshot" in kinds


def test_regenerating_keeps_the_earlier_versions(client, session: Session, profile) -> None:
    application_id = _prepared(client, session)
    before = client.get(f"/api/applications/{application_id}/artifacts").json()
    profile.technical_skills = [*profile.technical_skills, "kubernetes"]
    session.commit()

    response = client.post(f"/api/applications/{application_id}/regenerate")
    assert response.status_code == 200, response.text
    after = client.get(f"/api/applications/{application_id}/artifacts").json()
    assert {row["id"] for row in before} <= {row["id"] for row in after}
    assert len(after) > len(before), "the changed profile should produce a new snapshot"


def test_an_application_that_may_have_been_sent_cannot_be_regenerated(
    client, session: Session
) -> None:
    from app.db.models import Application

    application_id = _prepared(client, session)
    row = session.get(Application, application_id)
    row.status = ApplicationStatus.SUBMISSION_UNKNOWN
    session.commit()
    response = client.post(f"/api/applications/{application_id}/regenerate")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_submitted"


def test_locked_versions_are_reported_as_locked(client, session: Session) -> None:
    from app.db.models import utcnow

    application_id = _prepared(client, session)
    artifact = session.query(ApplicationArtifact).filter_by(application_id=application_id).first()
    artifact.locked_at = utcnow()
    session.commit()
    rows = client.get(f"/api/applications/{application_id}/artifacts").json()
    assert any(row["locked"] for row in rows)
