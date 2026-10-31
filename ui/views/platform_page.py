"""Platform assistant page, rendered for every platform from the same code.

One module serves Naukri, LinkedIn, Indeed, Wellfound and the ATS group. The differences
between them are data — which adapters they cover, what their policy permits — and that
data is read from ``GET /api/platforms/{key}``, so a capability change moves the UI without
a code change.

No business logic lives here. Matching, preparation, review and tracking are reached
through the same endpoints the Job feed and Review queue use; this page filters by source
and links onward. Two things it deliberately does not do:

* **It shows no count it did not receive.** A platform with nothing stored says so.
* **It renders unavailable actions as unavailable** rather than hiding them, because "this
  platform publishes no search API" is information the user needs, and a missing button
  looks like an unfinished feature.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import api_error, empty_state, get_client, job_card, metric_row
from ui.theme import esc, section_header

_STATUS_LABELS: dict[str, str] = {
    "DISCOVERED": "discovered",
    "SCORED": "scored",
    "FILTERED_OUT": "filtered out",
    "SHORTLISTED": "shortlisted",
    "SKIPPED": "skipped",
    "APPLIED": "applied",
}


def _capability_summary(detail: dict[str, Any]) -> None:
    discovery = detail["discovery_source_count"]
    metric_row(
        [
            ("Jobs stored", detail["jobs_stored"], "from this platform"),
            ("Applications", detail["applications"], "prepared for its jobs"),
            ("Adapters", detail["source_count"], "covered by this section"),
            (
                "Automated discovery",
                f"{discovery} of {detail['source_count']}",
                "sources with a published interface",
            ),
        ]
    )


def _how_jobs_arrive(detail: dict[str, Any]) -> None:
    st.markdown(
        f'<div class="ja-note"><b>How jobs get in.</b> {esc(detail["how_jobs_arrive"])}</div>',
        unsafe_allow_html=True,
    )
    for note in detail.get("notes") or []:
        st.caption(f"· {note}")


def _actions(detail: dict[str, Any]) -> None:
    section_header("What you can do here", "Derived from each adapter's declared capabilities.")
    available = [action for action in detail["actions"] if action["available"]]
    blocked = [action for action in detail["actions"] if not action["available"]]

    for action in available:
        st.markdown(f"**✓ {esc(action['label'])}** — {esc(action['description'])}")
    for action in blocked:
        st.markdown(
            f'<div class="ja-meta">✕ <b>{esc(action["label"])}</b> — '
            f"{esc(action['description'])}</div>",
            unsafe_allow_html=True,
        )


def _open_in_platform(detail: dict[str, Any]) -> None:
    template = detail.get("search_url_template") or ""
    homepage = detail.get("homepage") or ""
    if not template and not homepage:
        return

    section_header("Search on the platform", "Opens in a new tab. Nothing is fetched for you.")
    columns = st.columns([3, 1])
    query = columns[0].text_input(
        "Role or keywords",
        value="software engineer",
        key=f"platform_query_{detail['key']}",
        label_visibility="collapsed",
        placeholder="software engineer",
    )
    target = (
        template.replace("{query}", quote(query.strip().replace(" ", "-")))
        if template and query.strip()
        else homepage
    )
    columns[1].link_button("Open", target, use_container_width=True)
    st.caption(
        "Found something? Copy its URL into Job discovery to bring it in, then prepare the "
        "application here."
    )


def _jobs(detail: dict[str, Any], sources: list[str]) -> None:
    client = get_client()
    section_header(
        f"Jobs from {detail['display_name']}",
        "Ranked the same way as the Job feed: band first, then evidence, then score.",
    )
    if detail["jobs_stored"] == 0:
        empty_state(
            "Nothing stored from this platform yet",
            "Bring a listing in through Job discovery — by URL or CSV — and it will appear "
            "here with its score and explanation.",
        )
        return

    status_counts = detail.get("jobs_by_status") or {}
    if status_counts:
        shown = ", ".join(
            f"{count} {_STATUS_LABELS.get(status, status.lower())}"
            for status, count in sorted(status_counts.items(), key=lambda row: -row[1])
        )
        st.caption(shown)

    try:
        page = client.list_jobs(source=sources, limit=10, sort_by="score")
    except ApiClientError as exc:
        api_error(exc)
        return

    for job in page.get("items", []):
        job_card(job, key_prefix=f"plat_{detail['key']}_")
    if page.get("total", 0) > len(page.get("items", [])):
        st.caption(
            f"Showing {len(page['items'])} of {page['total']}. The Job feed has filters, "
            "sorting and pagination across every platform."
        )


def _applications(detail: dict[str, Any]) -> None:
    section_header(
        "Application history",
        "Applications prepared for this platform's jobs. Outcomes are whatever you recorded.",
    )
    by_status = detail.get("applications_by_status") or {}
    if not by_status:
        empty_state(
            "No applications prepared for this platform yet",
            "Prepare one from a job above, review it in the Review queue, then submit it on "
            "the platform yourself.",
        )
        return
    metric_row(
        [
            (status.replace("_", " ").title(), count, "")
            for status, count in sorted(by_status.items())
        ]
    )
    st.caption("Open the Review queue to edit a prepared application, or the tracker for outcomes.")


def _adapters(detail: dict[str, Any]) -> None:
    with st.expander(f"Adapter detail ({detail['source_count']})"):
        st.dataframe(
            [
                {
                    "source": source["source"],
                    "name": source["display_name"],
                    "enabled": source["enabled"],
                    "import": source["effective_capabilities"]["manual_import_enabled"],
                    "auto discovery": source["effective_capabilities"][
                        "authorized_discovery_enabled"
                    ],
                    "auto submission": source["effective_capabilities"][
                        "automated_submission_enabled"
                    ],
                    "jobs": source["jobs_stored"],
                    "last error": source["last_error"][:60],
                }
                for source in detail["sources"]
            ],
            hide_index=True,
            use_container_width=True,
        )
        for source in detail["sources"]:
            st.markdown(f"**{esc(source['display_name'])}** — {esc(source['policy_basis'])}")
            for limitation in source["limitations"]:
                st.caption(f"· {limitation}")


def render(key: str) -> None:
    client = get_client()
    try:
        detail = client.get_platform(key)
    except ApiClientError as exc:
        api_error(exc)
        return

    st.title(detail["display_name"])
    st.caption(detail["tagline"])

    _capability_summary(detail)
    _how_jobs_arrive(detail)

    if not detail["supports_automated_discovery"]:
        st.info(
            "This platform is **import-only by policy**, not because the feature is "
            "unfinished. Nothing here scrapes, logs in, or submits on your behalf.",
            icon="ℹ️",
        )

    _actions(detail)
    _open_in_platform(detail)
    _jobs(detail, [source["source"] for source in detail["sources"]])
    _applications(detail)
    _adapters(detail)
