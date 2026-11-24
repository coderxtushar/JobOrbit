"""Company research, interview preparation and salary normalisation.

Three tabs over ``/api/research``. Everything shown carries its source: a listing's URL and
retrieval date, "your profile", or a company page you supplied. Where the sources say
nothing, the page says so instead of filling the gap.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import streamlit as st

from ui.api_client import ApiClient, ApiClientError
from ui.components import (
    api_error,
    display_timezone,
    empty_state,
    get_client,
    local_time,
    section_header,
)

SECTION_TITLES = {
    "technical": "Technical questions (from the listing)",
    "resume": "About your resume and profile",
    "projects": "About your projects",
    "behavioural": "Behavioural questions",
    "coding": "Coding-prep topics",
    "company": "Company topics",
    "skill_gaps": "Skill gaps to prepare (topics, not claims)",
}
PRACTICE_KINDS = ("any", "technical", "resume", "projects", "behavioural")
UNIT_LABELS = {
    "lpa": "LPA (lakh per annum)",
    "inr_annual": "INR per year",
    "inr_monthly": "INR per month",
    "usd_annual": "USD per year",
}


# --------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------


def _get(client: ApiClient, path: str, **params: Any) -> Any:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return client._request("GET", path, params=clean or None)


def _cite(source: dict[str, Any] | None) -> str:
    if not source:
        return ""
    parts = [source.get("label") or source.get("kind") or "source"]
    if source.get("url"):
        parts.append(source["url"])
    if source.get("retrieved_at"):
        parts.append(f"retrieved {local_time(source['retrieved_at'])}")
    return " · ".join(parts)


def _quote(text: str, source: dict[str, Any] | None) -> None:
    st.markdown(f"> {text}")
    if source:
        st.caption(f"Source: {_cite(source)}")


def _money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "—"
    return f"{currency or ''} {value:,.0f}".strip()


def _load_jobs(client: ApiClient) -> list[dict[str, Any]]:
    try:
        page = _get(client, "/api/jobs", limit=200, sort_by="discovered_at")
    except ApiClientError as exc:
        api_error(exc)
        return []
    return list(page.get("items") or [])


def _load_applications(client: ApiClient) -> list[dict[str, Any]]:
    try:
        page = _get(client, "/api/applications", limit=200)
    except ApiClientError as exc:
        api_error(exc)
        return []
    return list(page.get("items") or [])


# --------------------------------------------------------------------------------------
# Company tab
# --------------------------------------------------------------------------------------


def _render_claims(title: str, block: dict[str, Any]) -> None:
    st.markdown(f"**{title}**")
    if not block.get("stated"):
        st.caption(block.get("message") or "not stated in the available sources")
        return
    for fact in block.get("facts") or []:
        st.markdown(f"- **{fact['statement']}**")
        _quote(fact["quote"], fact.get("source"))


def _render_job_context(context: dict[str, Any]) -> None:
    section_header(f"This job: {context.get('title', '')}")
    st.caption(f"Source: {_cite(context.get('source'))}")
    requirements = context.get("requirements") or {}
    rows = [
        {
            "skill": fact["skill"],
            "level": fact["level"],
            "listing says": fact.get("quote") or f"({fact.get('where')})",
        }
        for fact in (requirements.get("required_skills") or [])
        + (requirements.get("preferred_skills") or [])
    ]
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("The listing names no skills.")
    if requirements.get("experience"):
        st.markdown(f"**Experience:** “{requirements['experience']['quote']}”")
    for item in requirements.get("education") or []:
        st.markdown(f"**Education:** “{item['quote']}”")

    st.markdown("**Your relevant projects** (from your profile)")
    projects = context.get("relevant_projects") or []
    if not projects:
        st.caption("None of the projects in your profile share a skill with this listing.")
    for project in projects:
        st.markdown(f"- **{project['name']}** — overlaps on {', '.join(project['overlap'])}")
        if project.get("quote"):
            st.caption(project["quote"])

    st.markdown("**Suggested interview topics**")
    for topic in context.get("interview_topics") or []:
        st.markdown(f"- {topic['topic']}  \n  _derived from {topic['derived_from']}_")


def _render_company(research: dict[str, Any]) -> None:
    data = research.get("data") or {}
    st.subheader(research.get("company") or "Company")
    st.caption(
        f"Built {local_time(research.get('refreshed_at'))} from "
        f"{data.get('listing_count', 0)} listing(s)"
        + (" · cached" if research.get("from_cache") else " · rebuilt now")
    )

    section_header("About (quoted from the listings)")
    about = data.get("about") or []
    if not about:
        st.caption("No listing carries an 'About us' section or a company introduction.")
    for entry in about:
        _quote(entry["quote"], entry.get("source"))

    left, right = st.columns(2)
    with left:
        _render_claims("Business model", data.get("business_model") or {})
    with right:
        _render_claims("Products", data.get("products") or {})

    section_header("Technologies across this company's listings")
    technologies = data.get("technologies") or []
    if technologies:
        st.dataframe(
            [{"skill": item["skill"], "listings": item["listing_count"]} for item in technologies],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No known skill is named in these listings.")

    section_header("Engineering focus")
    focus = data.get("engineering_focus") or []
    if not focus:
        st.caption("No engineering theme is mentioned in these listings.")
    for theme in focus:
        with st.expander(f"{theme['theme']} — {', '.join(theme['phrases'])}"):
            for evidence in theme.get("evidence") or []:
                _quote(evidence["quote"], evidence.get("source"))

    website = data.get("website")
    if website:
        section_header("Company page")
        if website.get("error"):
            st.warning(f"Fetching {website['url']} failed: {website['error']}")
        elif website.get("fetched_at"):
            st.markdown(f"**{website.get('title') or '(no title)'}**")
            st.caption(website.get("description") or "(no meta description)")
            st.caption(f"Source: {website['url']} · fetched {local_time(website['fetched_at'])}")
        else:
            st.caption(f"{website['url']} — supplied by you, not fetched.")

    with st.expander(f"Listings used ({len(data.get('listings') or [])})"):
        st.dataframe(
            [
                {
                    "title": item["title"],
                    "url": item.get("url") or "—",
                    "retrieved": local_time(item.get("retrieved_at")),
                    "posted": local_time(item.get("posted_at"))
                    if item.get("posted_at")
                    else "not stated",
                }
                for item in data.get("listings") or []
            ],
            hide_index=True,
            use_container_width=True,
        )

    if research.get("job_context"):
        _render_job_context(research["job_context"])


def _company_tab(client: ApiClient, jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        empty_state(
            "No jobs yet",
            "Company research is built from the listings JobOrbit holds.",
            "Import or discover jobs first.",
        )
        return
    labels = {job["id"]: f"{job['company']} — {job['title']} (#{job['id']})" for job in jobs}
    job_id = st.selectbox(
        "Job", list(labels), format_func=lambda value: labels[value], key="research_company_job"
    )
    job = next(item for item in jobs if item["id"] == job_id)

    with st.expander("Refresh, or add the company's website"):
        st.caption(
            "Only a URL you type is used; JobOrbit never guesses a website from a name. "
            "Fetching reads just the page title and meta description, and needs "
            "JA_COMPANY_RESEARCH_EXTERNAL=true."
        )
        with st.form(f"company-refresh-{job_id}"):
            website = st.text_input("Website URL (optional)", placeholder="https://")
            fetch = st.checkbox("Fetch the page title and description")
            if st.form_submit_button("Rebuild profile"):
                try:
                    client._request(
                        "POST",
                        f"/api/research/companies/{quote(job['company'], safe='')}/refresh",
                        json={"website": website or None, "fetch_website": fetch},
                    )
                except ApiClientError as exc:
                    api_error(exc)
                else:
                    st.success("Profile rebuilt.")

    try:
        research = _get(client, f"/api/research/jobs/{job_id}/company")
    except ApiClientError as exc:
        api_error(exc)
        return
    _render_company(research)


# --------------------------------------------------------------------------------------
# Interview prep tab
# --------------------------------------------------------------------------------------


def _render_prep_sections(prep: dict[str, Any]) -> None:
    for key, items in (prep.get("content", {}).get("sections") or {}).items():
        with st.expander(f"{SECTION_TITLES.get(key, key)} ({len(items)})"):
            if not items:
                st.caption("Nothing to show: the inputs for this section are empty.")
            for item in items:
                st.markdown(f"- {item['question']}  \n  _from {item['derived_from']}_")
    for note in prep.get("content", {}).get("notes") or []:
        st.caption(note)


def _practice(client: ApiClient, application_id: int, prep: dict[str, Any]) -> None:
    section_header("Mock interview")
    state_key = f"research_practice_{application_id}"
    feedback_key = f"research_feedback_{application_id}"
    kind = st.selectbox("Question type", PRACTICE_KINDS, key=f"research_kind_{application_id}")
    current = st.session_state.get(state_key) or prep.get("next_question")
    if current and kind != "any" and current.get("kind") != kind:
        current = None
    if current is None:
        try:
            current = _get(
                client,
                f"/api/research/applications/{application_id}/interview-prep/next-question",
                kind=None if kind == "any" else kind,
            ).get("question")
        except ApiClientError as exc:
            api_error(exc)
            return
    if not current:
        st.caption("No practice questions for this selection.")
        return
    st.session_state[state_key] = current

    st.markdown(f"**{current['question']}**")
    st.caption(
        f"{current['kind']} · from {current['derived_from']} · practised "
        f"{current.get('times_practised', 0)} time(s)"
    )
    with st.form(f"practice-{application_id}-{current['id']}", clear_on_submit=True):
        answer = st.text_area("Your answer", height=160)
        submit, skip = st.columns(2)
        submitted = submit.form_submit_button("Submit answer", type="primary")
        skipped = skip.form_submit_button("Skip to next")
    if submitted:
        try:
            result = client._request(
                "POST",
                f"/api/research/applications/{application_id}/interview-prep/practice",
                json={"question_id": current["id"], "answer": answer},
            )
        except ApiClientError as exc:
            api_error(exc)
            return
        st.session_state[feedback_key] = result["feedback"]
        st.session_state[state_key] = result.get("next_question")
        st.rerun()
    if skipped:
        try:
            nxt = _get(
                client,
                f"/api/research/applications/{application_id}/interview-prep/next-question",
                kind=None if kind == "any" else kind,
                after=current["id"],
            )
        except ApiClientError as exc:
            api_error(exc)
            return
        st.session_state[state_key] = nxt.get("question")
        st.session_state.pop(feedback_key, None)
        st.rerun()

    feedback = st.session_state.get(feedback_key)
    if feedback:
        st.markdown("**Feedback on your last answer**")
        for point in feedback.get("points") or []:
            st.markdown(f"- {point}")
        st.caption(feedback.get("disclaimer", ""))

    history = prep.get("practice") or []
    if history:
        with st.expander(f"Practice history ({len(history)})"):
            for entry in reversed(history[-20:]):
                st.markdown(f"**{entry['question']}**")
                st.caption(f"{local_time(entry.get('answered_at'))} · {entry['kind']}")
                st.text(entry.get("answer") or "(no answer)")


def _round_values(prefix: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    scheduled = existing.get("scheduled_at")
    parsed = datetime.fromisoformat(scheduled).astimezone(display_timezone()) if scheduled else None
    name = st.text_input("Round", value=existing.get("round_name", ""), key=f"{prefix}-name")
    has_date = st.checkbox("Has a date", value=parsed is not None, key=f"{prefix}-hasdate")
    day_col, time_col = st.columns(2)
    day = day_col.date_input(
        "Date", value=parsed.date() if parsed else datetime.now().date(), key=f"{prefix}-day"
    )
    at = time_col.time_input(
        "Time", value=parsed.time() if parsed else datetime.now().time(), key=f"{prefix}-time"
    )
    notes = st.text_area(
        "Your notes", value=existing.get("interviewer_notes", ""), key=f"{prefix}-notes"
    )
    questions = st.text_area(
        "Questions asked (one per line)",
        value="\n".join(existing.get("questions_asked") or []),
        key=f"{prefix}-questions",
    )
    feedback = st.text_area(
        "Feedback you received", value=existing.get("feedback", ""), key=f"{prefix}-feedback"
    )
    next_steps = st.text_input(
        "Next steps", value=existing.get("next_steps", ""), key=f"{prefix}-next"
    )
    scheduled_at = (
        datetime.combine(day, at, tzinfo=display_timezone()).isoformat()
        if has_date and isinstance(day, date)
        else None
    )
    return {
        "round_name": name,
        "scheduled_at": scheduled_at,
        "interviewer_notes": notes,
        "questions_asked": [line.strip() for line in questions.splitlines() if line.strip()],
        "feedback": feedback,
        "next_steps": next_steps,
    }


def _rounds(client: ApiClient, application_id: int) -> None:
    section_header("Interview rounds")
    st.caption("Your own records. JobOrbit never fills in an outcome or feedback for a round.")
    try:
        rounds = _get(client, f"/api/research/applications/{application_id}/rounds")
    except ApiClientError as exc:
        api_error(exc)
        return
    for record in rounds:
        when = local_time(record["scheduled_at"]) if record.get("scheduled_at") else "no date"
        with st.expander(f"{record['round_name'] or 'Round'} · {when}"):
            with st.form(f"round-edit-{record['id']}"):
                values = _round_values(f"round-{record['id']}", record)
                save, delete = st.columns(2)
                saved = save.form_submit_button("Save")
                deleted = delete.form_submit_button("Delete")
            try:
                if saved:
                    client._request("PATCH", f"/api/research/rounds/{record['id']}", json=values)
                    st.rerun()
                if deleted:
                    client._request("DELETE", f"/api/research/rounds/{record['id']}")
                    st.rerun()
            except ApiClientError as exc:
                api_error(exc)

    with (
        st.expander("Record a round", expanded=not rounds),
        st.form(f"round-new-{application_id}", clear_on_submit=True),
    ):
        values = _round_values(f"round-new-{application_id}")
        if st.form_submit_button("Add round"):
            try:
                client._request(
                    "POST", f"/api/research/applications/{application_id}/rounds", json=values
                )
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.rerun()


def _prep_tab(client: ApiClient) -> None:
    applications = _load_applications(client)
    if not applications:
        empty_state(
            "No applications yet",
            "Interview preparation is built for an application you prepared.",
            "Prepare an application from the job feed.",
        )
        return
    labels = {
        item["id"]: f"{item.get('job_company', '')} — {item.get('job_title', '')} "
        f"({item.get('outcome', '')}, #{item['id']})"
        for item in applications
    }
    application_id = st.selectbox(
        "Application",
        list(labels),
        format_func=lambda value: labels[value],
        key="research_prep_application",
    )
    path = f"/api/research/applications/{application_id}/interview-prep"
    prep: dict[str, Any] | None = None
    try:
        prep = _get(client, path)
    except ApiClientError as exc:
        if exc.code != "interview_prep_not_generated":
            api_error(exc)
            return

    if prep is None:
        st.info("No preparation has been generated for this application yet.")
        if st.button("Generate preparation", type="primary", key=f"prep-gen-{application_id}"):
            try:
                client._request("POST", path, json={"regenerate": False})
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.rerun()
    else:
        stage = "in interview stage" if prep.get("interview_stage") else "not yet interviewing"
        st.caption(
            f"Generated {local_time(prep.get('generated_at'))} · "
            f"{prep['content'].get('generated_by', '')} · {stage}"
        )
        if st.button("Regenerate (keeps practice history)", key=f"prep-regen-{application_id}"):
            try:
                client._request("POST", path, json={"regenerate": True})
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.session_state.pop(f"research_practice_{application_id}", None)
                st.rerun()
        _render_prep_sections(prep)
        _practice(client, application_id, prep)

    _rounds(client, application_id)


# --------------------------------------------------------------------------------------
# Salary tab
# --------------------------------------------------------------------------------------


def _render_compensation(title: str, comp: dict[str, Any]) -> None:
    st.markdown(f"**{title}**")
    if comp.get("original"):
        st.caption(f"Stated as: “{comp['original']}”")
    if not comp.get("disclosed"):
        st.caption("Not disclosed — no figure was inferred.")
    else:
        currency = comp.get("currency")
        st.dataframe(
            [
                {
                    "view": f"as stated ({comp.get('period') or 'period unknown'})",
                    "minimum": _money(comp.get("minimum"), currency),
                    "maximum": _money(comp.get("maximum"), currency),
                },
                {
                    "view": "per year",
                    "minimum": _money(comp.get("annual_minimum"), currency),
                    "maximum": _money(comp.get("annual_maximum"), currency),
                },
                {
                    "view": "per year in INR",
                    "minimum": _money(comp.get("inr_annual_minimum"), "INR"),
                    "maximum": _money(comp.get("inr_annual_maximum"), "INR"),
                },
            ],
            hide_index=True,
            use_container_width=True,
        )
    for note in comp.get("assumptions") or []:
        st.caption(f"• {note}")


def _salary_tab(client: ApiClient, jobs: list[dict[str, Any]]) -> None:
    section_header("Parse any salary text")
    with st.form("salary-parse"):
        text = st.text_input("Salary text", placeholder="e.g. 12-18 LPA, ₹80k/month, $60/hr")
        parsed = st.form_submit_button("Parse")
    if parsed:
        try:
            result = _get(client, "/api/research/salary/parse", text=text)
        except ApiClientError as exc:
            api_error(exc)
        else:
            _render_compensation("Parsed", result["compensation"])
            st.markdown("**As a form would ask for it** (proposals only)")
            st.dataframe(
                [
                    {
                        "unit": UNIT_LABELS.get(unit, unit),
                        "value": proposal["value"] or "—",
                        "exact": "yes" if proposal["exact"] else "no — needs your approval",
                    }
                    for unit, proposal in result["proposals"].items()
                ],
                hide_index=True,
                use_container_width=True,
            )

    section_header("A job's salary next to your expectation")
    if not jobs:
        st.caption("No jobs yet.")
        return
    labels = {job["id"]: f"{job['company']} — {job['title']} (#{job['id']})" for job in jobs}
    job_id = st.selectbox(
        "Job", list(labels), format_func=lambda value: labels[value], key="research_salary_job"
    )
    try:
        result = _get(client, f"/api/research/jobs/{job_id}/salary")
    except ApiClientError as exc:
        api_error(exc)
        return
    left, right = st.columns(2)
    with left:
        _render_compensation(f"Listing ({result['listing_source']})", result["listing"])
    with right:
        _render_compensation("Your expectation", result["expectation"])
    comparison = result["comparison"]
    (st.info if comparison["comparable"] else st.caption)(comparison["statement"])


def render(client: ApiClient | None = None) -> None:
    st.title("Research and interview prep")
    st.caption(
        "Built only from the listings JobOrbit holds, your own profile and records, and a "
        "company page you choose to fetch. Anything the sources do not state is shown as "
        "not stated."
    )
    client = client or get_client()
    jobs = _load_jobs(client)
    company, prep, salary = st.tabs(["Company", "Interview prep", "Salary"])
    with company:
        _company_tab(client, jobs)
    with prep:
        _prep_tab(client)
    with salary:
        _salary_tab(client, jobs)
