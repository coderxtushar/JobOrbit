"""Durability and on-disk protection of the local data store.

These cover two things the unit suite otherwise misses: that application state survives a
full process restart (the database is the only store, so nothing may live in memory), and
that the SQLite file itself is not world-readable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import Settings
from app.db import base as db_base
from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationAnswer,
    ApplicationStatus,
    Base,
    Outcome,
)
from app.db.repositories import ApplicationRepository, ProfileRepository
from app.services.tracking import ApplicationTracker, TransitionRequest
from tests.conftest import make_record, persist_job


def _settings_for(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'persist.db'}",
        data_dir=tmp_path,
    )


def test_application_state_survives_a_full_restart(tmp_path: Path) -> None:
    """Write through one engine, dispose it, then read through a brand-new engine."""
    settings = _settings_for(tmp_path)

    first_engine = db_base.build_engine(settings)
    Base.metadata.create_all(first_engine)
    db_base.configure(first_engine)

    with db_base.session_scope() as session:
        profile = ProfileRepository(session).get_or_create_default()
        job = persist_job(session, make_record(external_id="PERSIST-1"))
        application = ApplicationRepository(session).create(
            Application(
                job_id=job.id,
                profile_id=profile.id,
                platform="linkedin",
                status=ApplicationStatus.READY_FOR_REVIEW,
                user_approved=True,
            )
        )
        session.add(
            ApplicationAnswer(
                application_id=application.id,
                question="What is your notice period?",
                question_key="notice_period",
                answer="Immediately available",
                provenance=AnswerProvenance.PROFILE_VERIFIED,
                is_sensitive=True,
            )
        )
        session.flush()
        tracker = ApplicationTracker(session)
        tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))
        tracker.transition(
            application,
            TransitionRequest(ApplicationStatus.SUBMITTED, submitted_by="Priya Nair"),
        )
        tracker.transition(
            application,
            TransitionRequest(
                ApplicationStatus.CONFIRMED, confirmation_evidence="Email ref ACME-99"
            ),
        )
        application.outcome = Outcome.INTERVIEWING
        application.notes = "Recruiter call booked"
        application_id = application.id

    first_engine.dispose()

    # A genuinely separate engine over the same file, as a restarted process would create.
    second_engine = db_base.build_engine(settings)
    db_base.configure(second_engine)
    try:
        with db_base.session_scope() as session:
            reloaded = ApplicationRepository(session).get(application_id)
            assert reloaded is not None
            assert reloaded.status is ApplicationStatus.CONFIRMED
            assert reloaded.submitted_by == "Priya Nair"
            assert reloaded.confirmation_evidence == "Email ref ACME-99"
            assert reloaded.outcome is Outcome.INTERVIEWING
            assert reloaded.notes == "Recruiter call booked"
            assert len(reloaded.events) == 3
            assert len(reloaded.answers) == 1
            assert reloaded.answers[0].provenance is AnswerProvenance.PROFILE_VERIFIED
    finally:
        second_engine.dispose()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes do not apply on Windows")
def test_the_sqlite_file_is_not_world_readable(tmp_path: Path) -> None:
    """Regression: the database was created 0644, exposing resumes and answers.

    The parent directory is 0700, but relying on that alone means a later move or copy of
    the data directory silently drops the only protection.
    """
    settings = _settings_for(tmp_path)
    engine = db_base.build_engine(settings)
    try:
        Base.metadata.create_all(engine)
        with engine.connect():
            pass
        database = Path(tmp_path / "persist.db")
        assert database.exists()
        assert database.stat().st_mode & 0o777 == 0o600
    finally:
        engine.dispose()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes do not apply on Windows")
def test_the_private_data_directories_are_owner_only(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.ensure_directories()
    for directory in (
        settings.data_dir,
        settings.resume_dir,
        settings.artifact_dir,
        settings.import_dir,
    ):
        assert directory.stat().st_mode & 0o777 == 0o700, directory


def test_foreign_keys_are_enforced_on_sqlite(tmp_path: Path) -> None:
    """SQLite ignores foreign keys unless the pragma is set per connection."""
    from sqlalchemy.exc import IntegrityError

    settings = _settings_for(tmp_path)
    engine = db_base.build_engine(settings)
    try:
        Base.metadata.create_all(engine)
        db_base.configure(engine)
        with pytest.raises(IntegrityError), db_base.session_scope() as session:
            session.add(
                ApplicationAnswer(
                    application_id=999999,
                    question="orphan",
                    question_key="orphan",
                )
            )
    finally:
        engine.dispose()


def test_an_in_memory_url_does_not_attempt_a_chmod() -> None:
    """The permission hook must not fire for :memory:, which has no file."""
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    engine = db_base.build_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection is not None
    finally:
        engine.dispose()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes do not apply on Windows")
def test_the_migration_path_also_restricts_the_database_file(tmp_path: Path) -> None:
    """`alembic upgrade head` must not leave a world-readable database.

    Regression: Alembic builds its own engine and bypasses build_engine's permission hook.
    Because the documented first run migrates *before* starting the API, the database sat
    at 0644 until the app first connected, and stayed there in a migrate-only deployment.
    """
    import subprocess
    import sys

    database = tmp_path / "migrated.db"
    environment = {
        **os.environ,
        "JA_DATABASE_URL": f"sqlite+pysqlite:///{database}",
        "JA_DATA_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode == 0, result.stderr
    assert database.exists()
    assert database.stat().st_mode & 0o777 == 0o600
