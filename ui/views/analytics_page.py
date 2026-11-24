"""Job-search analytics.

Three separate groups, never blended into one headline number: what was found, how much of
it can be trusted, and what actually happened. Outcome figures are counted from the
applications the user recorded, so a search with no interviews reads as no interviews.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    empty_state,
    get_client,
    metric_row,
    section_header,
)


def _counts_table(title: str, counts: dict[str, int], empty: str) -> None:
    st.markdown(f"**{title}**")
    if not counts:
        st.caption(empty)
        return
    st.dataframe(
        [
            {"name": str(name).replace("_", " "), "count": count}
            for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        ],
        hide_index=True,
        use_container_width=True,
    )


def _discovery(data: dict[str, Any]) -> None:
    section_header("Discovery")
    metric_row(
        [
            ("Jobs stored", data["jobs_total"], "unique after merging"),
            ("Scored", data["jobs_scored"], "against your profile"),
            ("Unscored", data["jobs_unscored"], "run Score all jobs"),
            ("Failed import runs", data["import_runs_failed"], "see diagnostics"),
        ]
    )

    by_day = data.get("new_by_day") or {}
    st.markdown(f"**Newly discovered, last {data['window_days']} days**")
    if not by_day:
        st.caption(
            "No jobs were discovered in this window. Discovery counts when the app first "
            "saw a listing, not when the employer posted it."
        )
    else:
        st.bar_chart(
            {"jobs": dict(sorted(by_day.items()))},
            use_container_width=True,
        )

    _counts_table(
        "Top sources",
        data.get("jobs_by_source") or {},
        "No source has contributed a job yet.",
    )
    st.caption(
        "A job seen on several platforms counts once per platform here, so this total can "
        "exceed the de-duplicated job count above."
    )


def _quality(data: dict[str, Any]) -> None:
    section_header("Quality of what was found")
    freshness = data.get("freshness") or {}
    metric_row(
        [
            ("Duplicate rate", f"{data['duplicate_rate']:g}%", "sightings merged"),
            ("Cross-source", f"{data['cross_source_rate']:g}%", "same job, two platforms"),
            ("Merge suspects", data["false_merge_suspects"], "need a human look"),
            ("Stale rate", f"{data['stale_rate']:g}%", f"older than {data['max_job_age_days']}d"),
            ("Undated", f"{data['undated_rate']:g}%", "source gave no posting date"),
        ]
    )
    st.caption(
        "The stale rate is measured only over listings that carry a posting date. Undated "
        "listings are counted separately and never assumed to be either current or stale."
    )

    left, right = st.columns(2)
    with left:
        _counts_table(
            "Recommendation bands",
            data.get("band_counts") or {},
            "Nothing has been scored yet.",
        )
    with right:
        _counts_table(
            "Evidence confidence",
            data.get("confidence_counts") or {},
            "Nothing has been scored yet.",
        )
    st.caption(
        f"Filtered out with a stated reason: {data['filtered_out']}. "
        f"Dated listings current: {freshness.get('current', 0)} · "
        f"stale: {freshness.get('stale', 0)} · undated: {freshness.get('undated', 0)}."
    )

    st.markdown("**Recommendation precision**")
    if data.get("labelled_precision") is None:
        st.info(data.get("labelled_precision_note") or "Not measured.")
    else:
        st.metric("precision", f"{data['labelled_precision']:.2f}")


def _outcomes(data: dict[str, Any], demo_mode: bool) -> None:
    section_header("What actually happened")
    if demo_mode:
        st.warning(
            "These outcome figures come from the fictional demo data in your own private "
            "copy. They are not a record of anyone's real job search."
        )
    metric_row(
        [
            ("Applications", data["prepared"], "prepared in total"),
            ("Marked submitted", data["marked_submitted"], "recorded by you"),
            ("Confirmed", data["confirmed"], "with evidence"),
            ("Interviews", data["interviews"], "from the outcome field"),
            ("Offers", data["offers"], "from the outcome field"),
        ]
    )
    st.caption(
        "An application counts as submitted only when you recorded it, or when an "
        "auto-apply attempt read the employer's own confirmation. A click is never counted."
    )

    section_header("Review queue")
    waiting_days = data.get("oldest_waiting_days")
    metric_row(
        [
            ("Waiting for you", data["review_queue_size"], "ready or approved"),
            (
                "Longest wait",
                f"{waiting_days:g} days" if waiting_days is not None else "—",
                "oldest unreviewed",
            ),
            (
                "Oldest id",
                data.get("oldest_waiting_id") or "—",
                "open it in the review queue",
            ),
        ]
    )
    if data["review_engine_hint"]:
        st.info(data["review_engine_hint"])

    left, right = st.columns(2)
    with left:
        _counts_table(
            "Applications by status",
            data.get("applications_by_status") or {},
            "You have not prepared an application yet.",
        )
    with right:
        _counts_table(
            "Applications by outcome",
            data.get("applications_by_outcome") or {},
            "No outcome has been recorded yet.",
        )
    _counts_table(
        "Applications by platform",
        data.get("applications_by_source") or {},
        "No application is linked to a platform yet.",
    )


def render() -> None:
    st.title("Job-search analytics")
    client = get_client()

    try:
        report = client.analytics()
    except ApiClientError as exc:
        api_error(exc)
        return

    discovery = report["discovery"]
    if discovery["jobs_total"] == 0:
        empty_state(
            "Nothing to analyse yet",
            "Import or discover some jobs on the **Job discovery** page, then score them.",
            "Go to Job discovery.",
        )
        return

    st.caption(
        "Counted facts only. Nothing on this page is estimated, and outcome figures are "
        "whatever you recorded — never inferred from a click."
    )

    _discovery(discovery)
    st.divider()
    _quality(report["quality"])
    st.divider()

    outcomes = dict(report["outcomes"])
    waiting = outcomes.get("oldest_waiting_days")
    outcomes["review_engine_hint"] = (
        f"Application {outcomes['oldest_waiting_id']} has been waiting "
        f"{waiting:g} days. That is the bottleneck in your pipeline."
        if waiting is not None and waiting >= 7
        else ""
    )
    _outcomes(outcomes, bool(report.get("demo_mode")))
    st.divider()
    _pipeline(client)


def _pipeline(client: Any) -> None:
    """Submission funnel, conversion and segment performance, from recorded data only."""
    section_header("Submissions and outcomes")
    try:
        data = client.outcome_analytics()
    except (ApiClientError, AttributeError):
        st.caption("Outcome analytics are unavailable from this API.")
        return
    funnel = data.get("funnel") or {}
    metric_row(
        [
            ("Submission attempts", funnel.get("submission_attempts", 0), "Submit was pressed"),
            ("Confirmed", funnel.get("confirmed_submissions", 0), "employer acknowledged"),
            ("Unknown outcome", funnel.get("unknown_outcomes", 0), "check before resending"),
            ("Failed", funnel.get("failed_submissions", 0), "rejected after Submit"),
            ("Stopped before Submit", funnel.get("failed_before_submit", 0), "nothing sent"),
        ]
    )
    rates = data.get("rates") or {}
    cells = []
    for key, label in (
        ("interview_rate", "Interview rate"),
        ("offer_rate", "Offer rate"),
        ("confirmation_rate", "Confirmation rate"),
    ):
        entry = rates.get(key) or {}
        value = entry.get("value")
        cells.append(
            (
                label,
                f"{value:g}%" if value is not None else "—",
                entry.get("note") or f"{entry.get('numerator', 0)}/{entry.get('denominator', 0)}",
            )
        )
    saved = data.get("time_saved") or {}
    cells.append(
        (
            "Time saved (estimate)",
            f"{saved.get('estimate_minutes', 0) / 60:.1f} h",
            saved.get("assumption", ""),
        )
    )
    metric_row(cells)
    left, right = st.columns(2)
    with left:
        _segment_table("By source", data.get("by_source") or {})
        _segment_table("By score band", data.get("by_score_band") or {})
    with right:
        _segment_table("By job family", data.get("by_job_family") or {})
        _counts_table(
            "Why attempts stopped",
            data.get("failure_reasons") or {},
            "No attempt has failed or waited on you.",
        )
    _segment_table("Top employers", data.get("by_employer") or {})
    weekly = data.get("weekly") or {}
    if weekly:
        st.markdown("**Weekly (by date submitted and interview round date)**")
        st.bar_chart(
            {week: values.get("sent", 0) for week, values in weekly.items()},
            x_label="week",
            y_label="applications sent",
        )
    freshness = data.get("freshness") or {}
    if freshness.get("median_hours_posted_to_sent") is not None:
        st.caption(
            f"Median {freshness['median_hours_posted_to_sent']:g} hours from posting to sending "
            f"({freshness.get('measured', 0)} measured, "
            f"{freshness.get('undated_postings', 0)} undated postings not counted)."
        )
    for note in data.get("notes") or []:
        st.caption(note)


def _segment_table(title: str, segments: dict[str, dict]) -> None:
    rows = [
        {
            "segment": name,
            "discovered": values.get("discovered", 0),
            "sent": values.get("sent", 0),
            "interviews": values.get("interviews", 0),
            "interview rate": (
                f"{values['interview_rate']:g}%"
                if values.get("interview_rate") is not None
                else "too few to say"
            ),
        }
        for name, values in segments.items()
    ]
    st.markdown(f"**{title}**")
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("No data yet.")
