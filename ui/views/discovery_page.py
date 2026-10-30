"""Job discovery and import page."""

from __future__ import annotations

import json

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    get_client,
    local_time,
    section_header,
)

SOURCE_CHOICES = ("csv", "manual", "linkedin", "indeed", "naukri", "wellfound")

CSV_TEMPLATE = (
    "Job Title,Company Name,Location,Link,Job ID,Source,Key Skills,Experience,Salary,Posted,Job Description\n"
    'Backend Developer,Acme Technologies,"Bengaluru, India",https://example.com/jobs/1,ACME-1,'
    "linkedin,Python|FastAPI|PostgreSQL,0-2 years,6-10 LPA,2 days ago,"
    '"Build REST APIs with Python and FastAPI."\n'
)


def _import_section() -> None:
    client = get_client()
    section_header("Import a file")
    st.caption(
        "This is the discovery path that always works: no credentials, no network access, "
        "no platform cooperation. Column names are matched case-insensitively, so exports "
        "from different boards import without editing."
    )

    columns = st.columns([3, 1])
    uploaded = columns[0].file_uploader(
        "CSV, TSV or JSON file", type=["csv", "tsv", "json"], key="jobs_file"
    )
    source = columns[1].selectbox(
        "Attribute these jobs to",
        SOURCE_CHOICES,
        key="import_source",
        help="Used for deduplication and tracking. A 'Source' column in the file overrides this per row.",
    )

    if st.button("Import file", type="primary"):
        if uploaded is None:
            st.warning("Choose a file first.")
        else:
            try:
                summary = client.import_jobs_file(uploaded.name, uploaded.getvalue(), source)
            except ApiClientError as exc:
                api_error(exc)
            else:
                _show_summary(summary)

    with st.expander("Paste JSON instead"):
        raw = st.text_area(
            "A JSON list of job objects",
            height=170,
            placeholder='[{"source":"linkedin","title":"Backend Developer","company":"Acme",'
            '"url":"https://example.com/jobs/1","location":"Bengaluru"}]',
        )
        if st.button("Import pasted JSON"):
            try:
                records = json.loads(raw)
            except json.JSONDecodeError as exc:
                st.error(f"That is not valid JSON: {exc.msg} on line {exc.lineno}.")
                return
            if not isinstance(records, list):
                st.error("Paste a JSON *list* of job objects.")
                return
            try:
                _show_summary(client.import_jobs_json(records))
            except ApiClientError as exc:
                api_error(exc)

    st.download_button(
        "Download a CSV template",
        CSV_TEMPLATE,
        file_name="job_import_template.csv",
        mime="text/csv",
    )


def _show_summary(summary: dict | list) -> None:
    summaries = summary if isinstance(summary, list) else [summary]
    for item in summaries:
        tone = (
            st.success
            if item["status"] == "success"
            else (st.warning if item["status"] in ("partial", "skipped_unsupported") else st.error)
        )
        tone(
            f"**{item['source']}** — {item['status']}: {item['jobs_created']} new, "
            f"{item['jobs_updated']} enriched, {item['duplicates_detected']} duplicate, "
            f"{item['records_invalid']} invalid."
        )
        if item.get("message") and item["status"] == "skipped_unsupported":
            st.caption(item["message"])
        if item.get("errors"):
            with st.expander(f"{len(item['errors'])} error(s) from this run"):
                for error in item["errors"]:
                    st.caption(f"- {error}")
        if item.get("warnings"):
            with st.expander(f"{len(item['warnings'])} note(s) from this run"):
                for warning in item["warnings"]:
                    st.caption(f"- {warning}")


def _discovery_section() -> None:
    client = get_client()
    section_header("Automated discovery")
    try:
        sources = client.list_sources()
    except ApiClientError as exc:
        api_error(exc)
        return

    discoverable = [
        item for item in sources if item["effective_capabilities"]["authorized_discovery_enabled"]
    ]
    blocked = [item for item in sources if not item["capabilities"]["authorized_discovery_enabled"]]

    if discoverable:
        st.caption("These sources have an authorized interface and are enabled.")
        chosen = st.multiselect(
            "Run discovery for",
            [item["source"] for item in discoverable],
            default=[item["source"] for item in discoverable],
        )
        if st.button("Run discovery now", type="primary"):
            try:
                _show_summary(client.discover(chosen))
            except ApiClientError as exc:
                api_error(exc)
    else:
        st.info(
            "No source currently has automated discovery enabled. The only authorized "
            "discovery path in this build is job-alert email ingestion, which is off by "
            "default — turn it on under **Settings and sources**."
        )

    with st.expander(f"Why {len(blocked)} source(s) cannot be searched automatically"):
        for item in blocked:
            st.markdown(f"**{item['display_name']}**")
            st.caption(item["policy_basis"])
            for limitation in item["limitations"]:
                st.caption(f"- {limitation}")
        st.caption(
            "Full citations are in `docs/COMPLIANCE.md`. This application does not scrape "
            "any platform, by design."
        )


def _history_section() -> None:
    client = get_client()
    section_header("Import history")
    try:
        runs = client.import_runs(limit=25)["items"]
    except ApiClientError as exc:
        api_error(exc)
        return
    if not runs:
        st.caption("No import has run yet.")
        return
    st.dataframe(
        [
            {
                "run": run["id"],
                "source": run["source"],
                "trigger": run["trigger"],
                "status": run["status"],
                "started": local_time(run["started_at"]),
                "received": run["records_received"],
                "new": run["jobs_created"],
                "enriched": run["jobs_updated"],
                "duplicates": run["duplicates_detected"],
                "invalid": run["records_invalid"],
                "message": run["message"],
            }
            for run in runs
        ],
        hide_index=True,
        use_container_width=True,
    )


def render() -> None:
    st.title("Job discovery and imports")
    _import_section()
    st.divider()
    _discovery_section()
    st.divider()
    _history_section()
