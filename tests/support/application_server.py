"""A real HTTP application-form server, for proving the submission pipeline end to end.

This exists because the submission framework cannot be verified against any real
employer: doing so would send genuine applications on a test run. So this module serves a
multi-step application form over loopback with a synthetic account, and the local
submission adapter applies to it for real — request, upload, confirmation, verification.

The flow mirrors how a real ATS form behaves:

1. ``GET  /api/jobs/{job}/form`` — read the field list, options and required flags.
2. ``POST /api/jobs/{job}/applications`` — post the field values, receive a reference.
3. ``POST /api/applications/{ref}/resume`` — upload the document as ``multipart/form-data``.
4. ``POST /api/applications/{ref}/finish`` — commit, receive a confirmation id.
5. ``GET  /api/applications/{ref}`` — independent verification that it exists.

Every failure mode the orchestrator claims to handle is injectable through
:class:`ServerBehaviour`, including the two that matter most and cannot be produced on
demand against a real provider: ``drop_finish``, where the commit returns success with no
confirmation (the ``OUTCOME_UNKNOWN`` case), and ``reset_finish``, where the connection
dies mid-commit.

It binds to an ephemeral loopback port and holds everything in memory. Nothing here is
imported by the application at runtime.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any

#: The synthetic account the adapter signs in with. Not a credential for anything real;
#: it exists so the adapter's auth path is exercised rather than stubbed out.
SYNTHETIC_TOKEN = "joborbit-test-account-token"

DEFAULT_FORM: dict[str, Any] = {
    "accepts_resume": True,
    "accepts_cover_letter": True,
    "fields": [
        {"name": "full_name", "label": "Full name", "kind": "text", "required": True},
        {"name": "email", "label": "Email", "kind": "email", "required": True},
        {"name": "phone", "label": "Phone", "kind": "phone", "required": False},
        {
            "name": "work_authorization",
            "label": "Are you authorised to work in this country?",
            "kind": "radio",
            "required": True,
            "options": ["Yes", "No"],
            "question_key": "work_authorization",
            "sensitive": True,
        },
        {
            "name": "sponsorship_detail",
            "label": "If no, describe the sponsorship you need",
            "kind": "textarea",
            "required": False,
            "required_when": "needs_sponsorship",
        },
        {
            "name": "notice_period",
            "label": "Notice period",
            "kind": "text",
            "required": False,
            "question_key": "notice_period",
            "sensitive": True,
        },
        {
            "name": "why_this_role",
            "label": "Why this role?",
            "kind": "textarea",
            "required": False,
            "max_length": 2000,
        },
        {
            "name": "accept_terms",
            "label": "I confirm the information given is accurate",
            "kind": "checkbox",
            "required": True,
            "sensitive": True,
        },
    ],
}


@dataclass(slots=True)
class ServerBehaviour:
    """Failure modes the server can be told to produce."""

    #: Serve a form that no program may complete, standing in for a CAPTCHA gate.
    require_captcha: bool = False
    #: Same, for a multi-factor challenge on the candidate's account.
    require_mfa: bool = False
    #: Reject the bearer token, standing in for a session that has expired.
    reject_token: bool = False
    #: Fail the upload step with a provider-side error.
    fail_upload: bool = False
    #: Return 200 from the commit step with no confirmation id. Produces OUTCOME_UNKNOWN.
    drop_finish: bool = False
    #: Close the connection during the commit step, without replying.
    reset_finish: bool = False
    #: Reply 429 once this many applications have been started. 0 disables the limit.
    rate_limit_after: int = 0
    #: Replace the served form entirely.
    form: dict[str, Any] | None = None


@dataclass(slots=True)
class StoredApplication:
    """One application the server has accepted."""

    reference: str
    job_key: str
    fields: dict[str, Any]
    cover_letter: str = ""
    resume_filename: str = ""
    resume_bytes: int = 0
    confirmation_id: str = ""
    status: str = "open"
    idempotency_key: str = ""


@dataclass(slots=True)
class ServerState:
    behaviour: ServerBehaviour = field(default_factory=ServerBehaviour)
    applications: dict[str, StoredApplication] = field(default_factory=dict)
    #: Idempotency key to reference, so a retried commit returns the first result.
    by_idempotency: dict[str, str] = field(default_factory=dict)
    started: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def confirmed(self) -> list[StoredApplication]:
        return [a for a in self.applications.values() if a.status == "confirmed"]


def _split_multipart(body: bytes, content_type: str) -> tuple[str, bytes]:
    """Pull the filename and bytes out of a ``multipart/form-data`` body.

    A deliberately small parser rather than a dependency: the server controls both ends,
    and the point is that the adapter really does send a multipart upload instead of a
    convenient JSON blob that would never match a real form.
    """
    marker = "boundary="
    if marker not in content_type:
        return "", b""
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    separator = f"--{boundary}".encode()
    for part in body.split(separator):
        if b"\r\n\r\n" not in part:
            continue
        headers, _, payload = part.partition(b"\r\n\r\n")
        header_text = headers.decode("utf-8", "replace")
        if 'name="resume"' not in header_text:
            continue
        filename = ""
        if "filename=" in header_text:
            filename = header_text.split("filename=", 1)[1].split('"')[1]
        return filename, payload.rstrip(b"\r\n-")
    return "", b""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: ServerState

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        """Silence the default stderr access log; the tests assert on behaviour, not noise."""

    # -- helpers ----------------------------------------------------------------------

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        if self.state.behaviour.reject_token:
            return False
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {SYNTHETIC_TOKEN}"

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # -- routes -----------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        behaviour = self.state.behaviour

        if parts == ["api", "health"]:
            self._reply(200, {"status": "ok"})
            return

        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "form":
            if behaviour.require_captcha:
                self._reply(
                    200,
                    {"human_required": "this form is behind a CAPTCHA and needs a person"},
                )
                return
            if behaviour.require_mfa:
                self._reply(
                    200,
                    {"human_required": "your account needs a one-time code to continue"},
                )
                return
            self._reply(200, behaviour.form or DEFAULT_FORM)
            return

        if len(parts) == 3 and parts[:2] == ["api", "applications"]:
            record = self.state.applications.get(parts[2])
            if record is None:
                self._reply(404, {"error": "no such application"})
                return
            self._reply(
                200,
                {
                    "reference": record.reference,
                    "status": record.status,
                    "confirmation_id": record.confirmation_id,
                    "resume_filename": record.resume_filename,
                    "job": record.job_key,
                },
            )
            return

        self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        behaviour = self.state.behaviour
        body = self._read_body()

        if not self._authorised():
            self._reply(401, {"error": "session expired; sign in again"})
            return

        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "applications":
            self._start_application(parts[2], body)
            return

        if len(parts) == 4 and parts[:2] == ["api", "applications"]:
            reference, action = parts[2], parts[3]
            if action == "resume":
                self._upload_resume(reference, body)
                return
            if action == "finish":
                self._finish(reference)
                return

        self._reply(404, {"error": "not found"})
        _ = behaviour

    def _start_application(self, job_key: str, body: bytes) -> None:
        behaviour = self.state.behaviour
        with self.state.lock:
            self.state.started += 1
            started = self.state.started
        if behaviour.rate_limit_after and started > behaviour.rate_limit_after:
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self._reply(400, {"error": "body is not JSON"})
            return

        fields = payload.get("fields") or {}
        form = behaviour.form or DEFAULT_FORM
        missing = [
            spec["label"]
            for spec in form["fields"]
            if spec.get("required") and not str(fields.get(spec["name"], "")).strip()
        ]
        if missing:
            self._reply(422, {"error": "missing required fields", "fields": missing})
            return

        idempotency = self.headers.get("Idempotency-Key", "")
        with self.state.lock:
            existing = self.state.by_idempotency.get(idempotency) if idempotency else None
            if existing:
                self._reply(200, {"reference": existing, "replayed": True})
                return
            reference = f"ref-{secrets.token_hex(6)}"
            self.state.applications[reference] = StoredApplication(
                reference=reference,
                job_key=job_key,
                fields=fields,
                cover_letter=str(payload.get("cover_letter") or ""),
                idempotency_key=idempotency,
            )
            if idempotency:
                self.state.by_idempotency[idempotency] = reference
        self._reply(201, {"reference": reference})

    def _upload_resume(self, reference: str, body: bytes) -> None:
        record = self.state.applications.get(reference)
        if record is None:
            self._reply(404, {"error": "no such application"})
            return
        if self.state.behaviour.fail_upload:
            self._reply(502, {"error": "the document store rejected the upload"})
            return
        filename, content = _split_multipart(body, self.headers.get("Content-Type", ""))
        if not filename or not content:
            self._reply(400, {"error": "no resume part in the upload"})
            return
        record.resume_filename = filename
        record.resume_bytes = len(content)
        self._reply(200, {"ok": True, "bytes": len(content)})

    def _finish(self, reference: str) -> None:
        record = self.state.applications.get(reference)
        if record is None:
            self._reply(404, {"error": "no such application"})
            return
        behaviour = self.state.behaviour
        if behaviour.reset_finish:
            self.close_connection = True
            return
        if behaviour.drop_finish:
            # Accepted, but nothing is committed and no confirmation is issued: the state
            # a real provider leaves behind when a write fails after the HTTP layer
            # already replied. The adapter must report this as an unknown outcome.
            self._reply(200, {"accepted": True})
            return
        if record.status != "confirmed":
            record.confirmation_id = f"CONF-{secrets.token_hex(4).upper()}"
            record.status = "confirmed"
        self._reply(200, {"confirmation_id": record.confirmation_id, "status": "confirmed"})


class TestApplicationServer:
    """A loopback application-form server, usable as a context manager."""

    #: Its name begins with ``Test``, so pytest would otherwise try to collect it and warn
    #: about the constructor. It is a fixture helper, not a test case.
    __test__ = False

    def __init__(self, behaviour: ServerBehaviour | None = None) -> None:
        self.state = ServerState(behaviour=behaviour or ServerBehaviour())
        handler = type("_BoundHandler", (_Handler,), {"state": self.state})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="joborbit-test-ats", daemon=True
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def job_url(self, job_key: str) -> str:
        return f"{self.base_url}/api/jobs/{job_key}/form"

    def __enter__(self) -> TestApplicationServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
