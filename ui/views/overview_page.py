"""Overview page."""

from __future__ import annotations

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


def render() -> None:
    st.title("Overview")
    client = get_client()

    try:
        metrics = client.metrics()
        estimated = client.estimated_metrics()
    except ApiClientError as exc:
        api_error(exc)
        return

    if metrics["jobs_total"] == 0:
        empty_state(
            "No jobs yet",
            "Nothing has been imported. The fastest start is to upload your resume on "
            "**Resume and profile**, then import a CSV or JSON file of jobs on "
            "**Job discovery**.",
            "Go to Resume and profile.",
        )

    section_header("Counted facts", "Every number here is a count of database rows.")
    metric_row(
        [
            ("Jobs stored", metrics["jobs_total"], ""),
            ("High matches", metrics["match_bands"].get("high", 0), "score 80-100"),
            ("Review queue", metrics["review_queue_size"], "awaiting your review"),
            ("Confirmed", metrics["applications_confirmed"], "with evidence"),
        ]
    )
    st.write("")
    metric_row(
        [
            ("Duplicates detected", metrics["duplicates_detected"], "merged, not dropped"),
            ("Filtered out", metrics["jobs_filtered_out"], "each with a reason"),
            ("Invalid import rows", metrics["records_invalid"], "reported by row"),
            ("Import failures", metrics["import_failures"], ""),
        ]
    )

    st.write("")
    left, right = st.columns(2)
    with left:
        section_header("Jobs by status")
        if metrics["jobs_by_status"]:
            st.dataframe(
                [
                    {"status": key, "count": value}
                    for key, value in sorted(metrics["jobs_by_status"].items())
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No jobs stored yet.")
    with right:
        section_header("Applications by status")
        if metrics["applications_by_status"]:
            st.dataframe(
                [
                    {"status": key, "count": value}
                    for key, value in sorted(metrics["applications_by_status"].items())
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No applications prepared yet.")

    st.divider()
    section_header(
        "Estimates", "Derived from an assumption, not measured. Shown separately on purpose."
    )
    metric_row(
        [("Estimated minutes saved", estimated["estimated_minutes_saved"], "")],
        kind="estimated",
    )
    st.caption(estimated["basis"])

    st.divider()
    try:
        runs = client.import_runs(limit=5)["items"]
    except ApiClientError as exc:
        api_error(exc)
        return

    section_header("Recent imports")
    if not runs:
        st.caption("No import has run yet.")
        return
    st.dataframe(
        [
            {
                "run": run["id"],
                "source": run["source"],
                "status": run["status"],
                "started": local_time(run["started_at"]),
                "new": run["jobs_created"],
                "duplicates": run["duplicates_detected"],
                "invalid": run["records_invalid"],
                "message": run["message"],
            }
            for run in runs
        ],
        hide_index=True,
        use_container_width=True,
    )
