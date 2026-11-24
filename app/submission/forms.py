"""Application form model, and the mapping from verified answers onto a form.

A provider describes its form as a :class:`FormSpec`. :func:`fill_form` maps the
application's stored answers onto it and returns either a complete :class:`FilledForm` or
the list of reasons it cannot be completed. Nothing in this module invents a value: an
answer either exists with acceptable provenance, or the field is reported unfilled.

Three rules decide whether a field may be filled, and all three exist because the
alternative is a lie sent to an employer under the candidate's name:

1. **A sensitive field needs human-verified provenance.** Work authorization, sponsorship,
   salary, notice period, education and every legal attestation may be filled only from
   ``profile_verified`` or ``user_entered`` data. An ``ai_draft`` is refused outright.
2. **A constrained field must match an offered option.** If the stored answer is not one
   of a select's or radio's choices, the field is reported ambiguous rather than coerced
   to the nearest option.
3. **A checkbox is never ticked on the candidate's behalf** unless they supplied that
   exact answer. Consent and attestation boxes are the ones that carry legal weight.

A field that fails any rule blocks *its own* application and nothing else — the caller
records ``BLOCKED_MISSING_INFO`` for that job and moves to the next one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from app.db.models import AnswerProvenance
from app.services.questions import SENSITIVE_KEYS


class FieldKind(str, enum.Enum):
    """Input types a real application form uses."""

    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    URL = "url"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    FILE = "file"


#: Provenances acceptable for a sensitive field. ``RESUME_EXTRACTED`` is absent on purpose:
#: a heuristic parser's reading of a PDF is not the candidate attesting to a legal fact.
_VERIFIED_PROVENANCE: frozenset[AnswerProvenance] = frozenset(
    {AnswerProvenance.PROFILE_VERIFIED, AnswerProvenance.USER_ENTERED}
)

#: Document formats a form may legitimately ask for. Checked before an upload is attempted
#: so a rejected format is reported as a validation failure rather than a submission one.
ALLOWED_DOCUMENT_SUFFIXES: frozenset[str] = frozenset({".pdf", ".doc", ".docx", ".txt", ".rtf"})


@dataclass(frozen=True, slots=True)
class FormField:
    """One input on a provider's application form."""

    name: str
    label: str
    kind: FieldKind = FieldKind.TEXT
    required: bool = False
    #: Permitted values for ``SELECT`` and ``RADIO``. Empty for free-text fields.
    options: tuple[str, ...] = ()
    #: Answer-bank key this field maps to, when the provider's field is a known question.
    question_key: str = ""
    #: Field whose truthiness makes this one required. Models "if yes, explain" branches.
    required_when: str = ""
    max_length: int = 0
    #: Marks a field as carrying legal or eligibility weight even if its key is not in
    #: :data:`SENSITIVE_KEYS` — a provider may word an attestation in any number of ways.
    sensitive: bool = False

    def is_sensitive(self) -> bool:
        return self.sensitive or self.question_key in SENSITIVE_KEYS


@dataclass(frozen=True, slots=True)
class FormSpec:
    """The complete form a provider expects, as discovered by ``inspect_application``."""

    fields: tuple[FormField, ...] = ()
    #: Whether the provider accepts a resume file upload.
    accepts_resume: bool = False
    #: Whether the provider accepts cover-letter text or a cover-letter file.
    accepts_cover_letter: bool = False
    #: Reported by the provider when its form cannot be read without a human — a CAPTCHA,
    #: an MFA challenge, or a sign-in wall. Non-empty means do not attempt submission.
    human_required_reason: str = ""

    def required_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.required)


@dataclass(frozen=True, slots=True)
class AnswerValue:
    """A stored answer, with the provenance that decides whether it may be used."""

    value: str
    provenance: AnswerProvenance = AnswerProvenance.NEEDS_USER_INPUT
    requires_user_input: bool = False
    #: Other answers the user has recorded for this same question. Tried only for a
    #: constrained field whose options :attr:`value` does not match — a profile holding
    #: "Authorised to work in India" and a form offering only "Yes"/"No" is the ordinary
    #: case, and the user's own "Yes" from the answer bank is the right value to send.
    #: Never used to invent anything: every alternative is something the user supplied.
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """A form question the user must answer once, raised into the Action inbox.

    ``question_key`` is what the answer bank stores the reply under, so the same question
    on a later form is filled from that one answer instead of being asked again.
    """

    question_key: str
    question: str
    sensitive: bool = False


@dataclass(slots=True)
class FilledForm:
    """The result of mapping answers onto a form."""

    values: dict[str, str] = field(default_factory=dict)
    checked: dict[str, bool] = field(default_factory=dict)
    #: Human-readable reasons the form cannot be submitted. Empty means ready.
    blocking: list[str] = field(default_factory=list)
    #: Fields left empty that the provider does not require.
    skipped_optional: list[str] = field(default_factory=list)
    #: Questions an adapter wants the user to answer once. Only adapters that read a live
    #: form populate this; the orchestrator raises each into the Action inbox.
    questions: list[PendingQuestion] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.blocking


def _truthy(text: str) -> bool:
    return text.strip().lower() in {"yes", "true", "y", "1", "on", "checked"}


def _option_match(value: str, options: tuple[str, ...]) -> str | None:
    """Return the offered option matching ``value``, comparing case-insensitively.

    Deliberately not fuzzy. "Yes, I am authorised" is not an acceptable stand-in for an
    option literally reading "Yes" unless the provider offers that wording, because the
    submitted value is what the employer reads.
    """
    wanted = value.strip().casefold()
    for option in options:
        if option.strip().casefold() == wanted:
            return option
    return None


def validate_document(filename: str, byte_size: int, *, max_bytes: int) -> str:
    """Return an empty string when the document may be uploaded, else the reason it cannot."""
    lowered = filename.lower()
    suffix = lowered[lowered.rfind(".") :] if "." in lowered else ""
    if suffix not in ALLOWED_DOCUMENT_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENT_SUFFIXES))
        return f"{filename or 'document'} is not an accepted format (accepted: {allowed})"
    if byte_size <= 0:
        return f"{filename} is empty"
    if byte_size > max_bytes:
        return f"{filename} is {byte_size} bytes, over the {max_bytes}-byte limit"
    return ""


def fill_form(spec: FormSpec, answers: dict[str, AnswerValue]) -> FilledForm:
    """Map stored answers onto ``spec``, refusing to guess any value.

    ``answers`` is keyed by :attr:`FormField.question_key` first and :attr:`FormField.name`
    second, so a provider field with no recognised question key can still be satisfied by
    an answer the user entered against that field's own name.
    """
    filled = FilledForm()
    if spec.human_required_reason:
        filled.blocking.append(spec.human_required_reason)
        return filled

    for form_field in spec.fields:
        answer = answers.get(form_field.question_key) or answers.get(form_field.name)
        required = form_field.required or _is_conditionally_required(form_field, spec, filled)

        if answer is None or not answer.value.strip():
            if required:
                filled.blocking.append(f"{form_field.label}: no verified answer is on file")
            else:
                filled.skipped_optional.append(form_field.name)
            continue

        if answer.requires_user_input:
            filled.blocking.append(f"{form_field.label}: waiting on your answer")
            continue

        if form_field.is_sensitive() and answer.provenance not in _VERIFIED_PROVENANCE:
            filled.blocking.append(
                f"{form_field.label}: needs your confirmation, not a generated answer "
                f"(currently {answer.provenance.value})"
            )
            continue

        if form_field.kind is FieldKind.CHECKBOX and form_field.options:
            # A "select all that apply" group. Every chosen option must be one the
            # employer offers; answers are separated with semicolons.
            wanted = [part.strip() for part in answer.value.split(";") if part.strip()]
            matched_all = [_option_match(part, form_field.options) for part in wanted]
            if not wanted or any(item is None for item in matched_all):
                offered = ", ".join(form_field.options)
                filled.blocking.append(
                    f"{form_field.label}: your answer {answer.value!r} is not among the "
                    f"options the employer offers ({offered})"
                )
                continue
            filled.values[form_field.name] = "; ".join(item for item in matched_all if item)
            continue

        if form_field.kind is FieldKind.CHECKBOX:
            if answer.provenance not in _VERIFIED_PROVENANCE:
                filled.blocking.append(
                    f"{form_field.label}: a tick box is only ever set from your own answer"
                )
                continue
            ticked = _truthy(answer.value)
            if required and not ticked:
                filled.blocking.append(f"{form_field.label}: you have not agreed to this")
                continue
            filled.checked[form_field.name] = ticked
            continue

        if form_field.options:
            matched = _option_match(answer.value, form_field.options)
            for candidate in answer.alternatives:
                if matched is not None:
                    break
                matched = _option_match(candidate, form_field.options)
            if matched is None:
                offered = ", ".join(form_field.options)
                filled.blocking.append(
                    f"{form_field.label}: your answer {answer.value!r} is not one of the "
                    f"options the employer offers ({offered})"
                )
                continue
            filled.values[form_field.name] = matched
            continue

        value = answer.value.strip()
        if form_field.max_length and len(value) > form_field.max_length:
            value = value[: form_field.max_length]
        filled.values[form_field.name] = value

    return filled


def _is_conditionally_required(form_field: FormField, spec: FormSpec, filled: FilledForm) -> bool:
    """Whether a ``required_when`` dependency has been satisfied by an earlier field.

    Only fields already processed are consulted, so a spec must list a controlling field
    before the field it controls — which is the order a rendered form presents them in.
    """
    if not form_field.required_when:
        return False
    controller = form_field.required_when
    if controller in filled.checked:
        return filled.checked[controller]
    value = filled.values.get(controller, "")
    if not value:
        return False
    controlling_field = next((f for f in spec.fields if f.name == controller), None)
    if controlling_field is not None and controlling_field.options:
        return _truthy(value)
    return True
