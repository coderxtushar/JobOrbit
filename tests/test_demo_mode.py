"""Public-demo deployment: upload refusal, seeding, and the embedded API launcher.

The demo exists so the app can be shared without anyone's resume being on a server that
has no per-user login. These tests assert that guarantee where it is enforced — in the API
— rather than trusting the UI to hide a button.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings, reset_settings_cache
from app.db.models import CandidateProfile, Job
from app.services.demo import DEMO_EMAIL, DEMO_FULL_NAME, seed_demo_data


@pytest.fixture
def demo_client(engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JA_DEMO_MODE", "true")
    reset_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    reset_settings_cache()


# --------------------------------------------------------------------------------------
# The guarantee: no resume reaches a shared deployment
# --------------------------------------------------------------------------------------


def test_demo_mode_refuses_a_resume_upload(demo_client: TestClient) -> None:
    response = demo_client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "demo_mode_upload_blocked"
    assert "no per-user login" in body["message"]


def test_the_refusal_happens_before_the_file_is_read_or_stored(
    demo_client: TestClient, session: Session
) -> None:
    """A rejected upload must leave nothing behind, not even an unparsed blob."""
    demo_client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    listed = demo_client.get("/api/resumes").json()
    assert listed["total"] == 0


def test_upload_still_works_when_demo_mode_is_off(client: TestClient) -> None:
    """The control: the refusal is conditional, not a permanent removal of the feature."""
    response = client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
    )
    assert response.status_code != 403


def test_health_reports_demo_mode(demo_client: TestClient) -> None:
    assert demo_client.get("/health").json()["demo_mode"] is True


def test_health_reports_demo_mode_off_by_default(client: TestClient) -> None:
    assert client.get("/health").json()["demo_mode"] is False


# --------------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------------


def test_seeding_installs_a_scored_feed(session: Session) -> None:
    summary = seed_demo_data(session)
    assert summary["jobs_created"] == 7
    assert summary["jobs_scored"] == 7

    jobs = session.query(Job).all()
    bands = {job.id: (job.matches[0].band if job.matches else None) for job in jobs}
    assert None not in bands.values(), "an unscored demo feed looks broken, not empty"
    assert {"high", "review", "low"} <= set(bands.values()), (
        "the demo must show every band so a visitor sees what the score means"
    )


def test_seeding_is_idempotent(session: Session) -> None:
    """It runs on every boot, and Streamlit restarts the process whenever it wakes."""
    first = seed_demo_data(session)
    second = seed_demo_data(session)
    assert first["jobs_created"] == 7
    assert second["jobs_created"] == 0
    assert second["duplicates"] == 7
    assert session.query(Job).count() == 7


def test_the_seeded_candidate_is_unmistakably_fictional(session: Session) -> None:
    """Nobody should be able to mistake the demo profile for a real applicant."""
    seed_demo_data(session)
    profile = session.query(CandidateProfile).one()
    assert profile.full_name == DEMO_FULL_NAME
    assert "sample" in profile.full_name.lower()
    assert profile.email == DEMO_EMAIL
    assert profile.email.endswith(".invalid"), "a reserved TLD cannot belong to a real person"


def test_seeding_never_creates_a_resume_record(session: Session) -> None:
    from app.db.models import Resume

    seed_demo_data(session)
    assert session.query(Resume).count() == 0


# --------------------------------------------------------------------------------------
# The embedded API launcher
# --------------------------------------------------------------------------------------


def test_the_launcher_defers_to_a_configured_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """With JA_API_BASE_URL set it must start nothing, so a real deployment is not hijacked."""
    import threading

    from ui.embedded_api import ensure_api_running

    monkeypatch.setenv("JA_API_BASE_URL", "https://api.example.invalid")
    ensure_api_running.clear()
    status = ensure_api_running()
    ensure_api_running.clear()

    assert "external" in status
    assert "api.example.invalid" in status
    # Named rather than counted: Streamlit's own runtime starts threads of its own, so a
    # bare count would be measuring the framework instead of this module.
    assert "embedded-api" not in {thread.name for thread in threading.enumerate()}


def test_the_launcher_reports_an_already_running_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from ui import embedded_api

    monkeypatch.delenv("JA_API_BASE_URL", raising=False)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    monkeypatch.setenv("JA_API_PORT", str(port))
    try:
        embedded_api.ensure_api_running.clear()
        status = embedded_api.ensure_api_running()
        embedded_api.ensure_api_running.clear()
    finally:
        listener.close()
    assert "already running" in status
    assert str(port) in status


def test_demo_mode_is_off_unless_the_environment_asks_for_it() -> None:
    os.environ.pop("JA_DEMO_MODE", None)
    reset_settings_cache()
    assert get_settings().demo_mode is False
    reset_settings_cache()
