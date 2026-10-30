"""Ranked job feed page."""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    empty_state,
    get_client,
    job_card,
)

STATUSES = (
    "DISCOVERED",
    "SCORED",
    "SHORTLISTED",
    "SKIPPED",
    "FILTERED_OUT",
    "EXPIRED",
    "DUPLICATE",
)
SOURCES = ("manual", "csv", "email_alert", "linkedin", "indeed", "naukri", "wellfound")
SORT_OPTIONS = {
    "Match score": "score",
    "Posted date": "posted_at",
    "Discovery date": "discovered_at",
    "Company": "company",
    "Title": "title",
}
PAGE_SIZE = 10


def render() -> None:
    st.title("Ranked job feed")
    client = get_client()

    header = st.columns([1, 1, 2])
    if header[0].button("Score all jobs", type="primary", use_container_width=True):
        try:
            report = client.score(rescore_all=True)
        except ApiClientError as exc:
            api_error(exc)
        else:
            st.success(
                f"Scored {report['scored']} jobs using the {report['scorer']} scorer: "
                f"{report['high']} high, {report['review']} worth a look, {report['low']} low. "
                f"{report['filtered_out']} were excluded by your filters."
            )
            for failure in report["failures"]:
                st.warning(failure)
    if header[1].button("Score new only", use_container_width=True):
        try:
            report = client.score(rescore_all=False)
        except ApiClientError as exc:
            api_error(exc)
        else:
            st.success(f"Scored {report['scored']} job(s).")

    with st.expander("Search and filters", expanded=True):
        row = st.columns([3, 2, 2])
        search = row[0].text_input("Search title, company or description", key="job_search")
        statuses = row[1].multiselect("Status", STATUSES, default=["SCORED", "SHORTLISTED"])
        sources = row[2].multiselect("Source", SOURCES)

        row = st.columns([2, 2, 2, 2])
        company = row[0].text_input("Company contains")
        min_score = row[1].slider("Minimum score", 0, 100, 0)
        max_age = row[2].number_input("Max age (days, 0 = any)", 0, 3650, 0)
        sort_label = row[3].selectbox("Sort by", list(SORT_OPTIONS))

        row = st.columns(3)
        descending = row[0].checkbox("Descending", value=True)
        include_duplicates = row[1].checkbox(
            "Show duplicate rows",
            value=False,
            help="Duplicates are normally merged into one card showing every platform it appeared on.",
        )
        if row[2].button("Reset filters"):
            for key in ("job_search", "job_page"):
                st.session_state.pop(key, None)
            st.rerun()

    page = st.session_state.get("job_page", 0)
    try:
        result = client.list_jobs(
            search=search or None,
            status=statuses or None,
            source=sources or None,
            company=company or None,
            min_score=min_score or None,
            max_age_days=int(max_age) or None,
            include_duplicates=include_duplicates,
            sort_by=SORT_OPTIONS[sort_label],
            descending=descending,
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
        )
    except ApiClientError as exc:
        api_error(exc)
        return

    total = result["total"]
    if total == 0:
        if search or statuses or sources or company or min_score:
            empty_state(
                "No jobs match these filters",
                "Nothing matched. Widen the filters, or clear the status filter — newly "
                "imported jobs are `DISCOVERED` until you score them.",
                "Press 'Reset filters' or 'Score all jobs'.",
            )
        else:
            empty_state(
                "No jobs stored yet",
                "Import a CSV or JSON file on the **Job discovery** page, then come back "
                "and press 'Score all jobs'.",
                "Go to Job discovery.",
            )
        return

    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    st.caption(f"{total} job(s) · page {page + 1} of {pages}")

    for job in result["items"]:
        job_card(job, key_prefix="feed")

    navigation = st.columns([1, 1, 4])
    if navigation[0].button("Previous", disabled=page == 0, use_container_width=True):
        st.session_state["job_page"] = max(page - 1, 0)
        st.rerun()
    if navigation[1].button("Next", disabled=page + 1 >= pages, use_container_width=True):
        st.session_state["job_page"] = page + 1
        st.rerun()
