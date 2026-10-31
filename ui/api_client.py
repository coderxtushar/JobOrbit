"""HTTP client used by the dashboard.

The UI talks to the backend only through this module, which is what keeps the Streamlit
layer replaceable by a React frontend later. API errors arrive in one shape, so
:class:`ApiClientError` carries the server's own user-facing message straight to the screen
rather than a generic "request failed".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_TIMEOUT = 120


class ApiClientError(RuntimeError):
    def __init__(self, message: str, code: str = "", field_errors: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.field_errors = field_errors or {}


@dataclass(slots=True)
class ApiClient:
    base_url: str
    token: str = ""
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> ApiClient:
        host = os.environ.get("JA_API_HOST", "127.0.0.1")
        port = os.environ.get("JA_API_PORT", "8000")
        return cls(
            base_url=os.environ.get("JA_API_BASE_URL", f"http://{host}:{port}"),
            token=os.environ.get("JA_API_TOKEN", ""),
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = requests.request(
                method, url, headers=self._headers, timeout=self.timeout, **kwargs
            )
        except requests.exceptions.ConnectionError as exc:
            raise ApiClientError(
                f"Cannot reach the API at {self.base_url}. Start it with "
                "`uvicorn app.main:app --host 127.0.0.1 --port 8000`.",
                code="connection_error",
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise ApiClientError(
                f"The API did not respond within {self.timeout}s.", code="timeout"
            ) from exc

        if response.status_code >= 400:
            message = f"HTTP {response.status_code}"
            code = "http_error"
            field_errors: dict = {}
            try:
                body = response.json()
                error = body.get("error") or {}
                message = error.get("message") or message
                code = error.get("code") or code
                field_errors = error.get("field_errors") or {}
            except ValueError:
                pass
            raise ApiClientError(message, code=code, field_errors=field_errors)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ---------------- system ----------------

    def health(self) -> dict:
        return self._request("GET", "/health")

    def diagnostics(self) -> dict:
        return self._request("GET", "/api/diagnostics")

    def metrics(self) -> dict:
        return self._request("GET", "/api/metrics")

    def estimated_metrics(self) -> dict:
        return self._request("GET", "/api/metrics/estimated")

    def duplication_metrics(self, suspect_limit: int = 25) -> dict:
        return self._request(
            "GET", "/api/metrics/duplication", params={"suspect_limit": suspect_limit}
        )

    def audit_logs(self, limit: int = 50, offset: int = 0, action: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if action:
            params["action"] = action
        return self._request("GET", "/api/audit-logs", params=params)

    def import_runs(self, limit: int = 25) -> dict:
        return self._request("GET", "/api/import-runs", params={"limit": limit})

    # ---------------- profile ----------------

    def get_profile(self) -> dict:
        return self._request("GET", "/api/profile")

    def update_profile(self, payload: dict) -> dict:
        return self._request("PUT", "/api/profile", json=payload)

    # ---------------- resumes ----------------

    def upload_resume(self, filename: str, data: bytes, label: str, is_primary: bool) -> dict:
        return self._request(
            "POST",
            "/api/resumes",
            files={"file": (filename, data)},
            data={"label": label, "is_primary": str(is_primary).lower()},
        )

    def list_resumes(self) -> dict:
        return self._request("GET", "/api/resumes", params={"limit": 50})

    def parsed_resume(self, resume_id: int) -> dict:
        return self._request("GET", f"/api/resumes/{resume_id}/parsed")

    def set_primary_resume(self, resume_id: int) -> dict:
        return self._request("POST", f"/api/resumes/{resume_id}/primary")

    def list_variants(self, resume_id: int) -> dict:
        return self._request("GET", f"/api/resumes/{resume_id}/variants")

    def create_variant(self, payload: dict) -> dict:
        return self._request("POST", "/api/resumes/variants", json=payload)

    # ---------------- jobs ----------------

    def import_jobs_json(self, records: list[dict], trigger: str = "manual") -> dict:
        return self._request(
            "POST", "/api/jobs/import", json={"records": records, "trigger": trigger}
        )

    def import_jobs_file(self, filename: str, data: bytes, source: str) -> dict:
        return self._request(
            "POST",
            "/api/jobs/import-csv",
            files={"file": (filename, data)},
            data={"source": source},
        )

    def discover(self, sources: list[str] | None = None) -> list[dict]:
        payload: dict[str, Any] = {"trigger": "manual"}
        if sources:
            payload["sources"] = sources
        return self._request("POST", "/api/jobs/discover", json=payload)

    def score(
        self, job_ids: list[int] | None = None, rescore_all: bool = False, offset: int = 0
    ) -> dict:
        payload: dict[str, Any] = {"rescore_all": rescore_all, "offset": offset}
        if job_ids:
            payload["job_ids"] = job_ids
        return self._request("POST", "/api/jobs/score", json=payload)

    def list_jobs(self, **params: Any) -> dict:
        clean = {key: value for key, value in params.items() if value not in (None, "", [])}
        return self._request("GET", "/api/jobs", params=clean)

    def get_job(self, job_id: int) -> dict:
        return self._request("GET", f"/api/jobs/{job_id}")

    def shortlist(self, job_id: int) -> dict:
        return self._request("POST", f"/api/jobs/{job_id}/shortlist")

    def skip(self, job_id: int, reason: str = "") -> dict:
        return self._request("POST", f"/api/jobs/{job_id}/skip", params={"reason": reason})

    # ---------------- applications ----------------

    def prepare_application(
        self,
        job_id: int,
        include_cover_letter: bool = True,
        extra_questions: list[str] | None = None,
    ) -> dict:
        return self._request(
            "POST",
            "/api/applications/prepare",
            json={
                "job_id": job_id,
                "include_cover_letter": include_cover_letter,
                "extra_questions": extra_questions or [],
            },
        )

    def list_applications(self, **params: Any) -> dict:
        clean = {key: value for key, value in params.items() if value not in (None, "", [])}
        return self._request("GET", "/api/applications", params=clean)

    def get_application(self, application_id: int) -> dict:
        return self._request("GET", f"/api/applications/{application_id}")

    def update_application(self, application_id: int, payload: dict) -> dict:
        return self._request("PATCH", f"/api/applications/{application_id}", json=payload)

    # ---------------- bulk preparation ----------------

    def preview_batch(self, payload: dict) -> dict:
        return self._request("POST", "/api/batches/preview", json=payload)

    def start_batch(self, payload: dict) -> dict:
        return self._request("POST", "/api/batches", json=payload)

    def list_batches(self, limit: int = 20, offset: int = 0) -> dict:
        return self._request("GET", "/api/batches", params={"limit": limit, "offset": offset})

    def get_batch(self, run_id: int) -> dict:
        return self._request("GET", f"/api/batches/{run_id}")

    def cancel_batch(self, run_id: int) -> dict:
        return self._request("POST", f"/api/batches/{run_id}/cancel")

    def resume_batch(self, run_id: int) -> dict:
        return self._request("POST", f"/api/batches/{run_id}/resume")

    # ---------------- answer bank ----------------

    def list_answers(self) -> list[dict]:
        return self._request("GET", "/api/answers")

    def action_inbox(self, limit: int = 100) -> list[dict]:
        return self._request("GET", "/api/answers/inbox", params={"limit": limit})

    def save_answer(self, question_key: str, payload: dict) -> dict:
        return self._request("PUT", f"/api/answers/{question_key}", json=payload)

    def delete_answer(self, question_key: str) -> None:
        self._request("DELETE", f"/api/answers/{question_key}")

    # ---------------- sources ----------------

    def list_sources(self) -> list[dict]:
        return self._request("GET", "/api/sources")

    def update_source(self, source: str, payload: dict) -> dict:
        return self._request("PATCH", f"/api/sources/{source}", json=payload)
