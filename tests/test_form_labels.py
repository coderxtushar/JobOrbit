"""Form-label classification: which stored answer may fill which question.

Each case here is a way a wrong answer could reach an employer under the candidate's
name, so the assertions are about keys never colliding, not about coverage.
"""

from __future__ import annotations

import pytest

from app.browser.labels import classify_label, link_for, option_key, split_name


@pytest.mark.parametrize(
    ("label", "tech"),
    [
        ("How many years of work experience do you have with Java?", "java"),
        ("Years of experience in Python", "python"),
        ("How many years of experience do you have using React?", "react"),
        ("Total years of experience working with AWS", "aws"),
    ],
)
def test_technology_experience_never_uses_total_experience(label: str, tech: str) -> None:
    """The bug that answered "years with Java" with the candidate's total experience."""
    result = classify_label(label)
    assert result.key.startswith(f"years:{tech}"), result.key
    assert result.key != "years_experience"
    assert result.sensitive


@pytest.mark.parametrize(
    "label",
    [
        "How many years of work experience do you have?",
        "Total years of experience",
        "Years of relevant experience",
        "How many years of professional experience do you have?",
    ],
)
def test_total_experience_questions_share_one_key(label: str) -> None:
    assert classify_label(label).key == "years_experience"


def test_two_technologies_get_two_answers() -> None:
    assert (
        classify_label("Years of experience with Java").key
        != classify_label("Years of experience with Python").key
    )


def test_sponsorship_and_authorization_are_opposite_questions() -> None:
    sponsorship = classify_label("Do you now or in the future require visa sponsorship?")
    authorised = classify_label("Are you legally authorized to work in India?")
    eligible = classify_label("Are you currently eligible to work in the country you applied to?")
    assert sponsorship.key == "requires_sponsorship"
    assert authorised.key == "work_authorization"
    assert eligible.key == "work_authorization"
    assert sponsorship.sensitive and authorised.sensitive


def test_current_and_expected_pay_are_different_answers() -> None:
    assert classify_label("What is your current CTC?").key == "current_salary"
    assert classify_label("Expected CTC (in LPA)").key == "salary_expectation"
    assert classify_label("What are your salary expectations?").key == "salary_expectation"


def test_each_declaration_needs_its_own_agreement() -> None:
    one = classify_label("I consent to a background verification check")
    two = classify_label("I agree to the privacy policy")
    assert one.key.startswith("consent:") and two.key.startswith("consent:")
    assert one.key != two.key
    assert one.sensitive and two.sensitive
    assert classify_label("I consent to a background verification check").key == one.key


def test_equal_opportunity_questions_do_not_share_an_answer() -> None:
    keys = {
        classify_label(label).key
        for label in (
            "Gender",
            "Race / Ethnicity",
            "Veteran status",
            "Do you have a disability?",
        )
    }
    assert keys == {"gender", "ethnicity", "veteran_status", "disability"}


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("First Name", "first_name"),
        ("Last Name", "last_name"),
        ("Name", "full_name"),
        ("Full name ✱", "full_name"),
        ("Email", "email"),
        ("Phone number", "phone"),
        ("LinkedIn Profile", "linkedin"),
        ("GitHub URL", "github"),
        ("Portfolio URL", "portfolio"),
        ("Resume/CV", "resume"),
        ("Cover Letter", "cover_letter"),
        ("Location (City)", "current_location"),
        ("Current company", "current_company"),
        ("Country", "country"),
        ("What is your notice period?", "notice_period"),
    ],
)
def test_common_fields(label: str, key: str) -> None:
    assert classify_label(label).key == key


def test_an_essay_is_keyed_per_company() -> None:
    acme = classify_label("Why do you want to work here?", company="Acme", long_answer=True)
    globex = classify_label("Why do you want to work here?", company="Globex", long_answer=True)
    assert acme.key.startswith("essay:") and acme.key != globex.key


def test_an_unknown_question_gets_a_stable_key_of_its_own() -> None:
    first = classify_label("Do you have a relative working at Groww?")
    again = classify_label("Do you have a relative working at Groww?")
    other = classify_label("Have you worked at Groww before?")
    assert first.key.startswith("form:") and first.key == again.key
    assert first.key != other.key
    assert len(first.key) <= 100


def test_a_constrained_question_is_keyed_by_its_choices() -> None:
    a = option_key("notice_period", ("Immediate", "15 days", "30 days"))
    b = option_key("notice_period", ("0-15 days", "16-30 days", "30+ days"))
    assert a != b and a.startswith("opt:notice_period") and len(a) <= 100
    assert option_key("notice_period", ("Immediate", "15 days", "30 days")) == a


def test_links_are_matched_by_host() -> None:
    links = (
        "https://github.com/someone",
        "https://www.linkedin.com/in/someone",
        "https://someone.dev",
    )
    assert link_for("github", links) == "https://github.com/someone"
    assert link_for("linkedin", links) == "https://www.linkedin.com/in/someone"
    assert link_for("portfolio", links) == "https://someone.dev"
    assert link_for("twitter", links) == ""


def test_names_split_on_the_first_space() -> None:
    assert split_name("Tushar Gautam") == ("Tushar", "Gautam")
    assert split_name("Ana María López") == ("Ana", "María López")
    assert split_name("Cher") == ("Cher", "")


def test_a_consent_hidden_in_the_choices_is_a_consent() -> None:
    """Ashby's live form asks "Phone" with SMS-consent choices; it is not the phone number."""
    from app.browser.labels import classify_choice

    sms = classify_choice(
        "Phone",
        (
            "Yes - I consent to receiving SMS text messages",
            "No - I do not consent to receiving SMS text messages",
        ),
    )
    whatsapp = classify_choice(
        "Phone",
        (
            "Yes - I consent to receiving WhatsApp messages",
            "No - I do not consent to receiving WhatsApp messages",
        ),
    )
    assert sms.key.startswith("consent:") and sms.sensitive
    assert sms.key != whatsapp.key
    assert classify_choice("Phone", ("Mobile", "Landline")).key.startswith("form:")


def test_a_stored_answer_picks_an_option_only_when_it_names_exactly_one() -> None:
    from app.browser.labels import resolve_option

    countries = ("United States +1", "India +91", "Indonesia +62")
    assert resolve_option("India", countries) == "India +91"
    assert resolve_option("india +91", countries) == "India +91"
    assert resolve_option("Ind", countries) is None, "a fragment is not an answer"
    assert resolve_option("Yes", ("Yes, full time", "Yes, part time", "No")) is None
    assert resolve_option("Yes", ("Yes - I consent", "No - I do not consent")) == "Yes - I consent"


def test_most_recent_employer_is_the_current_company() -> None:
    assert classify_label("Please list your most recent Employer here.").key == "current_company"


@pytest.mark.parametrize(
    ("answer", "options", "expected"),
    [
        ("No but i can relocate to Bangalore", ("Yes", "No"), "No"),
        ("Yes, happy to", ("Yes", "No"), "Yes"),
        ("Yes", ("No", "Yes, Netherlands visa", "Yes, Ireland visa"), None),
        ("I have never been employed there", ("Yes", "No"), None),
        ("Not sure", ("No", "Not applicable"), None),
        ("Nope", ("No", "Yes"), None),
    ],
)
def test_an_answer_that_starts_with_exactly_one_option_selects_it(
    answer, options, expected
) -> None:
    """The user wrote the option and then explained it; anything less clear is asked again."""
    from app.browser.labels import resolve_option

    assert resolve_option(answer, options) == expected


@pytest.mark.parametrize(
    ("option", "shown", "expected"),
    [
        ("India +91", "  +91", True),  # phone-country pickers show only the code
        ("United States +1", " +44", False),
        ("India +91", "+911", False),
        ("No", "Unknown", False),
        ("No", "No ✕", True),
        ("Yes, full time", "Yes, full time", True),
    ],
)
def test_a_picker_choice_is_confirmed_only_by_a_whole_word_match(option, shown, expected) -> None:
    from app.browser.dom import _choice_is_shown

    assert _choice_is_shown(option, shown) is expected


@pytest.mark.parametrize(
    ("label", "expected_prefix"),
    [
        # Signing something is consent: a typed name here is a signature.
        (
            "Please Review the NDA and indicate your agreement by typing your full name below",
            "consent:",
        ),
        ("Type your full name as your electronic signature", "consent:"),
        ("Sign below to confirm the information is accurate", "consent:"),
        ("Full name", "full_name"),
        # A yes/no question that mentions the employer is not asking for its name.
        (
            "Are you subject to any employment agreements and/or post-employment restrictions "
            "with your current employer?",
            "form:",
        ),
        ("What is the name of your current employer?", "current_company"),
        ("Where are you currently located?", "current_location"),
        ("Are you currently based in Bangalore?", "form:"),
    ],
)
def test_signatures_are_consent_and_yes_no_questions_are_not_profile_facts(
    label, expected_prefix
) -> None:
    assert classify_label(label).key.startswith(expected_prefix)


def test_a_place_answer_must_match_every_part_never_just_the_city() -> None:
    """Regression: "Gurgaon, Haryana" filled as "Gurgaon, Bihar, India"."""
    from app.browser.dom import _place_option

    offered = ("Gurgaon, Bihar, India", "Gurugram, Haryana, India", "Gurgaon Road, Delhi")
    assert _place_option("Gurgaon, Haryana", offered) == -1
    assert _place_option("Gurugram, Haryana", offered) == 1
    assert _place_option("Gurgaon", offered) == 0  # a single-part answer still matches
