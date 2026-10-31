"""Seed data for a public demo deployment.

A shared deployment has no per-user login, so it must never hold a real person's resume.
:func:`seed_demo_data` installs an obviously fictional candidate and a small set of sample
listings, which lets a visitor exercise scoring, filtering, bulk preparation and the review
queue without anyone uploading anything.

The candidate's name, email and phone are deliberately unmistakable placeholders rather
than plausible values, so nobody mistakes the demo profile for a real applicant.

Seeding is idempotent: it is called on every boot of the embedded API, and Streamlit
restarts that process whenever the container wakes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import SourceName, utcnow
from app.db.repositories import ProfileRepository
from app.logging_conf import get_logger
from app.schemas.job import RawJobRecord
from app.services.ingest import JobIngestService
from app.services.scoring import ScoringService

logger = get_logger(__name__)

DEMO_FULL_NAME = "Demo Candidate (sample data)"
DEMO_EMAIL = "demo.candidate@example.invalid"

DEMO_PROFILE: dict[str, Any] = {
    "full_name": DEMO_FULL_NAME,
    "email": DEMO_EMAIL,
    "phone": "+91 00000 00000",
    "headline": "Fresher software engineer — sample profile for the public demo",
    "experience_level": "fresher",
    "years_experience": 0.5,
    "graduation_date": "2026-06",
    "target_titles": [
        "Software Engineer",
        "Backend Developer",
        "Python Developer",
        "Frontend Developer",
        "AI Engineer",
        "Cloud Engineer",
        "DevOps Engineer",
    ],
    "technical_skills": [
        "python",
        "javascript",
        "typescript",
        "fastapi",
        "react",
        "node.js",
        "postgresql",
        "mongodb",
        "redis",
        "docker",
        "kubernetes",
        "aws",
        "git",
        "linux",
        "sql",
        "langchain",
    ],
    "soft_skills": ["communication", "teamwork"],
    "education": [
        {
            "degree": "B.Tech Computer Science",
            "institution": "Example Institute of Technology",
            "year": "2026",
        }
    ],
    "projects": [
        {
            "name": "Sample Retrieval Service",
            "description": "A FastAPI service with PostgreSQL and Redis caching, "
            "containerised with Docker and deployed through GitHub Actions",
        }
    ],
    "links": ["https://example.invalid/demo-candidate"],
    "preferred_locations": ["Remote", "Bengaluru", "Delhi NCR", "Noida"],
    "work_arrangements": ["remote", "hybrid", "onsite"],
    "employment_types": ["full_time", "internship"],
    # Filled in so a visitor can reach the review queue. On a real local profile these
    # stay blank until the user confirms them, which is what makes an application block.
    "work_authorization": "Authorised to work in India (sample answer)",
    "requires_sponsorship": False,
    "notice_period_days": 0,
    "salary_expectation_min": 600000,
    "salary_expectation_max": 1200000,
    "salary_currency": "INR",
    "open_to_relocation": True,
    "max_job_age_days": 45,
    "minimum_match_score": 65.0,
}


def _demo_jobs() -> list[RawJobRecord]:
    """Sample listings chosen so the feed shows every band and every honesty case."""
    now = utcnow()
    return [
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-1",
            title="Backend Developer (Python)",
            company="Northwind Systems",
            location="Bengaluru, Karnataka, India",
            url="https://example.invalid/demo/backend-developer",
            work_arrangement="hybrid",
            employment_type="full_time",
            experience_raw="0-2 years",
            required_skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
            preferred_skills=["Redis"],
            description=(
                "About the role\n"
                "We are hiring a backend developer to build and operate our public APIs.\n"
                "Requirements\n"
                "- Strong Python\n- FastAPI or a similar framework\n- PostgreSQL\n"
                "Nice to have\n- Redis\n- Exposure to Docker\n\n"
                "Freshers welcome. Tell us why you want to join us."
            ),
            posted_at=now - timedelta(days=2),
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-2",
            title="Frontend Developer - React",
            company="Palewind Labs",
            location="Remote",
            url="https://example.invalid/demo/frontend-developer",
            work_arrangement="remote",
            employment_type="full_time",
            experience_raw="0-1 years",
            required_skills=["React", "TypeScript", "CSS"],
            description=(
                "Requirements\n- React\n- TypeScript\n- CSS\n"
                "Nice to have\n- Next.js\n\nThis role is open to recent graduates."
            ),
            posted_at=now - timedelta(days=5),
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-3",
            title="Senior Staff Software Engineer, Platform",
            company="Northwind Systems",
            location="Bengaluru, India",
            url="https://example.invalid/demo/senior-staff",
            employment_type="full_time",
            required_skills=["Python", "Kubernetes"],
            description=(
                "Requirements\n"
                "- 8+ years of professional software engineering experience\n"
                "- Deep Kubernetes expertise\n"
            ),
            posted_at=now - timedelta(days=3),
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-4",
            title="Technical Support Engineer - Tier 1",
            company="Helpdesk Collective",
            location="Noida, Uttar Pradesh",
            url="https://example.invalid/demo/support",
            employment_type="full_time",
            description=(
                "Answer customer tickets on a rotating night shift. Our stack runs on "
                "Linux and Docker, so familiarity helps but is not required."
            ),
            posted_at=now - timedelta(days=1),
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-5",
            title="Software Engineer",
            company="Terse Listings Inc",
            location="",
            url="https://example.invalid/demo/terse",
            description="We are hiring a software engineer. Apply now.",
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-6",
            title="Cloud Engineer - Associate",
            company="Stratus Works",
            location="Remote",
            work_arrangement="remote",
            employment_type="full_time",
            experience_raw="0-2 years",
            required_skills=["AWS", "Docker", "Linux", "Kubernetes"],
            description=(
                "Requirements\n- AWS\n- Docker\n- Linux\nNice to have\n- Kubernetes\n"
                "- Terraform\n\nEntry level, mentoring provided."
            ),
            posted_at=now - timedelta(days=9),
        ),
        RawJobRecord(
            source=SourceName.MANUAL,
            external_id="DEMO-7",
            title="Enterprise Account Executive",
            company="Palewind Labs",
            location="Mumbai, Maharashtra",
            url="https://example.invalid/demo/account-executive",
            employment_type="full_time",
            description=(
                "Own a revenue quota and run prospecting across our enterprise accounts. "
                "Our customers build on Python and SQL."
            ),
            posted_at=now - timedelta(days=4),
        ),
    ]


def seed_demo_data(session: Session) -> dict[str, int]:
    """Install the demo profile and sample jobs if they are not already present."""
    repository = ProfileRepository(session)
    profile = repository.get_or_create_default()
    if profile.full_name != DEMO_FULL_NAME:
        repository.update(profile, DEMO_PROFILE)
        session.flush()

    report = JobIngestService(session).ingest(
        _demo_jobs(), source=SourceName.MANUAL, trigger="demo_seed"
    )
    # Scored here, not left for the visitor to trigger: an unscored feed shows seven rows
    # with no band, no ring and no explanation, which looks broken rather than empty.
    scored = ScoringService(session).score_many(profile, rescore_all=True)
    session.commit()
    summary = {
        "jobs_created": report.jobs_created,
        "duplicates": report.duplicates_detected,
        "jobs_scored": scored.scored,
        "profile_id": profile.id,
    }
    logger.info("demo data seeded", extra={"demo_seed": summary})
    return summary
