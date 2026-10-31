"""Logs and diagnostics page."""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    get_client,
    local_time,
    metric_row,
    section_header,
)


def render() -> None:
    st.title("Logs and diagnostics")
    client = get_client()

    try:
        diagnostics = client.diagnostics()
    except ApiClientError as exc:
        api_error(exc)
        return

    section_header("Why each source is or is not returning jobs")
    for entry in diagnostics["entries"]:
        icon = "✅" if entry["healthy"] else "⛔"
        with st.container(border=True):
            st.markdown(f"{icon} **{entry['display_name']}**")
            st.caption(entry["reason"])
            details = [entry["detail"]]
            if entry["last_run_at"]:
                details.append(f"last run recorded {local_time(entry['last_run_at'])}")
            if entry["jobs_last_run"] is not None:
                details.append(f"{entry['jobs_last_run']} new job(s) on the last run")
            st.caption(" · ".join(details))

    st.divider()
    section_header("Environment")
    st.json(
        {
            "llm_provider": diagnostics["llm_provider"],
            "llm_enabled": diagnostics["llm_enabled"],
            "scheduler_enabled": diagnostics["scheduler_enabled"],
            "database_dialect": diagnostics["database_dialect"],
            "api_bound_to_loopback": diagnostics["api_bound_to_loopback"],
            "display_timezone": diagnostics["display_timezone"],
            "timestamps_stored_in": "UTC",
        }
    )

    st.divider()
    section_header(
        "Cross-source duplication",
        "How often the same posting arrived from more than one source, and where the "
        "merge may have gone wrong.",
    )
    try:
        duplication = client.duplication_metrics()
    except ApiClientError as exc:
        api_error(exc)
    else:
        if duplication["jobs_total"] == 0:
            st.caption("No jobs stored yet, so there is nothing to measure.")
        else:
            metric_row(
                [
                    ("Stored jobs", duplication["jobs_total"], "after merging"),
                    ("Sightings", duplication["sightings_total"], "one per source per job"),
                    (
                        "Duplicate rate",
                        f"{duplication['duplicate_rate'] * 100:.1f}%",
                        "sightings that merged into an existing job",
                    ),
                    (
                        "Multi-source jobs",
                        duplication["multi_source_jobs"],
                        f"{duplication['cross_source_duplicate_rate'] * 100:.1f}% of stored jobs",
                    ),
                ]
            )
            metric_row(
                [
                    (
                        "Exact duplicates",
                        duplication["exact_duplicate_sightings"],
                        "matched on source id or canonical URL",
                    ),
                    (
                        "Fuzzy duplicates",
                        duplication["fuzzy_duplicate_sightings"],
                        "matched on the normalized fingerprint",
                    ),
                    (
                        "Possible missed merges",
                        len(duplication["missed_merge_suspects"]),
                        "near-identical jobs kept separate",
                    ),
                    (
                        "Possible false merges",
                        len(duplication["false_merge_suspects"]),
                        "one job whose sightings disagree",
                    ),
                ]
            )
            st.caption(
                f"{duplication['jobs_with_application']} stored job(s) have an application "
                f"recorded against them, {duplication['multi_source_jobs_with_application']} "
                "of those on a merged listing. Merging is additive: it never deletes a job, "
                "a sighting or an application record."
            )

            if duplication["source_pair_overlaps"]:
                with st.expander("Which source pairs overlap"):
                    st.dataframe(
                        [
                            {"source pair": pair.replace("+", " + "), "shared jobs": count}
                            for pair, count in duplication["source_pair_overlaps"].items()
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )

            if duplication["false_merge_suspects"]:
                st.warning(
                    "These jobs merged sightings that disagree about the role. Open each on "
                    "the Job detail page and check the platforms listed."
                )
                st.dataframe(
                    [
                        {
                            "job": suspect["job_id"],
                            "stored title": suspect["stored_title"],
                            "titles seen": " | ".join(suspect["observed_titles"]),
                            "sources": ", ".join(suspect["sources"]),
                            "why": suspect["reason"],
                        }
                        for suspect in duplication["false_merge_suspects"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

            if duplication["missed_merge_suspects"]:
                with st.expander(
                    f"Possible missed merges ({len(duplication['missed_merge_suspects'])})"
                ):
                    st.caption(
                        "Reported, never merged automatically. A company can legitimately "
                        "post two near-identical roles, so this is a prompt to look, not a "
                        "verdict."
                    )
                    st.dataframe(
                        [
                            {
                                "jobs": " / ".join(str(item) for item in suspect["job_ids"]),
                                "company": suspect["company"],
                                "titles": " | ".join(suspect["titles"]),
                                "title overlap": f"{suspect['title_overlap'] * 100:.0f}%",
                                "why": suspect["reason"],
                            }
                            for suspect in duplication["missed_merge_suspects"]
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )

            if duplication["normalization_collisions"]:
                st.warning(
                    "Company-name normalization has collapsed names that may belong to "
                    "different employers, which would merge unrelated jobs."
                )
                st.dataframe(
                    [
                        {
                            "normalized to": collision["normalized_company"],
                            "raw names": " | ".join(collision["raw_companies"]),
                            "jobs": collision["job_count"],
                        }
                        for collision in duplication["normalization_collisions"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            elif duplication["jobs_total"]:
                st.caption(
                    "No company-name collisions: every normalized employer key maps to names "
                    "that differ only by a legal suffix."
                )

            for skipped in duplication["buckets_skipped"]:
                st.caption(
                    f"Pair search skipped for {skipped}: the bucket is too large to compare "
                    "exhaustively in a request."
                )

    st.divider()
    section_header("Audit trail")
    columns = st.columns([2, 1])
    action = columns[0].text_input(
        "Filter by action", placeholder="jobs.import, application.prepared"
    )
    limit = columns[1].number_input("Rows", 10, 200, 50)

    try:
        logs = client.audit_logs(limit=int(limit), action=action or None)
    except ApiClientError as exc:
        api_error(exc)
        return

    if logs["total"] == 0:
        st.caption("No audit entries match.")
        return

    st.caption(f"{logs['total']} entr(ies) recorded")
    st.dataframe(
        [
            {
                "when": local_time(entry["created_at"]),
                "action": entry["action"],
                "entity": f"{entry['entity_type']}#{entry['entity_id']}"
                if entry["entity_type"]
                else "—",
                "actor": entry["actor"],
                "detail": str(entry["detail"])[:170],
            }
            for entry in logs["items"]
        ],
        hide_index=True,
        use_container_width=True,
    )
