"""Preferences wizard.

Four steps, a progress indicator, and a summary before anything is written. Nothing is
saved until the final step, so abandoning the wizard half-way leaves the stored profile
exactly as it was.

Two boundaries this screen keeps:

* It never touches resume facts. Name, skills, education and projects come from the parsed
  resume and are shown read-only here; a preference wizard that could silently rewrite
  them would let a careless click change what an employer is told.
* Hard constraints and soft preferences are collected in separate groups and labelled as
  such, because one removes listings from the feed with a stated reason and the other only
  reorders them.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    get_client,
    section_header,
)

STEPS = ("Career goals", "Locations", "Constraints", "Review and save")

DRAFT_KEY = "onboarding_draft"
STEP_KEY = "onboarding_step"

EXPERIENCE_LEVELS = ("fresher", "junior", "mid", "senior", "lead")
WORK_ARRANGEMENTS = ("remote", "hybrid", "onsite")
EMPLOYMENT_TYPES = ("full_time", "part_time", "internship", "contract")

SUGGESTED_CITIES = (
    "Remote",
    "Delhi NCR",
    "Gurgaon",
    "Noida",
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Mumbai",
)


def _draft(profile: dict) -> dict[str, Any]:
    if DRAFT_KEY not in st.session_state:
        st.session_state[DRAFT_KEY] = {
            "target_titles": list(profile.get("target_titles") or []),
            "experience_level": profile.get("experience_level") or "fresher",
            "years_experience": float(profile.get("years_experience") or 0.0),
            "graduation_date": profile.get("graduation_date") or "",
            "employment_types": list(profile.get("employment_types") or []),
            "preferred_locations": list(profile.get("preferred_locations") or []),
            "work_arrangements": list(profile.get("work_arrangements") or []),
            "open_to_relocation": bool(profile.get("open_to_relocation")),
            "requires_india_work_eligibility": bool(profile.get("requires_india_work_eligibility")),
            "max_required_experience_years": profile.get("max_required_experience_years"),
            "minimum_match_score": float(profile.get("minimum_match_score") or 65.0),
            "max_job_age_days": int(profile.get("max_job_age_days") or 30),
            "preferred_companies": list(profile.get("preferred_companies") or []),
            "excluded_companies": list(profile.get("excluded_companies") or []),
            "preferred_industries": list(profile.get("preferred_industries") or []),
        }
    draft: dict[str, Any] = st.session_state[DRAFT_KEY]
    return draft


def _as_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _progress() -> int:
    step = int(st.session_state.get(STEP_KEY, 0))
    st.progress((step + 1) / len(STEPS), text=f"Step {step + 1} of {len(STEPS)} · {STEPS[step]}")
    return step


def _career_goals(draft: dict[str, Any]) -> None:
    section_header("Career goals")
    draft["target_titles"] = _as_list(
        st.text_area(
            "Target job titles, one per line",
            value="\n".join(draft["target_titles"]),
            height=140,
            help="These drive title fit. A title here is matched against the listing's own.",
        )
    )
    columns = st.columns(3)
    draft["experience_level"] = columns[0].selectbox(
        "Experience level",
        EXPERIENCE_LEVELS,
        index=EXPERIENCE_LEVELS.index(draft["experience_level"])
        if draft["experience_level"] in EXPERIENCE_LEVELS
        else 0,
    )
    draft["years_experience"] = columns[1].number_input(
        "Years of experience",
        min_value=0.0,
        max_value=60.0,
        step=0.1,
        value=float(draft["years_experience"]),
    )
    draft["graduation_date"] = columns[2].text_input(
        "Graduation year or date",
        value=draft["graduation_date"],
        help="Left blank it stays unanswered and is asked on every application.",
    )
    draft["employment_types"] = st.multiselect(
        "Employment types you will consider",
        EMPLOYMENT_TYPES,
        default=[item for item in draft["employment_types"] if item in EMPLOYMENT_TYPES],
    )


def _locations(draft: dict[str, Any]) -> None:
    section_header("Locations")
    chosen = st.multiselect(
        "Preferred locations",
        SUGGESTED_CITIES,
        default=[item for item in draft["preferred_locations"] if item in SUGGESTED_CITIES],
        help="City aliases are handled, so Gurgaon and Gurugram are the same place.",
    )
    extra = _as_list(
        st.text_input(
            "Any other locations, comma separated",
            value=", ".join(
                item for item in draft["preferred_locations"] if item not in SUGGESTED_CITIES
            ),
        )
    )
    draft["preferred_locations"] = chosen + extra

    draft["work_arrangements"] = st.multiselect(
        "Work arrangements",
        WORK_ARRANGEMENTS,
        default=[item for item in draft["work_arrangements"] if item in WORK_ARRANGEMENTS],
    )
    draft["open_to_relocation"] = st.checkbox(
        "I am open to relocating (soft preference)",
        value=draft["open_to_relocation"],
        help="A soft preference: a job outside your cities is scored lower, not removed.",
    )
    draft["requires_india_work_eligibility"] = st.checkbox(
        "Only show roles I am eligible for from India (hard constraint)",
        value=draft["requires_india_work_eligibility"],
        help="A hard constraint: a remote role fenced to another region is removed with a "
        "stated reason. Roles that name no region are kept, because silence is not a "
        "restriction.",
    )


def _constraints(draft: dict[str, Any]) -> None:
    section_header("Job constraints")
    st.caption(
        "A **hard constraint** removes a listing from the feed and says why. A **soft "
        "preference** only changes the order."
    )

    columns = st.columns(2)
    cap = columns[0].number_input(
        "Hard: ignore roles asking more than this many years (0 = no cap)",
        min_value=0.0,
        max_value=40.0,
        step=0.5,
        value=float(draft["max_required_experience_years"] or 0.0),
    )
    draft["max_required_experience_years"] = cap or None
    draft["max_job_age_days"] = columns[1].number_input(
        "Hard: ignore listings older than this many days",
        min_value=1,
        max_value=365,
        value=int(draft["max_job_age_days"]),
    )

    draft["minimum_match_score"] = st.slider(
        "Soft: minimum score you want to see in the shortlist",
        min_value=0.0,
        max_value=100.0,
        value=float(draft["minimum_match_score"]),
        step=1.0,
    )
    draft["excluded_companies"] = _as_list(
        st.text_input(
            "Hard: companies to exclude, comma separated",
            value=", ".join(draft["excluded_companies"]),
        )
    )
    draft["preferred_companies"] = _as_list(
        st.text_input(
            "Soft: companies you would prefer, comma separated",
            value=", ".join(draft["preferred_companies"]),
        )
    )
    draft["preferred_industries"] = _as_list(
        st.text_input(
            "Soft: industries you would prefer, comma separated",
            value=", ".join(draft["preferred_industries"]),
        )
    )


def _resume_facts(profile: dict) -> None:
    section_header("From your resume (not editable here)")
    st.caption(
        "These come from the parsed resume. Change them on the **Resume and profile** page "
        "so the edit is recorded against the resume it came from."
    )
    st.markdown(
        f"- Name: {profile.get('full_name') or '_not parsed_'}\n"
        f"- Skills recorded: {len(profile.get('technical_skills') or [])}\n"
        f"- Education entries: {len(profile.get('education') or [])}\n"
        f"- Projects: {len(profile.get('projects') or [])}"
    )
    unanswered = profile.get("unanswered_sensitive_fields") or []
    if unanswered:
        st.warning(
            "Still unanswered, and each one blocks an application until you fill it in: "
            + ", ".join(str(name).replace("_", " ") for name in unanswered)
            + ". These are never guessed for you."
        )


def _review(draft: dict[str, Any], profile: dict) -> None:
    section_header("Review before saving")
    st.caption("Nothing has been written yet. Saving applies only the fields shown here.")

    hard, soft = st.columns(2)
    with hard:
        st.markdown("**Hard constraints** — remove listings")
        st.markdown(
            f"- India work eligibility required: "
            f"`{draft['requires_india_work_eligibility']}`\n"
            f"- Maximum years a listing may ask: "
            f"`{draft['max_required_experience_years'] or 'no cap'}`\n"
            f"- Maximum listing age: `{draft['max_job_age_days']} days`\n"
            f"- Excluded companies: `{', '.join(draft['excluded_companies']) or 'none'}`"
        )
    with soft:
        st.markdown("**Soft preferences** — change the order only")
        st.markdown(
            f"- Open to relocation: `{draft['open_to_relocation']}`\n"
            f"- Minimum score shown: `{draft['minimum_match_score']:g}`\n"
            f"- Preferred companies: `{', '.join(draft['preferred_companies']) or 'none'}`\n"
            f"- Preferred industries: `{', '.join(draft['preferred_industries']) or 'none'}`"
        )

    st.markdown(
        f"**Goals** — {len(draft['target_titles'])} target title(s), "
        f"`{draft['experience_level']}`, {draft['years_experience']:g} year(s), "
        f"types `{', '.join(draft['employment_types']) or 'any'}`"
    )
    st.markdown(
        f"**Locations** — `{', '.join(draft['preferred_locations']) or 'none set'}`, "
        f"arrangements `{', '.join(draft['work_arrangements']) or 'any'}`"
    )
    _resume_facts(profile)

    if st.button("Save my preferences", type="primary", use_container_width=True):
        payload = {key: value for key, value in draft.items() if key != "graduation_date"}
        if draft["graduation_date"].strip():
            payload["graduation_date"] = draft["graduation_date"].strip()
        try:
            client = get_client()
            client.update_profile(payload)
            client.complete_onboarding()
        except ApiClientError as exc:
            api_error(exc)
            return
        st.session_state.pop(DRAFT_KEY, None)
        st.session_state[STEP_KEY] = 0
        st.session_state["onboarding_saved"] = True
        st.rerun()


def render() -> None:
    st.title("Set up your job search")
    client = get_client()

    if st.session_state.pop("onboarding_saved", False):
        st.success(
            "Preferences saved. Re-score on the **Job feed** page to see them applied to "
            "your existing jobs."
        )

    try:
        profile = client.get_profile()
    except ApiClientError as exc:
        api_error(exc)
        return

    if profile.get("onboarding_completed_at"):
        st.caption(
            "You have been through this before. Walking it again shows your current "
            "settings and overwrites only what you change."
        )

    draft = _draft(profile)
    step = _progress()

    if step == len(STEPS) - 1:
        _review(draft, profile)
    else:
        # The step's inputs and its Next button share a form on purpose. Streamlit commits
        # a text area on blur, which triggers a rerun that swallows the click causing the
        # blur - so typing a title and then pressing Next left the user on the same step
        # until they clicked twice. A form submits the whole step in one click.
        with st.form(f"onboarding_step_{step}", border=False):
            if step == 0:
                _career_goals(draft)
            elif step == 1:
                _locations(draft)
            else:
                _constraints(draft)
            if st.form_submit_button("Next", type="primary", use_container_width=True):
                st.session_state[STEP_KEY] = step + 1
                st.rerun()

    st.divider()
    back, reset = st.columns([1, 1])
    if step > 0 and back.button("Back", use_container_width=True):
        st.session_state[STEP_KEY] = step - 1
        st.rerun()
    if reset.button("Start over", use_container_width=True):
        st.session_state.pop(DRAFT_KEY, None)
        st.session_state[STEP_KEY] = 0
        st.rerun()
