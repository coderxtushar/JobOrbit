"""Application tracker page."""

from __future__ import annotations

from datetime import UTC, date, datetime

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    empty_state,
    get_client,
    local_time,
    metric_row,
    section_header,
)

STATUSES = (
    "SHORTLISTED",
    "READY_FOR_REVIEW",
    "APPROVED",
    "SUBMITTED",
    "CONFIRMED",
    "SUBMISSION_UNKNOWN",
    "SKIPPED",
    "FAILED",
)
OUTCOMES = (
    "pending",
    "no_response",
    "rejected",
    "screening",
    "interviewing",
    "offer",
    "withdrawn",
    "accepted",
)


def render() -> None:
    st.title("Application tracker")
    client = get_client()

    try:
        metrics = client.metrics()
    except ApiClientError as exc:
        api_error(exc)
        return

    metric_row(
        [
            ("Prepared", metrics["applications_prepared"], ""),
            ("Submitted by you", metrics["applications_submitted"], "never automatic"),
            ("Confirmed", metrics["applications_confirmed"], "with evidence"),
            ("In review queue", metrics["review_queue_size"], ""),
        ]
    )
    st.write("")

    filters = st.columns(2)
    statuses = filters[0].multiselect("Status", STATUSES)
    outcomes = filters[1].multiselect("Outcome", OUTCOMES)

    try:
        result = client.list_applications(
            status=statuses or None, outcome=outcomes or None, limit=100
        )
    except ApiClientError as exc:
        api_error(exc)
        return

    if result["total"] == 0:
        empty_state(
            "No applications tracked yet",
            "Prepare one from the **Review queue** page. Applications appear here as soon "
            "as they are prepared, and you record submissions and outcomes against them.",
        )
        return

    st.caption(f"{result['total']} application(s)")
    st.dataframe(
        [
            {
                "id": item["id"],
                "job": item["job_title"],
                "company": item["job_company"],
                "platform": item["platform"],
                "status": item["status"],
                "outcome": item["outcome"],
                "submitted": local_time(item["submitted_at"]) if item["submitted_at"] else "—",
                "confirmed": "yes" if item["confirmed_at"] else "no",
                "follow up": local_time(item["follow_up_date"], "%d %b %Y")
                if item["follow_up_date"]
                else "—",
                "blocking": len(item["blocking_questions"]),
            }
            for item in result["items"]
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.divider()
    section_header("Update one application")
    options = {
        f"#{item['id']} · {item['job_title']} @ {item['job_company']}": item["id"]
        for item in result["items"]
    }
    chosen = st.selectbox("Application", list(options))
    application_id = options[chosen]
    current = next(item for item in result["items"] if item["id"] == application_id)

    with st.form("track_update"):
        columns = st.columns(3)
        outcome = columns[0].selectbox(
            "Outcome",
            OUTCOMES,
            index=OUTCOMES.index(current["outcome"]) if current["outcome"] in OUTCOMES else 0,
        )
        interview_status = columns[1].text_input(
            "Interview stage", value=current["interview_status"]
        )
        follow_up = columns[2].date_input(
            "Follow up on",
            value=(
                datetime.fromisoformat(current["follow_up_date"].replace("Z", "+00:00")).date()
                if current["follow_up_date"]
                else date.today()
            ),
        )
        notes = st.text_area("Notes", value=current["notes"], height=110)

        if st.form_submit_button("Save", type="primary"):
            payload = {
                "outcome": outcome,
                "interview_status": interview_status,
                "notes": notes,
                "follow_up_date": datetime.combine(
                    follow_up, datetime.min.time(), tzinfo=UTC
                ).isoformat(),
            }
            try:
                client.update_application(application_id, payload)
            except ApiClientError as exc:
                api_error(exc)
            else:
                st.success("Saved.")
                st.rerun()
