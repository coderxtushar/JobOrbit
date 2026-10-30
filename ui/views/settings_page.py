"""Settings and platform capabilities page."""

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


def _capability_row(name: str, declared: bool, effective: bool) -> str:
    if not declared:
        return f"- **{name}**: not available for this source"
    state = "on" if effective else "off (you disabled it)"
    return f"- **{name}**: {state}"


def render() -> None:
    st.title("Settings and platform capabilities")
    client = get_client()

    try:
        health = client.health()
        sources = client.list_sources()
    except ApiClientError as exc:
        api_error(exc)
        return

    section_header("Runtime")
    metric_row(
        [
            ("API", health["status"], ""),
            ("Database", health["database_dialect"], ""),
            ("LLM", health["llm_provider"] if health["llm_enabled"] else "none", ""),
            ("Scheduler", "on" if health["scheduler_enabled"] else "off", ""),
        ]
    )
    st.write("")
    if health["loopback_only"]:
        st.success("The API is bound to loopback, so your data is not reachable from the network.")
    else:
        st.warning(
            "The API is not bound to loopback. It requires a bearer token, but prefer "
            "127.0.0.1 for a personal install."
        )
    if not health["llm_enabled"]:
        st.info(
            "No LLM is configured, which is the default. Scoring is rule-based and fully "
            "explained, and cover letters are assembled from your verified facts. Set "
            "`JA_LLM_PROVIDER` and `JA_LLM_API_KEY` if you want AI drafting."
        )

    st.divider()
    section_header("Sources")
    st.caption(
        "A capability can be narrowed here but never widened. Enabling one requires a "
        "documented policy basis in the adapter, recorded in `docs/COMPLIANCE.md`."
    )

    for source in sources:
        with st.container(border=True):
            header = st.columns([3, 1])
            header[0].markdown(f"#### {source['display_name']}")
            header[0].caption(source["policy_basis"])
            badge = (
                "automated discovery"
                if source["capabilities"]["authorized_discovery_enabled"]
                else "import only"
            )
            header[1].markdown(f"`{badge}`")
            header[1].caption(source["status_detail"])

            declared = source["capabilities"]
            effective = source["effective_capabilities"]
            st.markdown(
                "\n".join(
                    [
                        _capability_row(
                            "Manual import",
                            declared["manual_import_enabled"],
                            effective["manual_import_enabled"],
                        ),
                        _capability_row(
                            "Authorized discovery",
                            declared["authorized_discovery_enabled"],
                            effective["authorized_discovery_enabled"],
                        ),
                        _capability_row(
                            "Browser assistance (opens your browser)",
                            declared["browser_assistance_enabled"],
                            effective["browser_assistance_enabled"],
                        ),
                        "- **Automated submission**: permanently off for every source, "
                        "enforced in the adapter, the API schema and the database",
                    ]
                )
            )

            with st.form(f"source_form_{source['source']}"):
                columns = st.columns([1, 1, 1, 1])
                enabled = columns[0].checkbox("Enabled", value=source["enabled"])
                manual = columns[1].checkbox(
                    "Manual import",
                    value=effective["manual_import_enabled"],
                    disabled=not declared["manual_import_enabled"],
                )
                discovery = columns[2].checkbox(
                    "Discovery",
                    value=effective["authorized_discovery_enabled"],
                    disabled=not declared["authorized_discovery_enabled"],
                    help=None
                    if declared["authorized_discovery_enabled"]
                    else source["policy_basis"],
                )
                rate_limit = columns[3].number_input(
                    "Runs per hour", 1, 1000, int(source["rate_limit_per_hour"])
                )
                if st.form_submit_button("Save"):
                    try:
                        client.update_source(
                            source["source"],
                            {
                                "enabled": enabled,
                                "manual_import_enabled": manual,
                                "authorized_discovery_enabled": discovery,
                                "rate_limit_per_hour": int(rate_limit),
                            },
                        )
                    except ApiClientError as exc:
                        api_error(exc)
                    else:
                        st.success("Saved.")
                        st.rerun()

            if source["last_error"]:
                st.error(f"Last error: {source['last_error']}")
            if source["last_run_at"]:
                st.caption(
                    f"Last run {local_time(source['last_run_at'])} · "
                    f"{source['consecutive_failures']} consecutive failure(s)"
                )

            with st.expander("Limitations"):
                for limitation in source["limitations"]:
                    st.caption(f"- {limitation}")

    st.divider()
    section_header("Privacy")
    st.markdown(
        "- Your resume, database and generated artifacts stay in the local `var/` "
        "directory, which is gitignored and created with owner-only permissions.\n"
        "- No platform password or session cookie is ever stored. Email ingestion reads an "
        "app-specific password from the environment per run.\n"
        "- Logs redact secrets and truncate long text, so resume contents never reach a log "
        "file.\n"
        "- To delete everything, stop the app and remove the `var/` directory."
    )
