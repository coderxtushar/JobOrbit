"""Submission framework.

One adapter per provider that could receive an application. Every real job platform
reports that it cannot, with the policy or credential reason; the only adapter that
submits targets a loopback test server this project runs itself.
"""

from __future__ import annotations

from app.submission.base import (
    Attachment,
    CandidateIdentity,
    CapabilityReport,
    CredentialOwner,
    ResumeDocument,
    SubmissionAdapter,
    SubmissionResult,
    SubmissionTarget,
    UnsupportedSubmissionAdapter,
)
from app.submission.forms import (
    AnswerValue,
    FieldKind,
    FilledForm,
    FormField,
    FormSpec,
    fill_form,
    validate_document,
)
from app.submission.registry import (
    adapter_for_job,
    all_submission_adapters,
    get_submission_adapter,
    supported_targets,
    target_for_job,
    target_for_url,
)
from app.submission.states import (
    NEEDS_USER_STATES,
    RETRYABLE_STATES,
    TERMINAL_STATES,
    SubmissionState,
    counts_as_sent,
    is_terminal,
)

__all__ = [
    "NEEDS_USER_STATES",
    "RETRYABLE_STATES",
    "TERMINAL_STATES",
    "AnswerValue",
    "Attachment",
    "CandidateIdentity",
    "CapabilityReport",
    "CredentialOwner",
    "FieldKind",
    "FilledForm",
    "FormField",
    "FormSpec",
    "ResumeDocument",
    "SubmissionAdapter",
    "SubmissionResult",
    "SubmissionState",
    "SubmissionTarget",
    "UnsupportedSubmissionAdapter",
    "adapter_for_job",
    "all_submission_adapters",
    "counts_as_sent",
    "fill_form",
    "get_submission_adapter",
    "is_terminal",
    "supported_targets",
    "target_for_job",
    "target_for_url",
    "validate_document",
]
