"""Job detail and match explanation page."""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    category_bars,
    confidence_badge,
    empty_state,
    evidence_block,
    get_client,
    local_time,
    metric_row,
    score_ring,
    section_header,
    skill_chips,
)

SOURCE_LABELS = {
    "listing": "from the listing",
    "profile": "from your profile",
    "scoring": "from the scoring rules",
}

SKILL_STATUS_LABELS = {
    "in_profile": "In your profile",
    "related_in_profile": "Related name only, not demonstrated",
    "not_in_profile": "Not found in your profile",
    "not_in_listing": "Yours; this listing does not ask about it",
}

SKILL_STATUS_ORDER = ("in_profile", "related_in_profile", "not_in_profile", "not_in_listing")


def _render_grounded(client, job_id: int) -> None:
    try:
        explanation = client.get_job_explanation(job_id)
    except ApiClientError as exc:
        st.caption(f"A grounded breakdown is not available: {exc.message}")
        return

    section_header("Why this job matches")
    st.caption(
        "Each finding names where it came from. Quotes are the listing's own words, so you "
        "can disagree with the scorer on the evidence rather than take it on trust."
    )
    for section in explanation.get("sections", []):
        findings = section.get("findings") or []
        with st.expander(f"{section['title']} ({len(findings)})", expanded=bool(findings)):
            if not findings:
                st.caption(section.get("empty_note") or "Nothing to report here.")
                continue
            for finding in findings:
                label = SOURCE_LABELS.get(finding.get("source", ""), finding.get("source", ""))
                st.markdown(f"- {finding['statement']}  \n  _{label}_")
                if finding.get("quote"):
                    st.caption(f"“{finding['quote']}”")

    section_header("Skill gap")
    st.caption(
        "Required, preferred and incidental mentions are kept apart, and a skill that only "
        "shares a name with one of yours is reported as such rather than counted as a match."
    )
    skills = explanation.get("skills", [])
    if not skills:
        st.caption("This listing names no skills, so there is no gap to report.")
        return
    rows = sorted(
        skills,
        key=lambda item: (
            SKILL_STATUS_ORDER.index(item["status"])
            if item["status"] in SKILL_STATUS_ORDER
            else len(SKILL_STATUS_ORDER)
        ),
    )
    st.dataframe(
        [
            {
                "skill": row["skill"],
                "status": SKILL_STATUS_LABELS.get(row["status"], row["status"]),
                "listing says": row.get("evidence_class") or "not mentioned",
                "evidence": row.get("quote") or "—",
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )


def render() -> None:
    st.title("Job detail and match explanation")
    client = get_client()

    try:
        recent = client.list_jobs(limit=100, sort_by="score", descending=True)
    except ApiClientError as exc:
        api_error(exc)
        return

    if recent["total"] == 0:
        empty_state(
            "No jobs to inspect",
            "Import jobs on the **Job discovery** page first.",
            "Go to Job discovery.",
        )
        return

    options = {
        f"#{item['id']} · {item['title']} @ {item['company']}": item["id"]
        for item in recent["items"]
    }
    default_index = 0
    pending = st.session_state.get("detail_job_id")
    linked = st.query_params.get("job_id")
    if linked and str(linked).isdigit():
        # Deep link, e.g. from the capture extension: /job?job_id=42.
        pending = int(str(linked))
    if pending in options.values():
        default_index = list(options.values()).index(pending)

    chosen = st.selectbox("Job", list(options), index=default_index)
    job_id = options[chosen]

    try:
        job = client.get_job(job_id)
    except ApiClientError as exc:
        api_error(exc)
        return

    match = job.get("match") or {}

    st.markdown(f"## {job['title']}")
    st.markdown(f"### {job['company']}")
    ring, cards = st.columns([1, 6])
    with ring:
        st.markdown(
            score_ring(match.get("total_score"), match.get("band", ""), size=84),
            unsafe_allow_html=True,
        )
        if match:
            st.markdown(
                confidence_badge(match.get("confidence", ""), match.get("evidence_coverage")),
                unsafe_allow_html=True,
            )
    with cards:
        coverage = match.get("evidence_coverage")
        metric_row(
            [
                ("Match score", match.get("total_score", "—"), "relevance only"),
                ("Band", match.get("band", "not scored"), ""),
                ("Confidence", match.get("confidence", "—"), "strength of evidence"),
                (
                    "Evidence coverage",
                    f"{float(coverage) * 100:.0f}%" if coverage is not None else "—",
                    "share of weight assessable",
                ),
                ("Status", job["status"], ""),
                ("Platforms", len(job["source_references"]), "sightings"),
            ]
        )

    facts = st.columns(2)
    with facts[0]:
        st.markdown("**Listing facts (as provided by the source)**")
        st.markdown(
            f"- Location: {job.get('location') or 'not stated'}\n"
            f"- Work arrangement: `{job['work_arrangement']}`\n"
            f"- Employment type: `{job['employment_type']}`\n"
            f"- Salary: {job.get('salary_raw') or 'not disclosed'}\n"
            f"- Experience asked: {job.get('experience_raw') or 'not stated'}\n"
            f"- Application method: `{job['application_method']}`"
        )
    with facts[1]:
        st.markdown("**Dates**")
        posted = (
            f"{local_time(job['posted_at'])}"
            + (
                " _(approximate, derived from a relative date)_"
                if job["posted_at_is_approximate"]
                else ""
            )
            if job.get("posted_at")
            else "**not provided by the source**"
        )
        st.markdown(
            f"- Posted: {posted}\n"
            f"- Discovered by this app: {local_time(job['discovered_at'])}\n"
            f"- Fingerprint: `{job['fingerprint'][:16]}…`"
        )
        if not job.get("posted_at"):
            st.caption(
                "Discovery time is never used as a stand-in for the posting date, so "
                "freshness is excluded from this job's score."
            )

    st.markdown("**Seen on these platforms**")
    st.dataframe(
        [
            {
                "source": reference["source"],
                "external id": reference["external_id"] or "—",
                "retrieved": local_time(reference["retrieved_at"]),
                "method": reference["retrieval_method"],
                "url": reference["url"] or "—",
            }
            for reference in job["source_references"]
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.divider()
    section_header("Match explanation")
    if not match:
        st.info("This job has not been scored. Run scoring from the Job feed page.")
    else:
        st.markdown(category_bars(match.get("category_scores") or {}), unsafe_allow_html=True)
        st.caption(
            "Categories that could not be assessed are given zero weight and the remaining "
            "weights are rescaled, so missing data does not drag the total toward the middle."
        )
        st.markdown("**Evidence behind this score**")
        st.markdown(evidence_block(match), unsafe_allow_html=True)
        st.caption(
            "Relevance and confidence are separate questions. The score is never adjusted "
            "for weak evidence — only the band is held back, so the number stays auditable."
        )
        st.markdown(
            "**You have:** " + skill_chips(match.get("matched_skills") or [], "#d8f0e2"),
            unsafe_allow_html=True,
        )
        st.markdown(
            "**Required but not in your profile:** "
            + skill_chips(match.get("missing_required_skills") or [], "#fde2e1"),
            unsafe_allow_html=True,
        )
        st.markdown(
            "**Preferred but not in your profile:** "
            + skill_chips(match.get("missing_preferred_skills") or [], "#fff3cd"),
            unsafe_allow_html=True,
        )
        if match.get("uncertain_requirements"):
            st.warning(
                "The listing published no explicit requirements list. These were inferred "
                "from its description and should be read as uncertain, not as the "
                "employer's stated requirements: " + ", ".join(match["uncertain_requirements"])
            )
        if match.get("filtered_out"):
            st.error("Excluded by your hard filters: " + "; ".join(match.get("filter_reasons", [])))
        with st.expander("Full reasoning", expanded=False):
            for line in match.get("explanation", []):
                st.markdown(f"- {line}")

        _render_grounded(client, job_id)

    st.divider()
    actions = st.columns([1, 1, 1, 2])
    if actions[0].button("Shortlist", use_container_width=True):
        try:
            client.shortlist(job_id)
            st.rerun()
        except ApiClientError as exc:
            api_error(exc)
    if actions[1].button("Skip", use_container_width=True):
        try:
            client.skip(job_id, reason="skipped from the job detail page")
            st.rerun()
        except ApiClientError as exc:
            api_error(exc)
    if actions[2].button("Prepare application", use_container_width=True):
        st.session_state["prepare_job_id"] = job_id
        st.session_state["goto_page"] = "Review queue"
        st.rerun()
    if job.get("url"):
        actions[3].link_button("Open official listing", job["url"], use_container_width=True)
    else:
        actions[3].caption("No safe link was provided for this job.")

    with st.expander("Full description (treated as untrusted text)"):
        st.caption(
            "This text came from a third party. It is stored and displayed as data only; "
            "instructions inside it are never acted on, and it is fenced before ever "
            "reaching a language model."
        )
        st.text(job.get("description") or "No description was provided.")
