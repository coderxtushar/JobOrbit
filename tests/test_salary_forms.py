"""Salary questions on live forms: the unit the form asks for decides what is typed.

A saved "12 LPA" is the user's own statement. It may be typed into a free-text "Expected
CTC" box as it is, but a number box asking for LPA, a monthly figure or USD gets nothing
until the user approves the converted value, which is then kept for that unit.
"""

from __future__ import annotations

import pytest

from app.db.models import AnswerProvenance
from app.submission.browser_ats import _pending_questions, _salary_field
from app.submission.forms import AnswerValue, FieldKind, FilledForm, FormField, FormSpec


def _field(label: str, key: str = "salary_expectation", kind: FieldKind = FieldKind.TEXT):
    return FormField(name="f1", label=label, question_key=key, kind=kind, required=True)


def _saved(value: str, key: str = "salary_expectation") -> dict[str, AnswerValue]:
    return {key: AnswerValue(value=value, provenance=AnswerProvenance.USER_ENTERED)}


@pytest.mark.parametrize(
    ("label", "saved", "kind", "typed"),
    [
        ("Expected CTC", "12 LPA", FieldKind.TEXT, "12 LPA"),
        ("Expected CTC (in LPA)", "12 LPA", FieldKind.NUMBER, "12"),
        ("Salary expectations", "12 LPA", FieldKind.TEXT, "12 LPA"),
    ],
)
def test_a_saved_answer_already_in_the_asked_unit_is_typed(label, saved, kind, typed) -> None:
    merged = _saved(saved)
    field = _salary_field(_field(label, kind=kind), merged, {})
    assert merged[field.question_key].value == typed


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Expected CTC", FieldKind.NUMBER),
        ("Expected monthly salary (INR)", FieldKind.TEXT),
        ("Expected salary (USD)", FieldKind.TEXT),
    ],
)
def test_a_conversion_is_proposed_never_typed(label, kind) -> None:
    merged, notes = _saved("12 LPA"), {}
    field = _salary_field(_field(label, kind=kind), merged, notes)
    assert field.question_key.startswith("salary_expectation@")
    assert field.question_key not in merged, "a converted salary was typed without approval"
    assert "12 LPA" in notes[field.question_key]

    pending = _pending_questions(FormSpec(fields=(field,)), FilledForm(), merged, notes)
    assert len(pending) == 1 and "12 LPA" in pending[0].question


def test_usd_without_a_rate_is_not_converted() -> None:
    notes: dict[str, str] = {}
    field = _salary_field(_field("Expected salary (USD)"), _saved("12 LPA"), notes)
    assert "without guessing" in notes[field.question_key] or "rate" in notes[field.question_key]


def test_an_approved_value_for_the_unit_is_used_on_the_next_form() -> None:
    merged = _saved("12 LPA")
    merged["salary_expectation@inr_monthly"] = AnswerValue(
        value="100000", provenance=AnswerProvenance.USER_ENTERED
    )
    field = _salary_field(_field("Expected monthly salary (INR)"), merged, {})
    assert merged[field.question_key].value == "100000"


def test_current_salary_is_never_filled_from_the_expectation() -> None:
    merged = _saved("12 LPA")  # only an *expected* salary is on file
    field = _salary_field(_field("What is your current CTC?", key="current_salary"), merged, {})
    assert field.question_key.startswith("current_salary")
    assert field.question_key not in merged
