"""Logs and diagnostics page."""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    get_client,
    local_time,
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
