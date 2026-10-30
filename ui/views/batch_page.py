"""Bulk preparation page.

Select jobs by score, band, freshness and role, see how many match before committing, then
prepare them all. The run reports progress as it goes because every item is committed as it
completes, and it can be cancelled or resumed from here.

Nothing on this page submits anything. A finished run leaves prepared applications in the
review queue and unanswered questions in the action inbox.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import api_error, empty_state, get_client, local_time, metric_row
from ui.theme import card_anchor, esc, pill, section_header

ITEM_TONE = {
    "prepared": "green",
    "needs_action": "amber",
    "queued": "slate",
    "in_progress": "indigo",
    "skipped_duplicate": "slate",
    "skipped_ineligible": "slate",
    "failed": "red",
    "cancelled": "slate",
}

RUN_TONE = {
    "completed": "green",
    "completed_with_errors": "amber",
    "running": "indigo",
    "cancelling": "amber",
    "cancelled": "slate",
    "interrupted": "amber",
    "failed": "red",
    "pending": "slate",
    "paused": "slate",
}

ACTIVE_STATUSES = {"running", "cancelling", "pending"}


def _selection_controls() -> dict[str, Any]:
    columns = st.columns(4)
    bands = columns[0].multiselect(
        "Match band", ["high", "review", "low"], default=["high", "review"]
    )
    min_score = columns[1].slider("Minimum score", 0, 100, 65)
    max_age = columns[2].number_input(
        "Posted within (days)", min_value=0, max_value=365, value=0, step=1
    )
    limit = columns[3].number_input("Maximum jobs", min_value=1, max_value=5000, value=100)

    titles_raw = st.text_input(
        "Title contains (comma separated, optional)",
        placeholder="backend, python, ai engineer",
    )
    extra = st.columns(2)
    include_unscored = extra[0].checkbox(
        "Include unscored jobs",
        value=False,
        help="Off by default: an unscored job has no ranking, so it cannot be prioritised.",
    )
    include_filtered = extra[1].checkbox(
        "Include jobs your filters excluded",
        value=False,
        help="Each excluded job still shows exactly why it was excluded.",
    )

    return {
        "bands": bands,
        "min_score": float(min_score) if min_score else None,
        "max_age_days": int(max_age) or None,
        "titles": [part.strip() for part in titles_raw.split(",") if part.strip()],
        "include_unscored": include_unscored,
        "include_filtered": include_filtered,
        "limit": int(limit),
    }


def _run_badge(status: str) -> str:
    return pill(status.replace("_", " "), RUN_TONE.get(status, "slate"))


def _render_items(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item["status"], []).append(item)

    order = [
        "failed",
        "needs_action",
        "prepared",
        "skipped_ineligible",
        "skipped_duplicate",
        "queued",
        "in_progress",
        "cancelled",
    ]
    for status in order:
        bucket = grouped.get(status)
        if not bucket:
            continue
        label = status.replace("_", " ")
        expanded = status in {"failed", "needs_action"}
        with st.expander(f"{label} — {len(bucket)}", expanded=expanded):
            st.dataframe(
                [
                    {
                        "Job": item["job_id"],
                        "Title": item["job_title"] or "(removed)",
                        "Company": item["job_company"],
                        "Application": item["application_id"] or "—",
                        "Attempts": item["attempts"],
                        "Needs answers": item["blocking_questions"],
                        "Detail": item["detail"],
                    }
                    for item in bucket
                ],
                use_container_width=True,
                hide_index=True,
            )


def _render_run(run: dict[str, Any]) -> None:
    client = get_client()
    status = run["status"]

    with st.container(border=True):
        card_anchor()
        st.markdown(
            f"**Run {run['id']}** &nbsp; {_run_badge(status)}"
            + (" &nbsp; " + pill("dry run", "indigo") if run["dry_run"] else ""),
            unsafe_allow_html=True,
        )
        metric_row(
            [
                ("Selected", run["total_items"], "jobs in this run"),
                ("Ready for review", run["prepared_count"], "nothing left to answer"),
                ("Needs your answers", run["needs_action_count"], "see the action inbox"),
                ("Skipped", run["skipped_count"], "duplicate or ineligible"),
                ("Failed", run["failed_count"], "each reason is listed"),
            ]
        )

        done = (
            run["prepared_count"]
            + run["needs_action_count"]
            + run["skipped_count"]
            + run["failed_count"]
        )
        total = max(1, run["total_items"])
        st.progress(min(1.0, done / total), text=f"{done} of {run['total_items']} processed")

        st.caption(
            f"Started {local_time(run['started_at'])}"
            + (f" · finished {local_time(run['finished_at'])}" if run["finished_at"] else "")
        )
        if run["message"]:
            st.info(esc(run["message"]))

        actions = st.columns(4)
        if status in ACTIVE_STATUSES and actions[0].button(
            "Stop this run", key=f"cancel-{run['id']}", use_container_width=True
        ):
            try:
                client.cancel_batch(run["id"])
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.warning("Cancellation requested. Jobs already prepared are kept.")
                st.rerun()

        resumable = status in {"interrupted", "cancelled", "completed_with_errors"}
        if resumable and actions[1].button(
            "Resume", key=f"resume-{run['id']}", use_container_width=True
        ):
            try:
                client.resume_batch(run["id"])
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.success("Resumed. Only jobs that never finished are retried.")
                st.rerun()

        if actions[2].button("Refresh", key=f"refresh-{run['id']}", use_container_width=True):
            st.rerun()

        if run["needs_action_count"] and actions[3].button(
            "Open action inbox", key=f"inbox-{run['id']}", use_container_width=True
        ):
            st.session_state["goto_page"] = "Action inbox"
            st.rerun()

    detail = run.get("items")
    if detail is None:
        try:
            detail = client.get_batch(run["id"]).get("items", [])
        except ApiClientError as exc:
            api_error(exc)
            return
    _render_items(detail)


def render() -> None:
    st.title("Bulk preparation")
    st.caption(
        "Prepare many applications in one run. Every application still stops at review — "
        "this page prepares, it never submits."
    )
    client = get_client()

    section_header(
        "Select the jobs", "Narrow by band, score, freshness and title, then check the count."
    )
    selection = _selection_controls()
    payload = {
        "selection": selection,
        "concurrency": 4,
        "max_attempts": 3,
        "dry_run": False,
        "include_cover_letter": True,
        "run_in_background": True,
    }

    tuning = st.columns(4)
    payload["concurrency"] = tuning[0].slider("Workers", 1, 16, 4)
    payload["max_attempts"] = tuning[1].slider("Attempts per job", 1, 10, 3)
    payload["include_cover_letter"] = tuning[2].checkbox("Draft cover letters", value=True)
    payload["dry_run"] = tuning[3].checkbox(
        "Dry run", value=False, help="Report what would happen and write nothing."
    )

    buttons = st.columns([1, 1, 3])
    if buttons[0].button("Count matches", use_container_width=True):
        try:
            preview = client.preview_batch(payload)
        except ApiClientError as exc:
            api_error(exc)
        else:
            if preview["total"]:
                st.success(
                    f"{preview['total']} job(s) match. Jobs you already submitted or "
                    "skipped are excluded automatically."
                )
            else:
                st.warning("No job matches. Loosen the band or score, or score the feed first.")

    if buttons[1].button("Prepare them", type="primary", use_container_width=True):
        try:
            started = client.start_batch(payload)
        except ApiClientError as exc:
            api_error(exc)
        else:
            if started["total_items"] == 0:
                st.warning(started["message"])
            else:
                st.session_state["batch_run_id"] = started["id"]
                st.success(
                    f"Run {started['id']} started over {started['total_items']} job(s). "
                    "Press Refresh to follow it."
                )
                st.rerun()

    st.divider()
    section_header("Runs")
    try:
        runs = client.list_batches(limit=10)["items"]
    except ApiClientError as exc:
        api_error(exc)
        return

    if not runs:
        empty_state(
            "No bulk run yet",
            "Pick a selection above and press Prepare them. A run of a hundred jobs takes "
            "a few minutes and can be stopped at any point.",
        )
        return

    focus = st.session_state.get("batch_run_id")
    ordered = sorted(runs, key=lambda run: run["id"] != focus)
    for run in ordered[:5]:
        try:
            _render_run(client.get_batch(run["id"]))
        except ApiClientError as exc:
            api_error(exc)
