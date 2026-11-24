"""Submission adapter contract.

One adapter per *submission provider*. A provider is whoever actually receives the
application — which is not the same thing as the source the listing was discovered from.
A role found in a job-alert email may be submitted through Greenhouse; a role found on
LinkedIn may only be submitted by the user in their own browser. So adapters here are
keyed by :class:`SubmissionTarget`, independently of :class:`~app.db.models.SourceName`.

The contract is seven operations, run in order:

``check_capability``
    Is there an authorized candidate-side submission interface at all? Everything else is
    pointless if this says no, and an adapter that says no must say *why*, with a citation.
``inspect_application``
    What does the form actually ask for? Returns a :class:`~app.submission.forms.FormSpec`,
    or a spec carrying ``human_required_reason`` when a CAPTCHA, MFA challenge or sign-in
    wall means no program may proceed.
``validate_candidate``
    Does the profile hold what this provider requires of any applicant (a name, a
    reachable email)? Returns the problems, so they are reported together rather than one
    per attempt.
``prepare_fields``
    Map verified answers onto the form. Never invents a value.
``attach_resume``
    Validate and stage the document. Format and size are checked before dispatch so a
    rejected file is a validation failure, not a half-made application.
``submit``
    Dispatch. Returns ``SUBMISSION_IN_PROGRESS``, ``FAILED`` or ``OUTCOME_UNKNOWN``;
    it never returns ``SUBMITTED_CONFIRMED`` on its own.
``verify_submission``
    Ask the provider whether the application exists. Only this step may return
    ``SUBMITTED_CONFIRMED``, and only on a reliable acknowledgement.

Splitting ``submit`` from ``verify_submission`` is what stops a 200 response being treated
as proof. A provider that accepts the request but silently drops it produces
``OUTCOME_UNKNOWN`` here, which is reported to the user as something to check rather than
counted as an application sent.

**Who can be submitted to.** With ``JA_BROWSER_SUBMISSION_ENABLED`` the Greenhouse,
Lever and Ashby providers use :mod:`app.submission.browser_ats`, which fills the
employer's own hosted form in JobOrbit's Chrome window. Every other platform returns
``submission_not_supported`` with its policy or credential reason. The local test server
adapter submits end to end against a server this project runs itself, which is what makes
the framework verifiable without applying to anybody's job on a test run.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.db.models import CandidateProfile, Job, utcnow
from app.submission.forms import AnswerValue, FilledForm, FormSpec, fill_form, validate_document
from app.submission.states import SubmissionState

#: Largest document this project will ever upload. Well under every provider's own limit;
#: the point is to fail locally with a clear message rather than mid-dispatch.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class CredentialOwner(str, enum.Enum):
    """Who a provider issues submission credentials to.

    This is the field that decides most of the feasibility matrix. An endpoint can be
    public, documented and perfectly functional and still be unusable here, because the
    key it needs is issued to the *employer* who owns the job board — not to the
    candidate applying.
    """

    #: No credential needed; the interface is open to any applicant.
    NONE = "none"
    #: The candidate signs in themselves and the session belongs to them.
    CANDIDATE = "candidate"
    #: Issued to the hiring company. A jobseeker cannot obtain one.
    EMPLOYER = "employer"
    #: Issued to approved ATS/vendor partners under a commercial agreement.
    APPROVED_VENDOR = "approved_vendor"
    #: No credential model is documented, so none can be relied on.
    UNDOCUMENTED = "undocumented"


@dataclass(frozen=True, slots=True)
class SubmissionTarget:
    """Identifies a submission provider."""

    key: str
    display_name: str


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """What a provider permits, and the evidence for it.

    Every field here appears in ``docs/SUBMISSION_FEASIBILITY.md``. ``evidence_url`` being
    empty is itself information: it means no authoritative statement was found, which is
    recorded as such rather than resolved by assumption.
    """

    supported: bool
    reason: str
    credential_owner: CredentialOwner = CredentialOwner.UNDOCUMENTED
    documented_api: bool = False
    browser_submission_permitted: bool = False
    manual_completion_required: bool = True
    accepts_resume_upload: bool = False
    evidence_url: str = ""
    evidence_quote: str = ""


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """The applicant facts any form needs, detached from the ORM.

    Adapters take this rather than a :class:`CandidateProfile` so a provider integration
    can be tested without a database session.
    """

    full_name: str = ""
    email: str = ""
    phone: str = ""
    #: Profile links (LinkedIn, GitHub, portfolio) exactly as the user recorded them.
    links: tuple[str, ...] = ()

    @classmethod
    def from_profile(cls, profile: CandidateProfile) -> CandidateIdentity:
        return cls(
            full_name=(profile.full_name or "").strip(),
            email=(profile.email or "").strip(),
            phone=(profile.phone or "").strip(),
            links=tuple(str(link).strip() for link in (profile.links or []) if str(link).strip()),
        )


@dataclass(frozen=True, slots=True)
class ResumeDocument:
    """A resume as it will be uploaded, with the hash recorded against the attempt."""

    filename: str
    content: bytes
    content_sha256: str = ""

    @property
    def byte_size(self) -> int:
        return len(self.content)


@dataclass(slots=True)
class Attachment:
    """The outcome of staging a document for upload."""

    document: ResumeDocument | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.document is not None and not self.reason


@dataclass(slots=True)
class SubmissionResult:
    """The outcome of one attempt, and the evidence for whatever it claims.

    ``confirmation_id`` is only ever set by :meth:`SubmissionAdapter.verify_submission`,
    and :func:`~app.submission.states.counts_as_sent` is the only thing that decides
    whether this counts as an application the user actually sent.
    """

    state: SubmissionState
    reason: str = ""
    confirmation_id: str = ""
    submitted_url: str = ""
    resume_sha256: str = ""
    response_metadata: dict[str, object] = field(default_factory=dict)
    attempted_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None
    #: Opaque handle the provider gave back, used by ``verify_submission`` to look the
    #: attempt up. Not a confirmation: having a handle does not mean the form was accepted.
    provider_reference: str = ""

    @property
    def is_confirmed(self) -> bool:
        return self.state is SubmissionState.SUBMITTED_CONFIRMED


class SubmissionAdapter(ABC):
    """Base class for every submission provider."""

    target: SubmissionTarget

    @abstractmethod
    def check_capability(self, job: Job) -> CapabilityReport:
        """Whether this provider permits a candidate to submit programmatically."""

    @abstractmethod
    def inspect_application(self, job: Job) -> FormSpec:
        """Read the provider's form. May return a spec with ``human_required_reason``."""

    def validate_candidate(self, job: Job, identity: CandidateIdentity) -> list[str]:
        """Return the problems that would stop any application to this provider.

        The default covers what every real form asks for. A provider needing more
        overrides this and calls ``super()``.
        """
        problems: list[str] = []
        if not identity.full_name:
            problems.append("your profile has no name on it")
        if "@" not in identity.email:
            problems.append("your profile has no usable email address")
        return problems

    def prepare_fields(
        self, job: Job, identity: CandidateIdentity, answers: dict[str, AnswerValue]
    ) -> FilledForm:
        """Map verified answers onto this provider's form.

        Identity fields are supplied from the profile under their conventional keys, then
        the shared :func:`~app.submission.forms.fill_form` applies the provenance rules.
        """
        spec = self.inspect_application(job)
        merged: dict[str, AnswerValue] = dict(answers)
        merged.setdefault("full_name", _verified(identity.full_name))
        merged.setdefault("email", _verified(identity.email))
        merged.setdefault("phone", _verified(identity.phone))
        return fill_form(spec, merged)

    def attach_resume(self, job: Job, document: ResumeDocument) -> Attachment:
        """Validate a document against format and size limits before any dispatch."""
        spec = self.inspect_application(job)
        if not spec.accepts_resume:
            return Attachment(reason=f"{self.target.display_name} accepts no resume upload")
        problem = validate_document(
            document.filename, document.byte_size, max_bytes=MAX_DOCUMENT_BYTES
        )
        if problem:
            return Attachment(reason=problem)
        return Attachment(document=document)

    @abstractmethod
    def submit(
        self,
        job: Job,
        form: FilledForm,
        attachment: Attachment,
        *,
        idempotency_key: str,
    ) -> SubmissionResult:
        """Dispatch the application.

        Must never return :attr:`SubmissionState.SUBMITTED_CONFIRMED`; confirming is
        :meth:`verify_submission`'s job. ``idempotency_key`` is passed to the provider
        where it supports one, so a retry after a lost response cannot create a second
        application.
        """

    @abstractmethod
    def verify_submission(self, result: SubmissionResult) -> SubmissionResult:
        """Ask the provider whether the application exists, and say so only if it does."""


def _verified(value: str) -> AnswerValue:
    from app.db.models import AnswerProvenance

    return AnswerValue(value=value, provenance=AnswerProvenance.PROFILE_VERIFIED)


class UnsupportedSubmissionAdapter(SubmissionAdapter):
    """A provider with no authorized candidate submission interface.

    Every real job platform in this build uses this class. It reports the reason verbatim
    at each step instead of raising, so the orchestrator can record one attempt as
    ``UNSUPPORTED_PLATFORM`` and carry on with the rest of the batch rather than aborting.
    """

    def __init__(
        self,
        target: SubmissionTarget,
        *,
        reason: str,
        credential_owner: CredentialOwner,
        documented_api: bool = False,
        evidence_url: str = "",
        evidence_quote: str = "",
        open_in_browser: bool = True,
    ) -> None:
        self.target = target
        self._reason = reason
        self._credential_owner = credential_owner
        self._documented_api = documented_api
        self._evidence_url = evidence_url
        self._evidence_quote = evidence_quote
        self._open_in_browser = open_in_browser

    def check_capability(self, job: Job) -> CapabilityReport:
        return CapabilityReport(
            supported=False,
            reason=self._reason,
            credential_owner=self._credential_owner,
            documented_api=self._documented_api,
            browser_submission_permitted=False,
            manual_completion_required=True,
            accepts_resume_upload=False,
            evidence_url=self._evidence_url,
            evidence_quote=self._evidence_quote,
        )

    @property
    def offers_open_in_platform(self) -> bool:
        """Whether the user can be sent to the employer's own page to finish by hand.

        True for every real platform: the compliant alternative to automated submission is
        the application prepared for the user and the official page opened for them.
        """
        return self._open_in_browser

    def inspect_application(self, job: Job) -> FormSpec:
        return FormSpec(human_required_reason=self._reason)

    def validate_candidate(self, job: Job, identity: CandidateIdentity) -> list[str]:
        return [self._reason]

    def submit(
        self,
        job: Job,
        form: FilledForm,
        attachment: Attachment,
        *,
        idempotency_key: str,
    ) -> SubmissionResult:
        return SubmissionResult(
            state=SubmissionState.UNSUPPORTED_PLATFORM,
            reason=self._reason,
            submitted_url=job.url or "",
            completed_at=utcnow(),
        )

    def verify_submission(self, result: SubmissionResult) -> SubmissionResult:
        return result
