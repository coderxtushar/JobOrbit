"""Submit applications through an employer's own Greenhouse, Lever or Ashby form.

This is the adapter that makes auto-apply real. For each queued job it opens the
employer's hosted application form in JobOrbit's own Chrome profile, reads every question
off the live page, fills it from verified answers, attaches the resume, checks that the
open page is still the queued job, presses Submit and reads the outcome back.

What it will not do is decided per field, not per form, and every refusal ends in the
user's Action inbox rather than a guess:

* a question with no stored answer, or only a generated one where a verified answer is
  required, is raised once into the inbox and the job waits;
* a consent or declaration is ticked only from the user's own answer to that exact text;
* a visible CAPTCHA or human check is never solved or dismissed: the tab is left open and
  the attempt is marked as needing the user;
* an outcome it cannot read back is ``OUTCOME_UNKNOWN`` and never retried, because a retry
  after an unknown outcome is how one application becomes two.

The adapter is registered only when ``JA_BROWSER_SUBMISSION_ENABLED`` is true, and every
run is a dry run unless the user starts it otherwise, so installing JobOrbit still submits
nothing until the user decides it should.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit, urlunsplit

from app.browser import dom
from app.browser.labels import (
    classify_choice,
    classify_label,
    link_for,
    option_key,
    resolve_option,
    split_name,
)
from app.db.models import AnswerProvenance, Job, utcnow
from app.logging_conf import get_logger
from app.submission.base import (
    Attachment,
    CandidateIdentity,
    CapabilityReport,
    CredentialOwner,
    ResumeDocument,
    SubmissionAdapter,
    SubmissionResult,
    SubmissionTarget,
)
from app.submission.forms import (
    AnswerValue,
    FieldKind,
    FilledForm,
    FormField,
    FormSpec,
    PendingQuestion,
    fill_form,
    validate_document,
)
from app.submission.states import FailureCategory, SubmissionState

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import BrowserContext, Page

    from app.browser.session import BrowserWorker

logger = get_logger(__name__)

MAX_RESUME_BYTES = 5 * 1024 * 1024

_KIND_MAP: dict[str, FieldKind] = {
    "text": FieldKind.TEXT,
    "date": FieldKind.TEXT,
    "email": FieldKind.EMAIL,
    "tel": FieldKind.PHONE,
    "url": FieldKind.URL,
    "number": FieldKind.NUMBER,
    "textarea": FieldKind.TEXTAREA,
    "select": FieldKind.SELECT,
    "multiselect": FieldKind.CHECKBOX,
    "combobox": FieldKind.SELECT,
    "radio": FieldKind.RADIO,
    "buttons": FieldKind.RADIO,
    "checkbox": FieldKind.CHECKBOX,
    "checkbox_group": FieldKind.CHECKBOX,
    "file": FieldKind.FILE,
}

_IDENTITY_KEYS = {"full_name", "first_name", "last_name", "email", "phone"}
_CLOSED = re.compile(
    r"no longer (available|accepting|open)|job (is )?not found|position (has been )?(filled|closed)|"
    r"page (you('| a)re looking for )?(could not be found|doesn't exist)|this job (has )?(closed|expired)",
    re.I,
)


def lever_apply_url(job: Job) -> str:
    parts = urlsplit(job.url or "")
    path = re.sub(r"/apply/?$", "", parts.path.rstrip("/"))
    return urlunsplit((parts.scheme or "https", parts.netloc, path + "/apply", parts.query, ""))


def ashby_apply_url(job: Job) -> str:
    parts = urlsplit(job.url or "")
    path = re.sub(r"/application/?$", "", parts.path.rstrip("/"))
    return urlunsplit(
        (parts.scheme or "https", parts.netloc, path + "/application", parts.query, "")
    )


def greenhouse_apply_url(job: Job) -> str:
    """The Greenhouse form for the job.

    A greenhouse.io URL is used as it is. A job listed on the company's own careers site
    opens Greenhouse's official embed form for that board and job, which is the same
    form the careers page frames, so the page JobOrbit reads is still Greenhouse's.
    """
    url = job.url or ""
    if "greenhouse.io" in (urlsplit(url).hostname or ""):
        return url
    from app.submission.registry import greenhouse_reference

    reference = greenhouse_reference(job)
    if reference is None:
        return url
    board, job_id = reference
    return (
        "https://job-boards.greenhouse.io/embed/job_app?"
        f"for={quote(board, safe='')}&token={quote(job_id, safe='')}"
    )


#: Tabs left open for the user after an unclear outcome or a CAPTCHA, by (target, job).
_KEPT_OPEN: dict[tuple[str, int], _OpenForm] = {}


@dataclass(slots=True)
class _OpenForm:
    """A form open in a browser tab, with what was read off it."""

    page: Page
    url: str
    spec: FormSpec
    dom_by_name: dict[str, dom.DomField]
    resume_field: dom.DomField | None = None
    blocked_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    #: A :class:`~app.submission.states.FailureCategory` value when ``blocked_reason`` is set.
    blocked_category: str = ""


class BrowserFormAdapter(SubmissionAdapter):
    """Fills and submits one ATS provider's hosted application form in the browser."""

    def __init__(
        self,
        target: SubmissionTarget,
        *,
        apply_url: Callable[[Job], str],
        browser: Callable[[], BrowserWorker] | None = None,
        data_dir: Path | None = None,
        pacing: dom.Pacing | None = None,
        confirmation_timeout_s: float = 25,
        evidence_screenshots: bool = True,
    ) -> None:
        self.target = target
        self._apply_url = apply_url
        self._browser_factory = browser
        self._data_dir = data_dir or Path("./var")
        self._pacing = pacing or dom.Pacing()
        self._confirmation_timeout_s = confirmation_timeout_s
        self._evidence_screenshots = evidence_screenshots
        self._open: dict[int, _OpenForm] = {}
        #: Copies of the resume written for upload. Deleted when the job is released: the
        #: browser has read the file by then, and a second copy of a resume is a liability.
        self._staged: list[Path] = []
        #: Set by the orchestrator for the duration of one ``submit``. Called on the
        #: orchestrator's own thread between browser steps, so it can commit a durable
        #: checkpoint *before* Submit is pressed.
        self.checkpoint_hook: Callable[[str, str], None] | None = None

    # ---------------- plumbing ----------------

    def _browser(self) -> BrowserWorker:
        if self._browser_factory is not None:
            return self._browser_factory()
        from app.browser.session import get_browser

        return get_browser()

    @staticmethod
    def _job_key(job: Job) -> int:
        return int(job.id) if job.id is not None else id(job)

    def _call(self, func: Callable[[BrowserContext], Any]) -> Any:
        return self._browser().call(func)

    # ---------------- contract ----------------

    def check_capability(self, job: Job) -> CapabilityReport:
        return CapabilityReport(
            supported=True,
            reason=(
                f"JobOrbit fills {self.target.display_name}'s hosted application form in its "
                "own Chrome window from your verified answers and presses Submit. A CAPTCHA, a "
                "sign-in wall or an unanswered question stops that job and hands it to you."
            ),
            credential_owner=CredentialOwner.NONE,
            documented_api=False,
            browser_submission_permitted=True,
            manual_completion_required=False,
            accepts_resume_upload=True,
        )

    def inspect_application(self, job: Job) -> FormSpec:
        key = self._job_key(job)
        if key in self._open:
            return self._open[key].spec
        url = self._apply_url(job)
        opened: _OpenForm = self._call(lambda ctx: self._open_form(ctx, job, url))
        self._open[key] = opened
        return opened.spec

    def _open_form(self, ctx: BrowserContext, job: Job, url: str) -> _OpenForm:
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001 - analytics beacons keep some pages "busy"
                pass
            self._pacing.pause()
            category, blocked = self._blocking_condition(page, job)
            if blocked:
                return _OpenForm(
                    page,
                    url,
                    FormSpec(human_required_reason=blocked),
                    {},
                    None,
                    blocked,
                    blocked_category=category,
                )
            fields = dom.discover_fields(page)
            enriched: list[dom.DomField] = []
            for item in fields:
                if item.kind == "combobox" and not item.options:
                    options = dom.read_combobox_options(page, item)
                    item = dataclasses.replace(item, options=options)
                enriched.append(item)
            spec, by_name, resume_field = self._spec_from_dom(job, enriched)
            if not spec.fields and resume_field is None:
                reason = "no application form was found on the page (the posting may have closed)"
                return _OpenForm(
                    page,
                    url,
                    FormSpec(human_required_reason=reason),
                    {},
                    None,
                    reason,
                    blocked_category=FailureCategory.FORM_CHANGED,
                )
            return _OpenForm(page, url, spec, by_name, resume_field)
        except Exception as error:  # noqa: BLE001 - reported on the attempt, not raised
            reason = f"the application form could not be read: {error}"
            category = (
                FailureCategory.TIMEOUT
                if "timeout" in str(error).casefold()
                else FailureCategory.TRANSIENT
            )
            return _OpenForm(
                page,
                url,
                FormSpec(human_required_reason=reason),
                {},
                None,
                reason,
                blocked_category=category,
            )

    def _blocking_condition(self, page: Page, job: Job) -> tuple[str, str]:
        """``(failure category, reason)`` for a page no program may proceed on, else blanks."""
        challenge = dom.visible_challenge(page)
        if challenge:
            return (
                FailureCategory.CAPTCHA,
                f"a {challenge} is showing on the form; it needs you, not a program",
            )
        prompt = dom.verification_prompt(page)
        if prompt:
            return (
                FailureCategory.MFA,
                f"the page is asking for a verification code ({prompt}); enter it yourself in "
                "JobOrbit's Chrome window",
            )
        text = dom.page_text(page)
        if _CLOSED.search(text[:4000]):
            return FailureCategory.POSTING_CLOSED, "the employer's page says this posting is closed"
        if page.locator("input[type=password]:visible").count():
            return (
                FailureCategory.SIGN_IN_REQUIRED,
                "the form asks you to sign in first (or your session expired); sign in once "
                "in JobOrbit's Chrome window",
            )
        problem = dom.identity_problem(page, title=job.title or "", company=job.company or "")
        if problem:
            return FailureCategory.WRONG_PAGE, f"wrong page: {problem}"
        return "", ""

    def blocked_condition(self, job: Job) -> tuple[str, str] | None:
        """Why the opened form cannot be filled, as ``(category, reason)``, or ``None``.

        Lets the orchestrator tell a CAPTCHA (needs the user) from a closed posting (final)
        from a page that failed to load (worth retrying), instead of reporting all three as
        a missing answer.
        """
        opened = self._open.get(self._job_key(job))
        if opened is None or not opened.blocked_reason:
            return None
        return opened.blocked_category or FailureCategory.TRANSIENT, opened.blocked_reason

    def _spec_from_dom(
        self, job: Job, fields: list[dom.DomField]
    ) -> tuple[FormSpec, dict[str, dom.DomField], dom.DomField | None]:
        form_fields: list[FormField] = []
        by_name: dict[str, dom.DomField] = {}
        resume_field: dom.DomField | None = None
        accepts_cover = False
        for item in fields:
            kind = _KIND_MAP.get(item.kind, FieldKind.TEXT)
            if item.kind == "combobox" and not item.options:
                kind = FieldKind.TEXT
            if item.options and kind in {FieldKind.SELECT, FieldKind.RADIO, FieldKind.CHECKBOX}:
                classified = classify_choice(item.label, item.options, company=job.company or "")
            else:
                classified = classify_label(
                    item.label, company=job.company or "", long_answer=item.kind == "textarea"
                )
            if kind is FieldKind.FILE:
                # Greenhouse labels its resume input only "Attach"; its id is "resume".
                named_resume = re.search(r"resume|\bcv\b", item.name, re.I) is not None
                if (classified.key == "resume" or named_resume) and resume_field is None:
                    resume_field = item
                    continue
                if classified.key == "cover_letter":
                    accepts_cover = True
                if not item.required or not item.label:
                    continue  # an optional or unlabelled upload (Ashby's "autofill") is skipped
            if not item.label:
                if item.required:
                    form_fields.append(
                        FormField(
                            name=f"f{item.index}",
                            label="An unlabelled required field",
                            kind=kind,
                            required=True,
                        )
                    )
                    by_name[f"f{item.index}"] = item
                continue
            name = f"f{item.index}"
            by_name[name] = item
            form_fields.append(
                FormField(
                    name=name,
                    label=item.label,
                    kind=kind,
                    required=item.required,
                    options=item.options
                    if kind in {FieldKind.SELECT, FieldKind.RADIO, FieldKind.CHECKBOX}
                    else (),
                    question_key=classified.key,
                    max_length=item.max_length,
                    sensitive=classified.sensitive,
                )
            )
        spec = FormSpec(
            fields=tuple(form_fields),
            accepts_resume=resume_field is not None,
            accepts_cover_letter=accepts_cover,
        )
        return spec, by_name, resume_field

    def prepare_fields(
        self, job: Job, identity: CandidateIdentity, answers: dict[str, AnswerValue]
    ) -> FilledForm:
        spec = self.inspect_application(job)
        merged: dict[str, AnswerValue] = dict(answers)
        first, last = split_name(identity.full_name)
        for key, value in (
            ("full_name", identity.full_name),
            ("first_name", first),
            ("last_name", last),
            ("email", identity.email),
            ("phone", identity.phone),
            ("linkedin", link_for("linkedin", identity.links)),
            ("github", link_for("github", identity.links)),
            ("portfolio", link_for("portfolio", identity.links)),
        ):
            if value and key not in merged:
                merged[key] = AnswerValue(value=value, provenance=AnswerProvenance.PROFILE_VERIFIED)

        adjusted: list[FormField] = []
        suggestions: dict[str, str] = {}
        for form_field in spec.fields:
            if not form_field.options and form_field.question_key in _SALARY_KEYS:
                form_field = _salary_field(form_field, merged, suggestions)
            if form_field.options and form_field.question_key:
                constrained = option_key(form_field.question_key, form_field.options)
                base = merged.get(form_field.question_key)
                if constrained in merged:
                    form_field = dataclasses.replace(form_field, question_key=constrained)
                elif not _answer_fits(base, form_field.options):
                    resolved = (
                        resolve_option(base.value, form_field.options)
                        if base is not None and form_field.kind is not FieldKind.CHECKBOX
                        else None
                    )
                    if base is not None and resolved is not None:
                        # The stored answer names exactly one offered choice ("India" for
                        # "India +91"): send that choice, with the answer's provenance.
                        private = f"_resolved:{form_field.name}"
                        merged[private] = dataclasses.replace(base, value=resolved, alternatives=())
                        form_field = dataclasses.replace(form_field, question_key=private)
                    else:
                        form_field = dataclasses.replace(form_field, question_key=constrained)
            adjusted.append(form_field)
        spec = dataclasses.replace(spec, fields=tuple(adjusted))
        job_key = self._job_key(job)
        if job_key in self._open:
            self._open[job_key].spec = spec

        filled = fill_form(spec, merged)
        filled.questions = _pending_questions(spec, filled, merged, suggestions)
        return filled

    def attach_resume(self, job: Job, document: ResumeDocument) -> Attachment:
        spec = self.inspect_application(job)
        if not spec.accepts_resume:
            # The form has no resume upload; there is nothing to attach and nothing missing.
            return Attachment(document=document)
        problem = validate_document(
            document.filename, document.byte_size, max_bytes=MAX_RESUME_BYTES
        )
        if problem:
            return Attachment(reason=problem)
        return Attachment(document=document)

    def submit(
        self,
        job: Job,
        form: FilledForm,
        attachment: Attachment,
        *,
        idempotency_key: str,
    ) -> SubmissionResult:
        """Fill the form, then — as a separate browser step — press Submit.

        The two steps are split so the orchestrator can commit ``submit_requested`` between
        them. A crash during filling is then provably harmless (nothing was sent), while a
        crash once Submit may have been pressed is recorded as an unknown outcome, never
        retried.
        """
        key = self._job_key(job)
        opened = self._open.get(key)
        if opened is None or opened.blocked_reason:
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=opened.blocked_reason if opened else "the form was never opened",
                submitted_url=self._apply_url(job),
                completed_at=utcnow(),
                response_metadata={
                    "failure_category": (opened.blocked_category if opened else "")
                    or FailureCategory.TRANSIENT
                },
            )
        resume_path = self._stage_resume(attachment, idempotency_key)
        prepared = self._call(
            lambda ctx: self._fill_for_submit(job, opened, form, resume_path, idempotency_key)
        )
        if prepared is not None:
            return prepared
        self._checkpoint("form_filled", "every answered field and the resume are on the form")
        self._checkpoint("submit_requested", "about to press Submit")
        result: SubmissionResult = self._call(
            lambda ctx: self._press_submit(job, opened, idempotency_key)
        )
        if result.state is SubmissionState.SUBMISSION_IN_PROGRESS:
            self._checkpoint("submit_clicked", "Submit pressed")
        return result

    def _checkpoint(self, name: str, detail: str) -> None:
        hook = self.checkpoint_hook
        if hook is not None:
            hook(name, detail)

    def preview_fill(
        self, job: Job, form: FilledForm, attachment: Attachment, *, label: str
    ) -> str:
        """Fill the form without submitting and save a screenshot. Used by dry runs."""
        key = self._job_key(job)
        opened = self._open.get(key)
        if opened is None or opened.blocked_reason:
            return ""
        resume_path = self._stage_resume(attachment, label)

        def work(_ctx: BrowserContext) -> str:
            page = opened.page
            try:
                self._fill(page, opened, form, resume_path)
            except dom.FillError as error:
                return f"dry run stopped while filling: {error}"
            shots = self._data_dir / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            os.chmod(shots, 0o700)
            path = shots / f"dry-run-{label}.png"
            page.screenshot(path=str(path), full_page=True)
            os.chmod(path, 0o600)
            return str(path)

        return str(self._call(work))

    def _stage_resume(self, attachment: Attachment, label: str) -> str:
        document = attachment.document
        if document is None or not document.content:
            return ""
        folder = self._data_dir / "uploads" / re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:80]
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        path = folder / re.sub(r"[^A-Za-z0-9_. -]", "_", document.filename or "resume.pdf")
        path.write_bytes(document.content)
        os.chmod(path, 0o600)
        self._staged.append(path)
        return str(path)

    def _retag_if_rerendered(self, page: Page, opened: _OpenForm) -> None:
        """Re-read the form if it was re-drawn since it was inspected.

        Single-page forms (Greenhouse's embed, for one) can rebuild their DOM after load —
        an autofill prompt, a consent banner, a client-side re-render — which drops the
        ``data-jo-field`` tags. The fields are then found again and matched to the ones
        already read by kind, label and position among same-labelled fields, so nothing
        is typed into a field that was not inspected. An unmatched field stops the fill.
        """
        known = [*opened.dom_by_name.values()]
        if opened.resume_field is not None:
            known.append(opened.resume_field)
        if not known or all(page.locator(item.selector).count() for item in known):
            return
        logger.info("form_rerendered_retagging", extra={"target": self.target.key})

        def key_counts(fields: list[dom.DomField]) -> dict[int, tuple[str, str, int]]:
            seen: dict[tuple[str, str], int] = {}
            keys: dict[int, tuple[str, str, int]] = {}
            for item in sorted(fields, key=lambda field: field.index):
                base = (item.kind, item.label.strip().casefold())
                seen[base] = seen.get(base, 0) + 1
                keys[item.index] = (*base, seen[base])
            return keys

        old_keys = key_counts(known)
        fresh = dom.discover_fields(page)
        fresh_keys = key_counts(fresh)
        by_key = {fresh_keys[item.index]: item for item in fresh}
        remapped: dict[str, dom.DomField] = {}
        for name, item in opened.dom_by_name.items():
            match = by_key.get(old_keys[item.index])
            if match is None:
                raise dom.FillError(f"field {item.label or name} changed after the form was read")
            remapped[name] = dataclasses.replace(match, options=item.options or match.options)
        opened.dom_by_name = remapped
        if opened.resume_field is not None:
            match = by_key.get(old_keys[opened.resume_field.index])
            if match is None:
                raise dom.FillError("the resume upload changed after the form was read")
            opened.resume_field = match

    def _fill(self, page: Page, opened: _OpenForm, form: FilledForm, resume_path: str) -> None:
        self._retag_if_rerendered(page, opened)
        if opened.resume_field is not None:
            if not resume_path:
                raise dom.FillError("the form wants a resume and none is on file")
            dom.upload_file(page, opened.resume_field, resume_path)
            self._pacing.pause()
            # Attaching a file commonly re-renders the form; the upload input itself is
            # often replaced, so it is no longer something to re-find.
            opened.resume_field = None
        for name, value in form.values.items():
            target = self._current(page, opened, name)
            dom.fill_field(page, target, value, self._pacing)
            self._pacing.pause()
        for name, ticked in form.checked.items():
            target = self._current(page, opened, name)
            dom.set_checkbox(page, target, ticked)
            self._pacing.pause(0.5)

    def _current(self, page: Page, opened: _OpenForm, name: str) -> dom.DomField:
        """The field to fill, re-read first if the form was re-rendered since."""
        target = opened.dom_by_name.get(name)
        if target is None:
            raise dom.FillError(f"field {name} is no longer on the page")
        if not page.locator(target.selector).count():
            self._retag_if_rerendered(page, opened)
            target = opened.dom_by_name[name]
        return target

    def _failed(
        self, url: str, reference: str, reason: str, category: str, page: Page | None = None
    ) -> SubmissionResult:
        metadata: dict[str, Any] = {"failure_category": category}
        shot = self._evidence_shot(page, reference, "not-submitted") if page is not None else ""
        if shot:
            metadata["screenshot"] = shot
        return SubmissionResult(
            state=SubmissionState.FAILED,
            reason=reason,
            completed_at=utcnow(),
            submitted_url=url,
            provider_reference=reference,
            response_metadata=metadata,
        )

    def _fill_for_submit(
        self, job: Job, opened: _OpenForm, form: FilledForm, resume_path: str, key: str
    ) -> SubmissionResult | None:
        """Fill everything and check the page is still right. ``None`` means ready to submit."""
        page = opened.page
        url, reference = opened.url, key
        if page.is_closed():
            return self._failed(
                url, reference, "the form tab was closed", FailureCategory.TRANSIENT
            )
        problem = dom.identity_problem(page, title=job.title or "", company=job.company or "")
        if problem:
            return self._failed(
                url, reference, f"not submitted: {problem}", FailureCategory.WRONG_PAGE, page
            )
        try:
            self._fill(page, opened, form, resume_path)
        except dom.FillError as error:
            text = str(error)
            category = (
                FailureCategory.UPLOAD_FAILED
                if "upload" in text.casefold() or "resume" in text.casefold()
                else FailureCategory.FORM_CHANGED
            )
            return self._failed(url, reference, f"not submitted: {text}", category, page)
        except Exception as error:  # noqa: BLE001 - nothing has been sent yet
            category = (
                FailureCategory.TIMEOUT
                if "timeout" in str(error).casefold()
                else FailureCategory.TRANSIENT
            )
            return self._failed(
                url, reference, f"not submitted: filling the form failed ({error})", category, page
            )
        # Checked again after filling: an unexpected navigation while typing would
        # otherwise leave Submit pressed on whatever page is now open.
        problem = dom.identity_problem(page, title=job.title or "", company=job.company or "")
        if problem:
            return self._failed(
                url, reference, f"not submitted: {problem}", FailureCategory.WRONG_PAGE, page
            )
        challenge = dom.visible_challenge(page)
        prompt = "" if challenge else dom.verification_prompt(page)
        if challenge or prompt:
            what = f"a {challenge}" if challenge else f"a verification-code prompt ({prompt})"
            return SubmissionResult(
                state=SubmissionState.REQUIRES_USER_ACTION,
                reason=(
                    f"the form is filled but {what} is showing. Finish it in JobOrbit's "
                    "Chrome window and press Submit yourself, then record it in the tracker."
                ),
                completed_at=utcnow(),
                submitted_url=url,
                provider_reference=reference,
                response_metadata={
                    "failure_category": FailureCategory.CAPTCHA
                    if challenge
                    else FailureCategory.MFA
                },
            )
        if dom.submit_button(page) is None:
            return self._failed(
                url,
                reference,
                "not submitted: the form has no visible Submit button",
                FailureCategory.FORM_CHANGED,
                page,
            )
        opened.extra["before_url"] = page.url
        opened.extra["before_phrases"] = sorted(dom.present_phrases(dom.page_text(page)))
        return None

    def _press_submit(self, job: Job, opened: _OpenForm, key: str) -> SubmissionResult:
        page = opened.page
        url, reference = opened.url, key
        button = dom.submit_button(page) if not page.is_closed() else None
        if button is None:
            # Re-read after the checkpoint: the page changed between the two steps.
            return self._failed(
                url,
                reference,
                "not submitted: the Submit button disappeared before it was pressed",
                FailureCategory.FORM_CHANGED,
            )
        self._pacing.pause(1.5)
        try:
            button.click()
        except Exception as error:  # noqa: BLE001 - the click may or may not have landed
            return SubmissionResult(
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason=f"Submit was pressed but the page errored ({error}); check the open tab",
                completed_at=utcnow(),
                submitted_url=url,
                provider_reference=reference,
                response_metadata={"failure_category": FailureCategory.UNKNOWN_OUTCOME},
            )
        return SubmissionResult(
            state=SubmissionState.SUBMISSION_IN_PROGRESS,
            reason="Submit pressed; reading the employer's response",
            response_metadata={
                "before_url": str(opened.extra.get("before_url") or url),
                "before_phrases": list(opened.extra.get("before_phrases") or []),
                "job_key": self._job_key(job),
            },
            submitted_url=url,
            provider_reference=reference,
        )

    def _evidence_shot(self, page: Page | None, reference: str, outcome: str) -> str:
        """Save an owner-only screenshot of the page as evidence, returning its path.

        The image may show the user's name, email and answers, so it is written with mode
        0600 into the private data directory, never served by URL, and deleted by the
        retention cleanup. No password is ever on the page: a form with a password field
        is refused before anything is typed.
        """
        if page is None or not self._evidence_screenshots or page.is_closed():
            return ""
        folder = self._data_dir / "screenshots"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.chmod(folder, 0o700)
            stamp = utcnow().strftime("%Y%m%dT%H%M%S")
            name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{self.target.key}-{reference[-12:]}")
            path = folder / f"{name}-{outcome}-{stamp}.png"
            page.screenshot(path=str(path), full_page=True)
            os.chmod(path, 0o600)
            return str(path)
        except Exception:  # noqa: BLE001 - missing evidence must not change the outcome
            logger.warning("evidence_screenshot_failed", extra={"target": self.target.key})
            return ""

    def verify_submission(self, result: SubmissionResult) -> SubmissionResult:
        job_key = result.response_metadata.get("job_key")
        opened = self._open.get(int(job_key)) if isinstance(job_key, int) else None
        if opened is None:
            return dataclasses.replace(
                result,
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason="Submit was pressed but the tab was lost before the outcome was read",
                completed_at=utcnow(),
            )
        before_url = str(result.response_metadata.get("before_url") or "")
        raw_phrases = result.response_metadata.get("before_phrases")
        before_phrases = (
            {str(item) for item in raw_phrases} if isinstance(raw_phrases, list) else set()
        )
        timeout = self._confirmation_timeout_s

        def work(_ctx: BrowserContext) -> SubmissionResult:
            page = opened.page
            deadline = time.monotonic() + timeout
            stable_errors = 0
            while time.monotonic() < deadline:
                if page.is_closed():
                    break
                evidence = dom.looks_confirmed(before_url, before_phrases, page)
                if evidence:
                    digest = hashlib.sha256(
                        f"{page.url}|{evidence}|{time.time()}".encode()
                    ).hexdigest()
                    return finish(
                        state=SubmissionState.SUBMITTED_CONFIRMED,
                        reason=f"{self.target.display_name} acknowledged the application: {evidence}",
                        confirmation_id=f"{self.target.key}-{digest[:16]}",
                        submitted_url=page.url,
                        metadata={"evidence": evidence, "final_url": page.url},
                        shot="confirmed",
                    )
                challenge = dom.visible_challenge(page)
                prompt = "" if challenge else dom.verification_prompt(page)
                if challenge or prompt:
                    what = (
                        f"A {challenge}" if challenge else f"A verification-code prompt ({prompt})"
                    )
                    return finish(
                        state=SubmissionState.REQUIRES_USER_ACTION,
                        reason=(
                            f"{what} appeared after Submit. Complete it in JobOrbit's Chrome "
                            "window (the tab is left open); the employer may then accept the "
                            "application. Record the outcome in the tracker."
                        ),
                        metadata={
                            "failure_category": FailureCategory.CAPTCHA
                            if challenge
                            else FailureCategory.MFA
                        },
                        shot="needs-you",
                    )
                errors = dom.page_errors(page)
                if errors and dom.submit_button(page) is not None:
                    stable_errors += 1
                    if stable_errors >= 3:
                        return finish(
                            state=SubmissionState.FAILED,
                            reason="the employer's form rejected the submission: "
                            + "; ".join(errors[:4]),
                            metadata={
                                "failure_category": FailureCategory.VALIDATION_REJECTED,
                                "form_errors": errors[:8],
                            },
                            shot="rejected",
                        )
                else:
                    stable_errors = 0
                page.wait_for_timeout(1000)
            return finish(
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason=(
                    "Submit was pressed but no confirmation appeared. The tab is left open in "
                    "JobOrbit's Chrome window; check it and record the outcome yourself."
                ),
                metadata={"failure_category": FailureCategory.UNKNOWN_OUTCOME},
                shot="unknown",
            )

        def finish(
            *,
            state: SubmissionState,
            reason: str,
            metadata: dict[str, Any],
            shot: str,
            confirmation_id: str = "",
            submitted_url: str = "",
        ) -> SubmissionResult:
            merged = {**result.response_metadata, **metadata}
            path = self._evidence_shot(opened.page, result.provider_reference or "attempt", shot)
            if path:
                merged["screenshot"] = path
            return dataclasses.replace(
                result,
                state=state,
                reason=reason,
                confirmation_id=confirmation_id,
                submitted_url=submitted_url or result.submitted_url,
                response_metadata=merged,
                completed_at=utcnow(),
            )

        try:
            return self._call(work)
        except Exception as error:  # noqa: BLE001 - Submit was pressed; the outcome is unread
            return dataclasses.replace(
                result,
                state=SubmissionState.OUTCOME_UNKNOWN,
                reason=(
                    f"Submit was pressed but the browser failed while reading the outcome "
                    f"({type(error).__name__}). Check the employer's page or your email before "
                    "trying again."
                ),
                response_metadata={
                    **result.response_metadata,
                    "failure_category": FailureCategory.UNKNOWN_OUTCOME,
                },
                completed_at=utcnow(),
            )

    def recheck(self, job: Job, before_url: str = "") -> str:
        """Look again at a tab left open after an unclear outcome. Returns evidence or ''."""
        key = self._job_key(job)
        opened = self._open.get(key) or _KEPT_OPEN.get((self.target.key, key))
        if opened is None:
            return ""

        def work(_ctx: BrowserContext) -> str:
            if opened.page.is_closed():
                return ""
            return dom.looks_confirmed(before_url or opened.url, set(), opened.page)

        try:
            return str(self._call(work) or "")
        except Exception:  # noqa: BLE001
            return ""

    def release(self, job: Job, *, keep_open: bool) -> None:
        """Close the job's tab unless the user still needs it.

        A tab kept open is remembered process-wide, because adapters are built per lookup
        and a later :meth:`recheck` comes from a different instance.
        """
        key = self._job_key(job)
        for staged in self._staged:
            try:
                staged.unlink(missing_ok=True)
                staged.parent.rmdir()
            except OSError:
                pass
        self._staged.clear()
        opened = self._open.pop(key, None)
        if opened is None:
            return
        if keep_open:
            _KEPT_OPEN[(self.target.key, key)] = opened
            return

        def work(_ctx: BrowserContext) -> None:
            if not opened.page.is_closed():
                opened.page.close()

        try:
            self._call(work)
        except Exception:  # noqa: BLE001 - a tab that will not close is harmless
            logger.warning("browser_tab_close_failed", extra={"target": self.target.key})


def _answer_fits(answer: AnswerValue | None, options: tuple[str, ...]) -> bool:
    if answer is None or not answer.value.strip():
        return True  # nothing to compare; the missing answer is reported as missing
    folded = {option.casefold().strip() for option in options}
    candidates = [answer.value, *answer.alternatives]
    for candidate in candidates:
        parts = [part.strip().casefold() for part in candidate.split(";") if part.strip()]
        if parts and all(part in folded for part in parts):
            return True
    return False


_SALARY_KEYS = frozenset({"salary_expectation", "current_salary"})
_UNIT_MEANING: dict[str, tuple[str, str]] = {
    "lpa": ("INR", "annual"),
    "inr_annual": ("INR", "annual"),
    "inr_monthly": ("INR", "monthly"),
    "usd_annual": ("USD", "annual"),
}


def _salary_field(
    form_field: FormField, merged: dict[str, AnswerValue], suggestions: dict[str, str]
) -> FormField:
    """Route a salary question to an answer in the unit the form asks for.

    "Expected CTC (in LPA)" and "Expected salary per month (INR)" want different numbers
    for the same expectation. A saved answer is typed only when it is already in the
    asked unit, exactly; anything that would need converting is proposed to the user
    instead, with the arithmetic shown, and their answer is kept under a unit-specific
    key so the next form asking in that unit is filled from it. Current and expected pay
    are separate keys throughout and never stand in for each other.
    """
    from app.services.salary import detect_question_unit, format_for_unit, parse_compensation

    unit = detect_question_unit(form_field.label)
    if unit is None:
        return form_field
    unit_key = f"{form_field.question_key}@{unit}"
    if unit_key in merged and (merged[unit_key].value or "").strip():
        return dataclasses.replace(form_field, question_key=unit_key)
    base = merged.get(form_field.question_key)
    if base is None or not (base.value or "").strip():
        return dataclasses.replace(form_field, question_key=unit_key)
    compensation = parse_compensation(base.value)
    currency, period = _UNIT_MEANING[unit]
    same_quantity = (
        compensation.disclosed
        and compensation.currency == currency
        and compensation.period == period
        and compensation.period_stated
        and (compensation.currency_stated or compensation.scale in ("lakh", "crore"))
    )
    if same_quantity and form_field.kind is not FieldKind.NUMBER:
        # A free-text box: the user's own words already state this quantity in this unit.
        merged[unit_key] = dataclasses.replace(base, alternatives=())
        return dataclasses.replace(form_field, question_key=unit_key)
    conversion = format_for_unit(compensation, unit)
    if conversion.exact and conversion.value:
        merged[unit_key] = dataclasses.replace(base, value=conversion.value, alternatives=())
        return dataclasses.replace(form_field, question_key=unit_key)
    if conversion.value:
        suggestions[unit_key] = (
            f"Suggested from your saved answer '{base.value}': {conversion.value} "
            f"({'; '.join(conversion.assumptions)}). Confirm it or enter your own figure."
        )
    else:
        suggestions[unit_key] = (
            f"Your saved answer '{base.value}' cannot be expressed in this unit without "
            f"guessing ({'; '.join(conversion.assumptions) or 'no conversion available'})."
        )
    return dataclasses.replace(form_field, question_key=unit_key)


def _pending_questions(
    spec: FormSpec,
    filled: FilledForm,
    answers: dict[str, AnswerValue],
    suggestions: dict[str, str] | None = None,
) -> list[PendingQuestion]:
    """The required questions this form could not fill, phrased for the Action inbox."""
    pending: list[PendingQuestion] = []
    seen: set[str] = set()
    for form_field in spec.fields:
        if not form_field.required or not form_field.question_key:
            continue
        if form_field.name in filled.values or form_field.name in filled.checked:
            continue
        if form_field.question_key in _IDENTITY_KEYS:
            continue  # reported by validate_candidate, answered on the profile page
        if form_field.question_key in seen:
            continue
        seen.add(form_field.question_key)
        question = form_field.label
        if form_field.options:
            shown = list(form_field.options[:15])
            more = len(form_field.options) - len(shown)
            listing = " / ".join(shown) + (f" / … and {more} more" if more > 0 else "")
            question = f"{question} (choose one of: {listing})"
            if form_field.kind is FieldKind.CHECKBOX:
                question = question.replace("choose one of", "choose any of, separated by ;")
        elif form_field.kind is FieldKind.CHECKBOX:
            question = f"{question} (answer Yes to tick this box, No to leave it)"
        note = (suggestions or {}).get(form_field.question_key)
        if note:
            question = f"{question} — {note}"
        pending.append(
            PendingQuestion(
                question_key=form_field.question_key,
                question=question[:1000],
                sensitive=form_field.is_sensitive(),
            )
        )
    return pending


__all__ = [
    "BrowserFormAdapter",
    "ashby_apply_url",
    "greenhouse_apply_url",
    "lever_apply_url",
]
