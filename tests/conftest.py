"""Shared test fixtures.

Every test runs against a fresh in-memory SQLite database and a temporary data directory,
with no LLM provider and no network access. That is deliberate: the default suite must
prove the application works with no API key and no platform credentials.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, reset_settings_cache
from app.db import base as db_base
from app.db.models import Base, CandidateProfile, Job, SourceName, WorkArrangement
from app.db.repositories import ProfileRepository
from app.schemas.job import RawJobRecord
from app.services.dedup import fingerprint_for_values
from app.services.normalization import normalize_record


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("JA_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("JA_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JA_LLM_PROVIDER", "none")
    monkeypatch.setenv("JA_LLM_API_KEY", "")
    monkeypatch.setenv("JA_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "false")
    monkeypatch.setenv("JA_API_HOST", "127.0.0.1")
    monkeypatch.setenv("JA_API_TOKEN", "")
    reset_settings_cache()
    from app.config import get_settings

    settings = get_settings()
    settings.ensure_directories()
    yield settings
    reset_settings_cache()


@pytest.fixture
def engine(_isolated_settings: Settings):
    """A single shared in-memory engine, configured as the app-wide engine.

    ``StaticPool`` is required, not a preference: every new connection to ``:memory:``
    creates its own private database, and TestClient runs the application on a different
    thread. Without a single shared connection the API would see an empty schema.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    db_base.configure(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    factory = db_base.get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def profile(session: Session) -> CandidateProfile:
    """A fresher profile matching the documented default job-seeker preferences."""
    repository = ProfileRepository(session)
    created = repository.get_or_create_default()
    repository.update(
        created,
        {
            "full_name": "Test Candidate",
            "email": "test@example.com",
            "experience_level": "fresher",
            "years_experience": 0.0,
            "target_titles": [
                "Software Engineer",
                "Backend Developer",
                "Python Developer",
                "Generative AI Engineer",
            ],
            "technical_skills": [
                "python",
                "fastapi",
                "postgresql",
                "docker",
                "aws",
                "langchain",
                "llm",
                "sql",
            ],
            "preferred_locations": ["Bengaluru", "Remote"],
            "work_arrangements": ["remote", "hybrid"],
            "employment_types": ["full_time", "internship"],
            "max_job_age_days": 30,
            "minimum_match_score": 65.0,
        },
    )
    session.commit()
    return created


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


# --------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------


def make_record(**overrides) -> RawJobRecord:
    payload: dict = {
        "source": SourceName.LINKEDIN,
        "external_id": "LI-1",
        "title": "Backend Developer",
        "company": "Acme Technologies",
        "location": "Bengaluru, India",
        "url": "https://jobs.example.com/view/1",
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "experience_raw": "0-2 years",
        "description": "Build REST APIs with Python and FastAPI on PostgreSQL in Bengaluru.",
    }
    payload.update(overrides)
    return RawJobRecord(**payload)


def persist_job(session: Session, record: RawJobRecord | None = None, **overrides) -> Job:
    """Normalize and store one job directly, bypassing the ingest pipeline."""
    record = record or make_record(**overrides)
    normalized = normalize_record(record)
    values = normalized.values
    values["fingerprint"] = fingerprint_for_values(values)
    job = Job(**values)
    session.add(job)
    session.flush()
    return job


def make_docx(lines: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pdf(lines: list[str]) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "\n".join(lines), fontsize=10)
    data = document.tobytes()
    document.close()
    return data


SAMPLE_RESUME_LINES = [
    "Priya Nair",
    "priya.nair@example.com | +91 98765 43210 | github.com/priyanair",
    "TECHNICAL SKILLS",
    "Languages: Python, JavaScript, SQL",
    "Frameworks: FastAPI, React",
    "Cloud: AWS, Docker, PostgreSQL",
    "EDUCATION",
    "B.Tech in Computer Science, National Institute of Technology, 2022 - 2026, CGPA 8.9",
    "PROJECTS",
    "- Job Matcher: FastAPI service that ranks jobs using PostgreSQL and embeddings.",
    "CERTIFICATIONS",
    "- AWS Certified Cloud Practitioner",
    "ACHIEVEMENTS",
    "- First place, college hackathon 2025",
]


def utc_days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


REMOTE = WorkArrangement.REMOTE
