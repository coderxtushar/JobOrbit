"""The one submission adapter in this build that actually submits.

It targets a loopback application server this project runs itself (see
``tests/support/application_server.py``), which is what makes the whole framework
verifiable: the multipart upload really happens, the confirmation id really comes back,
and the ``OUTCOME_UNKNOWN`` path can be produced on demand instead of being asserted in a
comment. Nobody's job is applied to on a test run.

Two guards keep it from becoming a way to submit to real employers:

* It is **unregistered unless configured.** ``JA_LOCAL_SUBMISSION_BASE_URL`` is empty by
  default, so :func:`build_local_test_adapter` returns ``None`` and the submission registry
  has no supported target at all.
* It **refuses any non-loopback address**, at construction. Pointing it at a public host
  raises rather than quietly working, because an adapter that submits is exactly the one
  that must not be repurposed by changing an environment variable.
"""

from __future__ import annotations

import ipaddress
import json
import os
from urllib.parse import urlsplit

import requests

from app.db.models import Job, utcnow
from app.logging_conf import get_logger
from app.submission.base import (
    Attachment,
    CapabilityReport,
    CredentialOwner,
    SubmissionAdapter,
    SubmissionResult,
)
from app.submission.forms import FieldKind, FilledForm, FormField, FormSpec
from app.submission.registry import LOCAL_TEST
from app.submission.states import SubmissionState

logger = get_logger(__name__)

#: Environment variable holding the loopback base URL of the test server. Empty by
#: default, which is what keeps submission switched off in every normal installation.
BASE_URL_ENV = "JA_LOCAL_SUBMISSION_BASE_URL"
TOKEN_ENV = "JA_LOCAL_SUBMISSION_TOKEN"

_TIMEOUT = 10.0


class NonLoopbackTarget(ValueError):
    """Raised when the submitting adapter is pointed at anything but loopback."""


def _require_loopback(base_url: str) -> str:
    host = (urlsplit(base_url).hostname or "").lower()
    if not host:
        raise NonLoopbackTarget(f"{base_url!r} has no host")
    if host == "localhost" or host.endswith(".localhost"):
        return base_url.rstrip("/")
    try:
        if ipaddress.ip_address(host).is_loopback:
            return base_url.rstrip("/")
    except ValueError as error:
        raise NonLoopbackTarget(
            f"{host!r} is not an IP address; the submitting adapter accepts loopback only"
        ) from error
    raise NonLoopbackTarget(
        f"{host!r} is not a loopback address. This adapter submits applications, so it is "
        "restricted to the local test server and must never be aimed at a real employer."
    )


def _field_from_json(raw: dict[str, object]) -> FormField:
    kind_value = str(raw.get("kind") or "text")
    try:
        kind = FieldKind(kind_value)
    except ValueError:
        kind = FieldKind.TEXT
    options = raw.get("options") or []
    return FormField(
        name=str(raw.get("name") or ""),
        label=str(raw.get("label") or raw.get("name") or ""),
        kind=kind,
        required=bool(raw.get("required")),
        options=tuple(str(o) for o in options) if isinstance(options, list) else (),
        question_key=str(raw.get("question_key") or ""),
        required_when=str(raw.get("required_when") or ""),
        max_length=int(str(raw.get("max_length") or 0)),
        sensitive=bool(raw.get("sensitive")),
    )


class LocalTestSubmissionAdapter(SubmissionAdapter):
    """Submits to the loopback test application server."""

    target = LOCAL_TEST

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = _require_loopback(base_url)
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    # -- capability -------------------------------------------------------------------

    def check_capability(self, job: Job) -> CapabilityReport:
        return CapabilityReport(
            supported=True,
            reason=(
                "JobOrbit's own loopback test server. Submission is authorized here "
                "because this project operates the server; it is not an employer."
            ),
            credential_owner=CredentialOwner.CANDIDATE,
            documented_api=True,
            browser_submission_permitted=False,
            manual_completion_required=False,
            accepts_resume_upload=True,
            evidence_url=self._base_url,
            evidence_quote="operated by this project for end-to-end verification",
        )

    # -- inspection -------------------------------------------------------------------

    def _job_key(self, job: Job) -> str:
        """Derive the server-side job key from the job's own application URL.

        Falls back to the database id so a job stored without a URL is still addressable
        in tests; a real provider would always be addressed by its own identifier.
        """
        path = urlsplit(job.url or "").path.strip("/").split("/")
        if "jobs" in path:
            index = path.index("jobs")
            if index + 1 < len(path):
                return path[index + 1]
        return str(job.id or "unknown")

    def inspect_application(self, job: Job) -> FormSpec:
        url = f"{self._base_url}/api/jobs/{self._job_key(job)}/form"
        try:
            response = self._session.get(url, timeout=_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, json.JSONDecodeError) as error:
            return FormSpec(human_required_reason=f"the form could not be read: {error}")

        human = str(payload.get("human_required") or "")
        if human:
            return FormSpec(human_required_reason=human)

        raw_fields = payload.get("fields") or []
        fields = tuple(_field_from_json(item) for item in raw_fields if isinstance(item, dict))
        return FormSpec(
            fields=fields,
            accepts_resume=bool(payload.get("accepts_resume")),
            accepts_cover_letter=bool(payload.get("accepts_cover_letter")),
        )

    # -- dispatch ---------------------------------------------------------------------

    def submit(
        self,
        job: Job,
        form: FilledForm,
        attachment: Attachment,
        *,
        idempotency_key: str,
    ) -> SubmissionResult:
        if not form.is_complete:
            return SubmissionResult(
                state=SubmissionState.BLOCKED_MISSING_INFO,
                reason="; ".join(form.blocking),
                completed_at=utcnow(),
            )

        values: dict[str, object] = dict(form.values)
        values.update({name: ("Yes" if ticked else "") for name, ticked in form.checked.items()})
        start_url = f"{self._base_url}/api/jobs/{self._job_key(job)}/applications"

        try:
            started = self._session.post(
                start_url,
                json={"fields": values, "cover_letter": form.values.get("cover_letter", "")},
                headers={"Idempotency-Key": idempotency_key},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as error:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=f"the form was never reached: {error}",
                completed_at=utcnow(),
            )

        if started.status_code == 401:
            return SubmissionResult(
                state=SubmissionState.REQUIRES_USER_ACTION,
                reason="your session with the provider has expired; sign in again",
                completed_at=utcnow(),
            )
        if started.status_code == 429:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason="the provider is rate limiting; this job will be retried",
                response_metadata={"retry_after": started.headers.get("Retry-After", "")},
                completed_at=utcnow(),
            )
        if started.status_code == 422:
            detail = started.json().get("fields", [])
            return SubmissionResult(
                state=SubmissionState.BLOCKED_MISSING_INFO,
                reason=f"the provider rejected the form as incomplete: {detail}",
                completed_at=utcnow(),
            )
        if started.status_code not in {200, 201}:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=f"the provider returned HTTP {started.status_code}",
                completed_at=utcnow(),
            )

        reference = str(started.json().get("reference") or "")
        if not reference:
            return SubmissionResult(
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason="the provider accepted the form but issued no reference",
                completed_at=utcnow(),
            )

        if attachment.ok and attachment.document is not None:
            upload = self._upload(reference, attachment)
            if upload is not None:
                return upload

        return self._commit(job, reference, attachment, idempotency_key)

    def _upload(self, reference: str, attachment: Attachment) -> SubmissionResult | None:
        """Upload the resume. Returns a result only on failure, so the caller can continue."""
        document = attachment.document
        assert document is not None  # guarded by the caller
        url = f"{self._base_url}/api/applications/{reference}/resume"
        try:
            response = self._session.post(
                url,
                files={"resume": (document.filename, document.content, "application/pdf")},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as error:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=f"the resume upload failed: {error}",
                provider_reference=reference,
                completed_at=utcnow(),
            )
        if response.status_code != 200:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=(
                    "the provider rejected the resume upload "
                    f"(HTTP {response.status_code}); nothing was submitted"
                ),
                provider_reference=reference,
                completed_at=utcnow(),
            )
        return None

    def _commit(
        self, job: Job, reference: str, attachment: Attachment, idempotency_key: str
    ) -> SubmissionResult:
        url = f"{self._base_url}/api/applications/{reference}/finish"
        resume_hash = attachment.document.content_sha256 if attachment.document is not None else ""
        try:
            response = self._session.post(
                url, headers={"Idempotency-Key": idempotency_key}, timeout=_TIMEOUT
            )
        except requests.RequestException as error:
            # The request left this machine and no reply came back. Whether the provider
            # committed it is genuinely unknown, so it is never retried automatically.
            return SubmissionResult(
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason=(
                    "the connection dropped while submitting, so it is unclear whether the "
                    f"application was received: {error}. Check the employer's site before "
                    "applying again."
                ),
                provider_reference=reference,
                submitted_url=job.url or "",
                resume_sha256=resume_hash,
                completed_at=utcnow(),
            )

        if response.status_code != 200:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=f"the provider returned HTTP {response.status_code} on submit",
                provider_reference=reference,
                completed_at=utcnow(),
            )

        payload = response.json()
        if not payload.get("confirmation_id"):
            return SubmissionResult(
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason=(
                    "the provider accepted the submission but issued no confirmation, so "
                    "it cannot be reported as sent"
                ),
                provider_reference=reference,
                submitted_url=job.url or "",
                resume_sha256=resume_hash,
                completed_at=utcnow(),
            )

        return SubmissionResult(
            state=SubmissionState.SUBMISSION_IN_PROGRESS,
            reason="submitted; awaiting verification",
            provider_reference=reference,
            submitted_url=job.url or "",
            resume_sha256=resume_hash,
            response_metadata={"confirmation_id": str(payload["confirmation_id"])},
        )

    # -- verification -----------------------------------------------------------------

    def verify_submission(self, result: SubmissionResult) -> SubmissionResult:
        """Confirm independently that the application exists on the provider's side.

        Deliberately re-reads rather than trusting the commit response: a provider that
        replies 200 and then fails to persist is the case this whole split exists for.
        """
        if not result.provider_reference:
            return result
        url = f"{self._base_url}/api/applications/{result.provider_reference}"
        try:
            response = self._session.get(url, timeout=_TIMEOUT)
        except requests.RequestException as error:
            result.state = SubmissionState.OUTCOME_UNKNOWN
            result.reason = f"the submission could not be verified: {error}"
            result.completed_at = utcnow()
            return result

        if response.status_code != 200:
            result.state = SubmissionState.OUTCOME_UNKNOWN
            result.reason = (
                f"the provider has no record to verify (HTTP {response.status_code}); "
                "check before applying again"
            )
            result.completed_at = utcnow()
            return result

        payload = response.json()
        confirmation = str(payload.get("confirmation_id") or "")
        if payload.get("status") == "confirmed" and confirmation:
            result.state = SubmissionState.SUBMITTED_CONFIRMED
            result.confirmation_id = confirmation
            result.reason = "the provider confirmed receipt"
            result.response_metadata["verified_status"] = "confirmed"
        else:
            result.state = SubmissionState.OUTCOME_UNKNOWN
            result.reason = (
                "the provider has a record but has not confirmed it; treat as unknown "
                "rather than sent"
            )
        result.completed_at = utcnow()
        return result


def build_local_test_adapter() -> LocalTestSubmissionAdapter | None:
    """Return the adapter when a loopback test server is configured, else ``None``.

    Returning ``None`` is the default and means the submission registry exposes no
    supported target, so a normal installation submits to nothing at all.
    """
    base_url = os.environ.get(BASE_URL_ENV, "").strip()
    if not base_url:
        return None
    token = os.environ.get(TOKEN_ENV, "").strip()
    try:
        return LocalTestSubmissionAdapter(base_url, token)
    except NonLoopbackTarget as error:
        logger.error("local_submission_target_rejected", extra={"reason": str(error)})
        return None
