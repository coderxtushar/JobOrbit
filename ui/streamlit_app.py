"""JobOrbit entry point.

Run with:
    streamlit run ui/streamlit_app.py

Two surfaces share one Streamlit app:

* the **landing page** at the root URL, which touches nothing — no API, no database, no
  demo seed — so arriving costs a template render;
* the **workspace**, whose pages are the operational dashboard.

Routing uses ``st.navigation``, so every page has a real URL that survives a refresh, a
bookmark and the browser's back button. Pages are plain ``render()`` functions in
``ui/views``, wrapped by :func:`_workspace` which supplies the shared chrome and starts the
API on first use. That wrapper is the only place the API is started, which is what keeps
the landing page inert.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui import landing  # noqa: E402
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
    platform_page,
    resume_page,
    review_page,
    searches_page,
    settings_page,
)

st.set_page_config(
    page_title="JobOrbit",
    page_icon="🪐",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar_status() -> dict | None:
    """Shared sidebar chrome. Returns the health payload, or ``None`` if the API is down."""
    st.sidebar.markdown(
        '<div class="ja-brand">Job<span style="color:#8B82F0">Orbit</span></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Local-first. Nothing is submitted without you.")

    health = require_api()
    if health is None:
        st.sidebar.error("API offline")
        return None

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
        "JobOrbit never submits an application. It prepares one and opens the employer's "
        "own page so you submit it yourself."
    )
    return health


def _workspace(render: Callable[[], None]) -> Callable[[], None]:
    """Wrap a view with the workspace chrome, starting the API on first use.

    Every workspace page goes through here, so the embedded API is started lazily by
    whichever page the visitor opens first — including when they deep-link straight to one.
    """

    def _page() -> None:
        inject_css()
        api_status = ensure_api_running()
        health = _sidebar_status()
        if health is None:
            st.sidebar.caption(f"API: {api_status}")
            st.error(
                "The dashboard cannot reach its API. Locally, start it with "
                "`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`."
            )
            return
        if health.get("demo_mode"):
            st.warning(
                "**Public demo with sample data.** The candidate, the listings and the "
                "applications here are fictional, and resume upload is disabled: a shared "
                "deployment has no per-user login, so one visitor's resume would be "
                "readable by the next. Run it locally with your own resume — the README "
                "has the two commands.",
                icon="🧪",
            )
        render()

    return _page


def _platform(key: str) -> Callable[[], None]:
    return _workspace(lambda: platform_page.render(key))


LANDING = st.Page(
    lambda: landing.render(OVERVIEW),
    title="JobOrbit",
    icon=":material/rocket_launch:",
    url_path="home",
    default=True,
)

OVERVIEW = st.Page(
    _workspace(overview_page.render),
    title="Overview",
    icon=":material/dashboard:",
    url_path="overview",
)

_MAIN = [
    OVERVIEW,
    st.Page(
        _workspace(resume_page.render),
        title="Resume and profile",
        icon=":material/description:",
        url_path="resume",
    ),
    st.Page(
        _workspace(discovery_page.render),
        title="Job discovery",
        icon=":material/search:",
        url_path="discovery",
    ),
    st.Page(
        _workspace(jobs_page.render), title="Job feed", icon=":material/list:", url_path="jobs"
    ),
    st.Page(
        _workspace(job_detail_page.render),
        title="Job detail",
        icon=":material/article:",
        url_path="job",
    ),
    st.Page(
        _workspace(searches_page.render),
        title="Saved searches",
        icon=":material/bookmark:",
        url_path="searches",
    ),
]

_PLATFORMS = [
    st.Page(_platform("naukri"), title="Naukri", icon=":material/work:", url_path="naukri"),
    st.Page(_platform("linkedin"), title="LinkedIn", icon=":material/work:", url_path="linkedin"),
    st.Page(_platform("indeed"), title="Indeed", icon=":material/work:", url_path="indeed"),
    st.Page(
        _platform("wellfound"), title="Wellfound", icon=":material/work:", url_path="wellfound"
    ),
    st.Page(_platform("ats"), title="ATS & other platforms", icon=":material/hub:", url_path="ats"),
]

_APPLICATIONS = [
    st.Page(
        _workspace(batch_page.render),
        title="Bulk preparation",
        icon=":material/layers:",
        url_path="bulk",
    ),
    st.Page(
        _workspace(inbox_page.render),
        title="Action inbox",
        icon=":material/inbox:",
        url_path="inbox",
    ),
    st.Page(
        _workspace(review_page.render),
        title="Review queue",
        icon=":material/fact_check:",
        url_path="review",
    ),
    st.Page(
        _workspace(applications_page.render),
        title="Application tracker",
        icon=":material/track_changes:",
        url_path="tracker",
    ),
]

_SYSTEM = [
    st.Page(
        _workspace(settings_page.render),
        title="Settings and sources",
        icon=":material/settings:",
        url_path="settings",
    ),
    st.Page(
        _workspace(diagnostics_page.render),
        title="Logs and diagnostics",
        icon=":material/monitor_heart:",
        url_path="diagnostics",
    ),
]

#: Section order is the sidebar order. "" groups the landing link with no heading above it,
#: so the workspace sidebar does not open with a one-item section called "Home".
SECTIONS: dict[str, list] = {
    "": [LANDING],
    "Main": _MAIN,
    "Platform assistants": _PLATFORMS,
    "Applications": _APPLICATIONS,
    "System": _SYSTEM,
}

#: Every page the app serves, used by the navigation tests to assert nothing was dropped
#: in a restructure.
ALL_PAGES: list = [page for pages in SECTIONS.values() for page in pages]

# expanded=True because the default collapses anything past the tenth page behind a
# "View 7 more" button, which hid the whole Applications and System sections — including
# the Review queue and Settings. An operational sidebar has to show its sections.
st.navigation(SECTIONS, expanded=True).run()
