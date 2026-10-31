"""Resume and profile page.

The extraction review step is the important part: parsed fields are shown as a *proposal*
in an editable form, and nothing reaches the profile until the user accepts it.
"""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClient, ApiClientError
from ui.components import (
    api_error,
    empty_state,
    get_client,
    local_time,
    section_header,
)

JOB_FAMILIES = (
    "general_software",
    "backend",
    "frontend",
    "fullstack",
    "ai_ml",
    "genai",
    "cloud_devops",
    "data",
)
EXPERIENCE_LEVELS = ("fresher", "junior", "mid", "senior", "lead")
WORK_ARRANGEMENTS = ("onsite", "hybrid", "remote")
EMPLOYMENT_TYPES = ("full_time", "part_time", "internship", "contract", "temporary")


def _csv_to_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _demo_mode(client: ApiClient) -> bool:
    try:
        return bool(client.health().get("demo_mode"))
    except ApiClientError:
        return False


def _upload_section() -> None:
    client = get_client()
    section_header("1. Upload your resume")

    if _demo_mode(client):
        st.info(
            "Resume upload is disabled on this public demo. A shared deployment has no "
            "per-user login, so one visitor's resume would be readable by the next. The "
            "profile below is sample data; run the app locally to use your own resume.",
            icon="🧪",
        )
        return

    st.caption("PDF or DOCX, up to 10 MB. The file is stored privately under `var/resumes`.")

    uploaded = st.file_uploader("Resume file", type=["pdf", "docx"], key="resume_upload")
    columns = st.columns([2, 1, 1])
    label = columns[0].text_input("Label", value="base", key="resume_label")
    is_primary = columns[1].checkbox("Set as primary", value=True, key="resume_primary")

    if columns[2].button("Upload and extract", type="primary", use_container_width=True):
        if uploaded is None:
            st.warning("Choose a file first.")
            return
        try:
            result = client.upload_resume(uploaded.name, uploaded.getvalue(), label, is_primary)
        except ApiClientError as exc:
            api_error(exc)
            return
        st.session_state["parsed_resume"] = result["parsed"]
        st.session_state["parsed_resume_id"] = result["resume"]["id"]
        st.success(
            f"Extracted {len(result['parsed']['skills'])} skills from "
            f"'{result['resume']['original_filename']}'. Nothing has been written to your "
            "profile yet — review it below."
        )
        for warning in result["resume"]["parse_warnings"]:
            st.warning(warning)


def _review_section() -> None:
    parsed = st.session_state.get("parsed_resume")
    if not parsed:
        return

    client = get_client()
    section_header("2. Review what was extracted")
    st.caption(
        "These are the parser's findings, not facts about you yet. Correct anything wrong, "
        "then accept. Fields the parser could not find are left empty on purpose."
    )

    confidence = parsed.get("field_confidence") or {}
    low = sorted(name for name, value in confidence.items() if 0 < value < 0.6)
    if low:
        st.info("Lower-confidence fields, worth checking closely: " + ", ".join(low))

    with st.form("accept_extraction"):
        columns = st.columns(3)
        full_name = columns[0].text_input("Full name", value=parsed.get("full_name", ""))
        email = columns[1].text_input("Email", value=parsed.get("email", ""))
        phone = columns[2].text_input("Phone", value=parsed.get("phone", ""))

        skills = st.text_area(
            "Technical skills (comma separated)",
            value=", ".join(parsed.get("skills", [])),
            height=90,
        )
        links = st.text_input("Links (comma separated)", value=", ".join(parsed.get("links", [])))
        certifications = st.text_area(
            "Certifications (comma separated)",
            value=", ".join(parsed.get("certifications", [])),
            height=70,
        )
        graduation = st.text_input("Graduation year", value=parsed.get("graduation_date") or "")

        estimated = parsed.get("estimated_years_experience")
        st.caption(
            f"Parser's experience estimate: {estimated if estimated is not None else 'could not be determined'}. "
            "Set the real value on the profile form below; it is never guessed for you."
        )

        if parsed.get("education"):
            st.markdown("**Education found**")
            st.dataframe(parsed["education"], hide_index=True, use_container_width=True)
        if parsed.get("projects"):
            st.markdown("**Projects found**")
            st.dataframe(
                [
                    {
                        "name": project.get("name", ""),
                        "technologies": ", ".join(project.get("technologies", [])),
                        "description": (project.get("description", "") or "")[:160],
                    }
                    for project in parsed["projects"]
                ],
                hide_index=True,
                use_container_width=True,
            )

        if st.form_submit_button("Accept into my profile", type="primary"):
            payload = {
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "technical_skills": _csv_to_list(skills),
                "links": _csv_to_list(links),
                "certifications": _csv_to_list(certifications),
                "education": [
                    {
                        "degree": str(entry.get("degree", "")),
                        "institution": str(entry.get("institution", "")),
                        "field_of_study": str(entry.get("field_of_study", "")),
                        "start_year": str(entry.get("start_year", "")),
                        "end_year": str(entry.get("end_year", "")),
                        "grade": str(entry.get("grade", "")),
                    }
                    for entry in parsed.get("education", [])
                ],
                "projects": [
                    {
                        "name": str(project.get("name", "")),
                        "description": str(project.get("description", "")),
                        "technologies": [str(item) for item in project.get("technologies", [])],
                        "url": str(project.get("url", "")),
                    }
                    for project in parsed.get("projects", [])
                ],
            }
            if graduation.strip():
                payload["graduation_date"] = graduation.strip()
            try:
                client.update_profile(payload)
            except ApiClientError as exc:
                api_error(exc)
                return
            st.session_state.pop("parsed_resume", None)
            st.success("Profile updated from the resume.")
            st.rerun()


def _profile_section() -> None:
    client = get_client()
    try:
        profile = client.get_profile()
    except ApiClientError as exc:
        api_error(exc)
        return

    section_header("3. Your profile and preferences")
    unanswered = profile.get("unanswered_sensitive_fields") or []
    if unanswered:
        st.warning(
            "These are empty and will be flagged for manual input on every application, "
            "because they are never guessed: " + ", ".join(unanswered)
        )

    with st.form("profile_form"):
        tabs = st.tabs(
            ["Basics", "Targets and skills", "Preferences", "Verified answers", "Scoring"]
        )

        with tabs[0]:
            columns = st.columns(3)
            full_name = columns[0].text_input("Full name", value=profile["full_name"])
            email = columns[1].text_input("Email", value=profile["email"])
            phone = columns[2].text_input("Phone", value=profile["phone"])
            headline = st.text_input("Headline", value=profile["headline"])
            links = st.text_input("Links (comma separated)", value=", ".join(profile["links"]))

        with tabs[1]:
            target_titles = st.text_area(
                "Target job titles (comma separated)",
                value=", ".join(profile["target_titles"]),
                height=90,
            )
            technical_skills = st.text_area(
                "Technical skills (comma separated)",
                value=", ".join(profile["technical_skills"]),
                height=90,
            )
            soft_skills = st.text_input(
                "Interpersonal skills (comma separated)", value=", ".join(profile["soft_skills"])
            )
            columns = st.columns(2)
            experience_level = columns[0].selectbox(
                "Experience level",
                EXPERIENCE_LEVELS,
                index=EXPERIENCE_LEVELS.index(profile["experience_level"])
                if profile["experience_level"] in EXPERIENCE_LEVELS
                else 0,
            )
            years_experience = columns[1].number_input(
                "Years of experience",
                min_value=0.0,
                max_value=60.0,
                value=float(profile["years_experience"]),
                step=0.5,
            )

        with tabs[2]:
            preferred_locations = st.text_input(
                "Preferred locations (comma separated)",
                value=", ".join(profile["preferred_locations"]),
            )
            columns = st.columns(2)
            work_arrangements = columns[0].multiselect(
                "Work arrangements", WORK_ARRANGEMENTS, default=profile["work_arrangements"]
            )
            employment_types = columns[1].multiselect(
                "Employment types", EMPLOYMENT_TYPES, default=profile["employment_types"]
            )
            excluded_companies = st.text_input(
                "Excluded companies (comma separated)",
                value=", ".join(profile["excluded_companies"]),
            )
            excluded_keywords = st.text_input(
                "Excluded keywords (comma separated)",
                value=", ".join(profile["excluded_keywords"]),
            )

        with tabs[3]:
            st.caption(
                "Values here are treated as verified and are used to answer application "
                "questions. Leave a field empty if you do not want it answered for you."
            )
            columns = st.columns(2)
            relocation_options = ("not specified", "yes", "no")
            current_relocation = (
                "not specified"
                if profile["open_to_relocation"] is None
                else ("yes" if profile["open_to_relocation"] else "no")
            )
            relocation = columns[0].selectbox(
                "Open to relocation",
                relocation_options,
                index=relocation_options.index(current_relocation),
            )
            current_sponsorship = (
                "not specified"
                if profile["requires_sponsorship"] is None
                else ("yes" if profile["requires_sponsorship"] else "no")
            )
            sponsorship = columns[1].selectbox(
                "Requires visa sponsorship",
                relocation_options,
                index=relocation_options.index(current_sponsorship),
            )
            work_authorization = st.text_input(
                "Work authorization statement", value=profile["work_authorization"] or ""
            )
            columns = st.columns(3)
            salary_min = columns[0].number_input(
                "Salary expectation min",
                min_value=0,
                value=int(profile["salary_expectation_min"] or 0),
                step=50_000,
            )
            salary_max = columns[1].number_input(
                "Salary expectation max",
                min_value=0,
                value=int(profile["salary_expectation_max"] or 0),
                step=50_000,
            )
            salary_currency = columns[2].text_input("Currency", value=profile["salary_currency"])
            columns = st.columns(2)
            notice_period = columns[0].number_input(
                "Notice period (days, -1 = not specified)",
                min_value=-1,
                max_value=365,
                value=int(profile["notice_period_days"])
                if profile["notice_period_days"] is not None
                else -1,
            )
            graduation_date = columns[1].text_input(
                "Graduation date", value=profile["graduation_date"] or ""
            )

        with tabs[4]:
            weights = profile["scoring_weights"] or {}
            st.caption("Weights are relative and normalized before use. Defaults in brackets.")
            columns = st.columns(3)
            skills_w = columns[0].number_input(
                "Skills [35]", 0.0, 100.0, float(weights.get("skills", 35.0))
            )
            title_w = columns[1].number_input(
                "Title [25]", 0.0, 100.0, float(weights.get("title", 25.0))
            )
            experience_w = columns[2].number_input(
                "Experience [15]", 0.0, 100.0, float(weights.get("experience", 15.0))
            )
            columns = st.columns(3)
            location_w = columns[0].number_input(
                "Location [10]", 0.0, 100.0, float(weights.get("location", 10.0))
            )
            freshness_w = columns[1].number_input(
                "Freshness [10]", 0.0, 100.0, float(weights.get("freshness", 10.0))
            )
            preferences_w = columns[2].number_input(
                "Other preferences [5]", 0.0, 100.0, float(weights.get("preferences", 5.0))
            )
            columns = st.columns(2)
            minimum_score = columns[0].slider(
                "Minimum match score", 0.0, 100.0, float(profile["minimum_match_score"])
            )
            max_age = columns[1].number_input(
                "Maximum job age (days)", 1, 365, int(profile["max_job_age_days"])
            )

        if st.form_submit_button("Save profile", type="primary"):
            payload: dict = {
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "headline": headline,
                "links": _csv_to_list(links),
                "target_titles": _csv_to_list(target_titles),
                "technical_skills": _csv_to_list(technical_skills),
                "soft_skills": _csv_to_list(soft_skills),
                "experience_level": experience_level,
                "years_experience": years_experience,
                "preferred_locations": _csv_to_list(preferred_locations),
                "work_arrangements": work_arrangements,
                "employment_types": employment_types,
                "excluded_companies": _csv_to_list(excluded_companies),
                "excluded_keywords": _csv_to_list(excluded_keywords),
                "work_authorization": work_authorization or None,
                "salary_currency": salary_currency,
                "minimum_match_score": minimum_score,
                "max_job_age_days": max_age,
                "graduation_date": graduation_date or None,
                "scoring_weights": {
                    "skills": skills_w,
                    "title": title_w,
                    "experience": experience_w,
                    "location": location_w,
                    "freshness": freshness_w,
                    "preferences": preferences_w,
                },
                "open_to_relocation": None
                if relocation == "not specified"
                else relocation == "yes",
                "requires_sponsorship": None
                if sponsorship == "not specified"
                else sponsorship == "yes",
                "salary_expectation_min": salary_min or None,
                "salary_expectation_max": salary_max or None,
                "notice_period_days": None if notice_period < 0 else notice_period,
            }
            try:
                client.update_profile(payload)
            except ApiClientError as exc:
                api_error(exc)
                return
            st.success("Profile saved.")
            st.rerun()


def _resumes_section() -> None:
    client = get_client()
    try:
        resumes = client.list_resumes()["items"]
    except ApiClientError as exc:
        api_error(exc)
        return

    section_header("4. Stored resumes and variants")
    if not resumes:
        empty_state("No resumes stored", "Upload one above to get started.")
        return

    for resume in resumes:
        with st.container(border=True):
            columns = st.columns([3, 1, 1])
            columns[0].markdown(
                f"**{resume['original_filename']}** · label `{resume['label']}`"
                + ("  ·  **primary**" if resume["is_primary"] else "")
            )
            columns[0].caption(
                f"Uploaded {local_time(resume['created_at'])} · "
                f"{resume['file_size_bytes'] // 1024} KB · "
                f"{resume['text_character_count']} characters of text · "
                f"{resume['variant_count']} variant(s)"
            )
            if not resume["is_primary"] and columns[1].button(
                "Make primary", key=f"primary{resume['id']}"
            ):
                try:
                    client.set_primary_resume(resume["id"])
                    st.rerun()
                except ApiClientError as exc:
                    api_error(exc)

            with columns[2].popover("New variant"):
                family = st.selectbox("Job family", JOB_FAMILIES, key=f"fam{resume['id']}")
                emphasise = st.text_input("Emphasise skills", key=f"emph{resume['id']}")
                if st.button("Build", key=f"build{resume['id']}"):
                    try:
                        variant = client.create_variant(
                            {
                                "resume_id": resume["id"],
                                "job_family": family,
                                "emphasised_skills": _csv_to_list(emphasise),
                            }
                        )
                        st.success(f"Built '{variant['name']}' v{variant['version']}")
                        omitted = (variant.get("included_items") or {}).get(
                            "omitted_requested_skills"
                        )
                        if omitted:
                            st.warning(
                                "Omitted because they are not in your resume or profile: "
                                + ", ".join(omitted)
                            )
                    except ApiClientError as exc:
                        api_error(exc)

            if resume["parse_warnings"]:
                with st.expander(f"{len(resume['parse_warnings'])} parse warning(s)"):
                    for warning in resume["parse_warnings"]:
                        st.caption(f"- {warning}")

            try:
                variants = client.list_variants(resume["id"])["items"]
            except ApiClientError:
                variants = []
            for variant in variants:
                with st.expander(
                    f"{variant['name']} v{variant['version']} ({variant['job_family']})"
                ):
                    st.caption(
                        "Generated by "
                        + variant["generated_by"]
                        + ". Only facts already in your resume and profile are used."
                    )
                    st.markdown(variant["content"])


def render() -> None:
    st.title("Resume and profile")
    _upload_section()
    _review_section()
    st.divider()
    _profile_section()
    st.divider()
    _resumes_section()
