"""Saved searches and the on-demand new-match digest.

Two controls, and the distinction between them is the point: *Preview* shows what the
search would return and leaves the "last looked" watermark alone, while *Run* marks the
results as seen. Mixing them would mean opening the page cost you the record of what you
had not yet read.
"""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    empty_state,
    get_client,
    job_card,
    local_time,
    metric_row,
    section_header,
)

BANDS = ("high", "review", "low")
SORT_OPTIONS = {
    "Match score": "score",
    "Posted date": "posted_at",
    "Discovery date": "discovered_at",
}
DIGEST_LIMIT = 25


def render() -> None:
    st.title("Saved searches")
    st.caption(
        "A saved search stores your filters, not a snapshot of results, so running it "
        "again reflects the feed as it is now. Nothing runs in the background — JobOrbit "
        "checks only when you ask it to."
    )
    client = get_client()

    try:
        searches = client.list_searches()
    except ApiClientError as exc:
        api_error(exc)
        return

    _create_form(client)

    if not searches:
        empty_state(
            "No saved searches yet",
            "Save the filters you keep retyping — a role family, a band, a freshness "
            "window — and JobOrbit will tell you what is new since you last looked.",
            "Add one above.",
        )
        return

    metric_row(
        [
            ("Saved searches", str(len(searches)), ""),
            (
                "Never run",
                str(sum(1 for entry in searches if not entry.get("last_run_at"))),
                "no watermark yet",
            ),
        ]
    )

    for entry in searches:
        _render_search(client, entry)


def _create_form(client) -> None:
    with st.expander("Save a new search"), st.form("new_saved_search"):
        name = st.text_input("Name", placeholder="Fresher backend in Bengaluru")
        columns = st.columns(2)
        keywords = columns[0].text_input("Keywords", placeholder="backend python")
        company = columns[1].text_input("Company contains", placeholder="")
        columns = st.columns(3)
        bands = columns[0].multiselect("Bands", BANDS, default=["high", "review"])
        min_score = columns[1].slider("Minimum score", 0.0, 100.0, 65.0)
        max_age = columns[2].number_input("Maximum age (days)", 1, 365, 30)
        sort_label = st.selectbox("Sort by", list(SORT_OPTIONS))

        if st.form_submit_button("Save search", type="primary"):
            if not name.strip():
                st.warning("Give the search a name so you can recognise it later.")
                return
            criteria: dict = {
                "bands": bands,
                "min_score": min_score,
                "max_age_days": int(max_age),
                "sort_by": SORT_OPTIONS[sort_label],
            }
            if keywords.strip():
                criteria["search"] = keywords.strip()
            if company.strip():
                criteria["company"] = company.strip()
            try:
                client.create_search(name.strip(), criteria)
            except ApiClientError as exc:
                api_error(exc)
                return
            st.session_state["_saved_search_flash"] = f"Saved '{name.strip()}'."
            st.rerun()

    flash = st.session_state.pop("_saved_search_flash", "")
    if flash:
        st.success(flash)


def _criteria_summary(criteria: dict) -> str:
    """Render the stored filters as a sentence, so a search is recognisable without opening it."""
    parts: list[str] = []
    if criteria.get("search"):
        parts.append(f"keywords “{criteria['search']}”")
    if criteria.get("company"):
        parts.append(f"company contains “{criteria['company']}”")
    if criteria.get("bands"):
        parts.append("bands " + ", ".join(criteria["bands"]))
    if criteria.get("min_score") is not None:
        parts.append(f"score ≥ {criteria['min_score']:g}")
    if criteria.get("max_age_days") is not None:
        parts.append(f"posted within {criteria['max_age_days']} days")
    return " · ".join(parts) if parts else "no filters — the whole feed"


def _render_search(client, entry: dict) -> None:
    last_run = entry.get("last_run_at")
    section_header(
        entry["name"],
        f"Last run {local_time(last_run)}" if last_run else "Never run",
    )
    st.caption(_criteria_summary(entry.get("criteria") or {}))

    columns = st.columns([1, 1, 1, 3])
    preview_clicked = columns[0].button(
        "Preview", key=f"preview-{entry['id']}", use_container_width=True
    )
    run_clicked = columns[1].button(
        "Run", key=f"run-{entry['id']}", type="primary", use_container_width=True
    )
    if columns[2].button("Delete", key=f"delete-{entry['id']}", use_container_width=True):
        try:
            client.delete_search(entry["id"])
        except ApiClientError as exc:
            api_error(exc)
            return
        st.session_state["_saved_search_flash"] = f"Deleted '{entry['name']}'."
        st.rerun()

    if not (preview_clicked or run_clicked):
        _render_digest(st.session_state.pop(_digest_key(entry["id"]), None), previewed=False)
        return

    try:
        digest = (
            client.run_search(entry["id"], limit=DIGEST_LIMIT)
            if run_clicked
            else client.preview_search(entry["id"], limit=DIGEST_LIMIT)
        )
    except ApiClientError as exc:
        api_error(exc)
        return

    if run_clicked:
        # A run advances the "last looked" watermark on the server, but this page read the
        # search list before the click — so the header above still says "Never run". The
        # digest is carried across a rerun rather than drawn here, so the header refreshes
        # and the results survive.
        st.session_state[_digest_key(entry["id"])] = digest
        st.rerun()

    _render_digest(digest, previewed=True)


def _digest_key(search_id: int) -> str:
    return f"_saved_search_digest_{search_id}"


def _render_digest(digest: dict | None, *, previewed: bool) -> None:
    if not digest:
        return
    if previewed:
        st.info("Preview only — this did not mark anything as seen.")

    metric_row(
        [
            ("Matching now", str(digest["total_matching"]), "across the whole feed"),
            (
                "New since last run",
                str(digest["new_since_last_run"]),
                "first run, so everything counts"
                if digest["previous_run_at"] is None
                else f"since {local_time(digest['previous_run_at'])}",
            ),
        ]
    )

    jobs = digest.get("jobs") or []
    if not jobs:
        empty_state(
            "Nothing new",
            f"This search matches {digest['total_matching']} listing(s), but none have "
            "been discovered since you last ran it. Import or discover more jobs and run "
            "it again.",
        )
        return

    for job in jobs:
        job_card(job)
