"""Dashboard entry point.

Run with:
    streamlit run ui/streamlit_app.py

The API must be running separately. Pages are plain functions in ``ui/views`` so the same
backend can be driven by a different frontend later without touching business logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import require_api  # noqa: E402
from ui.embedded_api import ensure_api_running  # noqa: E402
from ui.theme import inject_css  # noqa: E402
from ui.views import (  # noqa: E402
    applications_page,
    batch_page,
    diagnostics_page,
    discovery_page,
    inbox_page,
    job_detail_page,
    jobs_page,
    overview_page,
    resume_page,
    review_page,
    settings_page,
)

PAGES: dict[str, callable] = {
    "Overview": overview_page.render,
    "Resume and profile": resume_page.render,
    "Job discovery": discovery_page.render,
    "Job feed": jobs_page.render,
    "Job detail": job_detail_page.render,
    "Bulk preparation": batch_page.render,
    "Action inbox": inbox_page.render,
    "Review queue": review_page.render,
    "Application tracker": applications_page.render,
    "Settings and sources": settings_page.render,
    "Logs and diagnostics": diagnostics_page.render,
}


def main() -> None:
    st.set_page_config(
        page_title="Job Search Assistant",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    # Rendered as a styled div rather than st.sidebar.title(): that emits an <h1>, which
    # would give every page two top-level headings and break the heading hierarchy for
    # screen readers. The page's own st.title() is the single h1.
    st.sidebar.markdown('<div class="ja-brand">Job Search Assistant</div>', unsafe_allow_html=True)
    st.sidebar.caption("Local-first. Nothing is submitted without you.")

    if "goto_page" in st.session_state:
        st.session_state["nav"] = st.session_state.pop("goto_page")

    choice = st.sidebar.radio("Go to", list(PAGES), key="nav", label_visibility="collapsed")

    # On a single-process host there is no separate API to reach, so start one before the
    # health check rather than showing "API offline" with no way to act on it. A no-op
    # when an API is already configured or already listening.
    api_status = ensure_api_running()

    health = require_api()
    if health is None:
        st.sidebar.error("API offline")
        st.sidebar.caption(f"API: {api_status}")
        return

    if health.get("demo_mode"):
        st.warning(
            "**Public demo with sample data.** The candidate, the listings and the "
            "applications here are fictional, and resume upload is disabled: a shared "
            "deployment has no per-user login, so one visitor's resume would be readable "
            "by the next. Run it locally with your own resume — the README has the two "
            "commands.",
            icon="🧪",
        )

    st.sidebar.divider()
    st.sidebar.markdown(
        f"**API** `{health['status']}`  \n"
        f"**Database** `{health['database_dialect']}`  \n"
        f"**LLM** `{health['llm_provider']}`"
        + ("" if health["llm_enabled"] else " _(rule-based)_")
        + f"  \n**Scheduler** `{'on' if health['scheduler_enabled'] else 'off'}`"
    )
    st.sidebar.divider()
    st.sidebar.info(
        "This app never submits an application. It prepares one and opens the employer's "
        "own page so you submit it yourself."
    )

    PAGES[choice]()


main()
