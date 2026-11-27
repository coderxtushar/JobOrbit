"""Hosted (Google sign-in) mode: verified identity, sessions, route policy and isolation.

No test reaches Google. ID tokens are signed here with a throwaway RSA key and the module
is pointed at its public half, so the real verification code (signature, issuer,
audience, expiry, verified email) runs unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import HOSTED_OPEN, HOSTED_POLICY
from app.config import reset_settings_cache
from app.db.models import CandidateProfile, User, UserSession
from app.services import accounts
from tests.conftest import make_docx, persist_job

CLIENT_ID = "test-client.apps.googleusercontent.com"
SERVICE_TOKEN = "service-token-for-tests"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(
    sub: str,
    email: str,
    *,
    audience: str = CLIENT_ID,
    verified: bool = True,
    expires_in: int = 600,
    key=_KEY,
) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": audience,
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "name": email.split("@")[0].title(),
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JA_AUTH_MODE", "google")
    monkeypatch.setenv("JA_GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JA_API_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv("JA_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(accounts, "_signing_key", lambda _token: _KEY.public_key())
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def api(hosted: None, engine) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        test_client.headers["Authorization"] = f"Bearer {SERVICE_TOKEN}"
        yield test_client


def sign_in(api: TestClient, sub: str, email: str) -> dict[str, str]:
    response = api.post("/api/auth/session", json={"id_token": google_token(sub, email)})
    assert response.status_code == 201, response.text
    return {"X-JobOrbit-Session": response.json()["session_token"]}


# ---------------------------------------------------------------- verification


def test_a_valid_google_token_is_accepted(hosted: None) -> None:
    identity = accounts.verify_google_id_token(
        google_token("sub-1", "Ada@Example.com"), CLIENT_ID, key=_KEY.public_key()
    )
    assert identity.subject == "sub-1"
    assert identity.email == "ada@example.com"


@pytest.mark.parametrize(
    "token_kwargs, code",
    [
        ({"audience": "someone-elses-client"}, "invalid_id_token"),
        ({"expires_in": -3600}, "invalid_id_token"),
        ({"verified": False}, "email_not_verified"),
        (
            {"key": rsa.generate_private_key(public_exponent=65537, key_size=2048)},
            "invalid_id_token",
        ),
    ],
)
def test_a_token_google_did_not_issue_for_us_is_refused(
    hosted: None, token_kwargs: dict, code: str
) -> None:
    token = google_token("sub-1", "ada@example.com", **token_kwargs)
    with pytest.raises(accounts.SignInError) as refused:
        accounts.verify_google_id_token(token, CLIENT_ID, key=_KEY.public_key())
    assert refused.value.code == code


# ---------------------------------------------------------------- sessions


def test_signing_in_creates_the_user_a_profile_and_a_hashed_session(
    api: TestClient, session: Session
) -> None:
    response = api.post(
        "/api/auth/session", json={"id_token": google_token("sub-ada", "ada@example.com")}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["is_new_user"] is True
    assert body["account"]["email"] == "ada@example.com"

    token = body["session_token"]
    stored = session.scalars(select(UserSession)).all()
    assert len(stored) == 1
    assert stored[0].token_hash == accounts.hash_token(token)
    assert token not in stored[0].token_hash
    profile = session.scalars(select(CandidateProfile)).one()
    assert profile.email == "ada@example.com"

    again = api.post(
        "/api/auth/session", json={"id_token": google_token("sub-ada", "ada@example.com")}
    )
    assert again.json()["is_new_user"] is False
    assert session.scalar(select(func.count(User.id))) == 1


def test_requests_without_a_live_session_must_sign_in(api: TestClient) -> None:
    assert api.get("/api/profile").json()["error"]["code"] == "signin_required"
    forged = api.get("/api/profile", headers={"X-JobOrbit-Session": "not-a-real-session"})
    assert forged.status_code == 401

    headers = sign_in(api, "sub-ada", "ada@example.com")
    assert api.get("/api/profile", headers=headers).status_code == 200
    assert api.delete("/api/auth/session", headers=headers).status_code == 204
    assert api.get("/api/profile", headers=headers).status_code == 401


def test_the_service_token_is_still_required(api: TestClient) -> None:
    headers = sign_in(api, "sub-ada", "ada@example.com")
    stolen_cookie_only = api.get(
        "/api/profile", headers={**headers, "Authorization": "Bearer wrong"}
    )
    assert stolen_cookie_only.status_code == 401


def test_admin_routes_and_local_only_features_are_refused(api: TestClient) -> None:
    user = sign_in(api, "sub-ada", "ada@example.com")
    admin = sign_in(api, "sub-admin", "admin@example.com")

    discover = api.post("/api/jobs/discover", json={}, headers=user)
    assert discover.status_code == 403
    assert discover.json()["error"]["code"] == "admin_only"
    assert api.get("/api/diagnostics", headers=admin).status_code == 200

    email = api.get("/api/email/status", headers=admin)
    assert email.status_code == 403
    assert "local install" in email.json()["error"]["message"]
    run = api.post("/api/autoapply/runs", json={}, headers=user)
    assert run.json()["error"]["code"] == "hosted_start_run_unavailable"


def test_sign_ups_stop_at_the_account_limit(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JA_MAX_USERS", "1")
    reset_settings_cache()
    sign_in(api, "sub-ada", "ada@example.com")
    second = api.post(
        "/api/auth/session", json={"id_token": google_token("sub-bo", "bo@example.com")}
    )
    assert second.status_code == 403
    assert second.json()["error"]["code"] == "sign_ups_closed"


def test_every_route_has_a_hosted_mode_decision(hosted: None) -> None:
    from app.main import create_app

    names = {
        route.endpoint.__name__ for route in create_app().routes if isinstance(route, APIRoute)
    }
    unclassified = names - set(HOSTED_POLICY) - HOSTED_OPEN
    assert not unclassified, f"routes with no hosted-mode policy: {sorted(unclassified)}"


# ---------------------------------------------------------------- deletion


def test_deleting_an_account_removes_everything_it_owned(api: TestClient, session: Session) -> None:
    headers = sign_in(api, "sub-ada", "ada@example.com")
    api.put("/api/answers/notice_period", json={"answer": "30 days"}, headers=headers)
    api.post("/api/searches", json={"name": "Python", "criteria": {}}, headers=headers)

    wrong = api.post(
        "/api/auth/account/delete", json={"confirm_email": "someone@example.com"}, headers=headers
    )
    assert wrong.status_code == 400
    deleted = api.post(
        "/api/auth/account/delete", json={"confirm_email": "ADA@example.com"}, headers=headers
    )
    assert deleted.status_code == 204

    session.expire_all()
    assert session.scalar(select(func.count(User.id))) == 0
    assert session.scalar(select(func.count(CandidateProfile.id))) == 0
    assert session.scalar(select(func.count(UserSession.id))) == 0
    assert api.get("/api/profile", headers=headers).status_code == 401


# ---------------------------------------------------------------- isolation


def _items(response) -> list:
    body = response.json()
    return body["items"] if isinstance(body, dict) else body


def test_two_users_never_see_each_others_data(api: TestClient, session: Session) -> None:
    job = persist_job(session, external_id="ISO-1", url="https://jobs.example.com/view/iso-1")
    other_job = persist_job(
        session,
        external_id="ISO-2",
        url="https://jobs.example.com/view/iso-2",
        title="Frontend Developer",
    )
    session.commit()
    ada = sign_in(api, "sub-ada", "ada@example.com")
    bo = sign_in(api, "sub-bo", "bo@example.com")

    # Ada builds up some state.
    resume = api.post(
        "/api/resumes",
        files={"file": ("resume.docx", make_docx(["Ada Lovelace", "ada@example.com", "Python"]))},
        headers=ada,
    )
    assert resume.status_code == 201, resume.text
    resume_id = resume.json()["resume"]["id"]
    api.put("/api/answers/notice_period", json={"answer": "30 days"}, headers=ada)
    search = api.post("/api/searches", json={"name": "Python", "criteria": {}}, headers=ada)
    search_id = search.json()["id"]
    assert api.post(f"/api/jobs/{job.id}/shortlist", headers=ada).status_code == 200
    assert api.post(f"/api/jobs/{other_job.id}/skip", headers=ada).status_code == 200
    prepared = api.post("/api/applications/prepare", json={"job_id": job.id}, headers=ada)
    assert prepared.status_code == 201, prepared.text
    application_id = prepared.json()["id"]

    # Hosted mode keeps the parsed fields, never the file itself.
    from app.config import get_settings

    assert list(get_settings().resume_dir.iterdir()) == []

    # Bo sees none of it, by listing or by id.
    assert _items(api.get("/api/resumes", headers=bo)) == []
    assert api.get(f"/api/resumes/{resume_id}", headers=bo).status_code == 404
    assert _items(api.get("/api/answers", headers=bo)) == []
    assert _items(api.get("/api/searches", headers=bo)) == []
    assert api.get(f"/api/searches/{search_id}/preview", headers=bo).status_code == 404
    assert api.get("/api/applications", headers=bo).json()["total"] == 0
    assert api.get(f"/api/applications/{application_id}", headers=bo).status_code == 404
    bo_jobs = {item["id"]: item for item in api.get("/api/jobs", headers=bo).json()["items"]}
    assert bo_jobs[job.id]["status"] not in ("SHORTLISTED", "SKIPPED")
    assert other_job.id in bo_jobs, "Ada skipping a job must not hide it from Bo"
    assert bo_jobs[job.id]["has_application"] is False
    metrics = api.get("/api/metrics", headers=bo).json()
    assert metrics["applications_prepared"] == 0

    # Ada still sees her own.
    ada_jobs = {item["id"]: item for item in api.get("/api/jobs", headers=ada).json()["items"]}
    assert ada_jobs[job.id]["status"] == "SHORTLISTED"
    assert other_job.id not in ada_jobs or ada_jobs[other_job.id]["status"] == "SKIPPED"
    assert api.get("/api/applications", headers=ada).json()["total"] == 1


def test_batches_and_auto_apply_runs_belong_to_their_owner(
    api: TestClient, session: Session
) -> None:
    from app.db.models import AutoApplyRun, BatchRun

    ada = sign_in(api, "sub-ada", "ada@example.com")
    bo = sign_in(api, "sub-bo", "bo@example.com")
    ada_profile_id = api.get("/api/auth/me", headers=ada).json()["profile_id"]
    batch = BatchRun(profile_id=ada_profile_id)
    run = AutoApplyRun(profile_id=ada_profile_id)
    session.add_all([batch, run])
    session.commit()

    assert api.get("/api/batches", headers=bo).json()["total"] == 0
    assert api.get(f"/api/batches/{batch.id}", headers=bo).status_code == 404
    assert api.post(f"/api/batches/{batch.id}/cancel", headers=bo).status_code == 404
    assert api.get("/api/autoapply", headers=bo).json()["total"] == 0
    assert api.get(f"/api/autoapply/runs/{run.id}", headers=bo).status_code == 404
    assert api.post(f"/api/autoapply/runs/{run.id}/cancel", headers=bo).status_code == 404

    assert api.get("/api/batches", headers=ada).json()["total"] == 1
    assert api.get(f"/api/autoapply/runs/{run.id}", headers=ada).status_code == 200
