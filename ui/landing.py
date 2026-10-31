"""Public landing page.

Deliberately inert: it reads configuration, renders markup and nothing else. It does not
call :func:`ui.embedded_api.ensure_api_running`, open a database session or run the demo
seed, so arriving at the root URL costs a template render rather than a migration plus a
scoring pass. The workspace pages start the API on their first render instead.

The only configuration it reads is ``JA_DEMO_MODE``, through the cached settings object,
which touches the environment and ``.env`` and never the database.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.config import get_settings
from app.services.platforms import PLATFORMS
from ui.theme import esc, inject_landing_css, wordmark

HERO_HEADLINE = "Your job search, in orbit."
HERO_SUPPORT = (
    "Discover relevant opportunities. Prepare stronger applications. "
    "Stay in control of every submission."
)
DEMO_BADGE = "Free demo · No account required · Fictional data"

#: Mark colours for the platform strip. Indexed by registry key so a new platform fails
#: loudly in the test rather than silently rendering an unstyled tile.
_MARK_COLOURS: dict[str, str] = {
    "naukri": "#4A6CF7",
    "linkedin": "#0A66C2",
    "indeed": "#2557A7",
    "wellfound": "#1F2937",
    "ats": "#5146E5",
}

_FEATURES: tuple[tuple[str, str, str], ...] = (
    (
        "◎",
        "Ranking you can audit",
        "Six categories, each scored 0–100 with the weight shown. Every job says which "
        "skills matched, which are missing from your profile, and what could not be "
        "assessed at all.",
    ),
    (
        "◇",
        "Confidence, kept separate",
        "Relevance and certainty are different questions. A listing with no requirements "
        "published can look like a strong match and still be impossible to judge, so the "
        "score stays and the confidence drops.",
    ),
    (
        "✎",
        "Applications you'd sign",
        "A truthful resume variant, a cover letter naming the actual role, and answers "
        "drawn only from facts you verified. Anything unknown is flagged, never guessed.",
    ),
    (
        "⧉",
        "Answer once, reuse forever",
        "Notice period, work authorisation, salary — answer each once in the action inbox "
        "and it fills every open application and every future one.",
    ),
    (
        "⊞",
        "A hundred at a time",
        "Bulk preparation runs across your whole shortlist with checkpoints, so it can be "
        "stopped and resumed without preparing anything twice.",
    ),
    (
        "⊘",
        "It never presses Apply",
        "There is no submit endpoint, no code path and no button. The app prepares the "
        "application and opens the employer's own page so you submit it yourself.",
    ),
)

_STEPS: tuple[tuple[str, str], ...] = (
    (
        "Add your resume and confirm what it found",
        "Parsing is a proposal, not a decision. You see every extracted field on an "
        "editable screen and nothing reaches your profile until you accept it.",
    ),
    (
        "Bring jobs in, or let the real APIs fetch them",
        "Import a CSV or paste a URL from any platform. Where a company publishes its own "
        "job-board API — Greenhouse, Lever, Ashby, Workable, SmartRecruiters — JobOrbit can "
        "fetch directly.",
    ),
    (
        "Read the ranking, not just the number",
        'Open "Why this score" on any job for the per-category breakdown, the matched and '
        "missing skills, and the reasons behind its confidence level.",
    ),
    (
        "Prepare, review, and submit yourself",
        "JobOrbit assembles the application and opens the official page. You check it, you "
        "send it, and you record what happened.",
    ),
)


def _nav() -> None:
    links = (
        '<div class="ja-lp-links">'
        '<a href="#features">Features</a>'
        '<a href="#platforms">Platforms</a>'
        '<a href="#how-it-works">How it works</a>'
        '<span class="ja-lp-soon">Sign in · coming soon</span>'
        "</div>"
    )
    st.markdown(f'<div class="ja-lp-nav">{wordmark()}{links}</div>', unsafe_allow_html=True)


def _hero(explore_target: Any) -> None:
    demo = get_settings().demo_mode
    eyebrow = "Local-first job search assistant"
    st.markdown(
        f'<div class="ja-lp-hero">'
        f'<span class="ja-lp-eyebrow">{esc(eyebrow)}</span>'
        f'<h1 class="ja-lp-h1">Your job search, <em>in orbit.</em></h1>'
        f'<p class="ja-lp-sub">{esc(HERO_SUPPORT)}</p>'
        f"</div>",
        unsafe_allow_html=True,
    )

    actions = st.columns([1.05, 1, 2.6], gap="small")
    if actions[0].button("Explore JobOrbit", type="primary", use_container_width=True):
        st.switch_page(explore_target)
    actions[1].link_button("How it works", "#how-it-works", use_container_width=True)

    badge = DEMO_BADGE if demo else "Local-first · Your data stays on your machine"
    st.markdown(
        f'<div class="ja-lp-trust"><b>●</b> {esc(badge)}</div>',
        unsafe_allow_html=True,
    )


def _features() -> None:
    st.markdown(
        '<div id="features"></div>'
        '<div class="ja-lp-sect">What it does</div>'
        '<h2 class="ja-lp-h2">Fewer applications. Better ones.</h2>'
        '<p class="ja-lp-lede">JobOrbit optimises for interviews, not for volume. Every '
        "number it shows can be traced back to something an employer actually published."
        "</p>",
        unsafe_allow_html=True,
    )
    cards = "".join(
        f'<div class="ja-lp-card"><div class="ja-lp-ico">{esc(icon)}</div>'
        f"<h3>{esc(title)}</h3><p>{esc(body)}</p></div>"
        for icon, title, body in _FEATURES
    )
    st.markdown(f'<div class="ja-lp-grid">{cards}</div>', unsafe_allow_html=True)


def _platforms() -> None:
    st.markdown(
        '<div id="platforms"></div>'
        '<div class="ja-lp-sect">Platforms</div>'
        '<h2 class="ja-lp-h2">Every platform, honestly labelled.</h2>'
        '<p class="ja-lp-lede">Each section says exactly how jobs get in. Where a platform '
        "publishes no jobseeker API, or its terms prohibit automated access, JobOrbit says "
        "so and gives you import instead of pretending to search.</p>",
        unsafe_allow_html=True,
    )
    tiles = []
    for platform in PLATFORMS:
        colour = _MARK_COLOURS.get(platform.key, "#5146E5")
        live = platform.key == "ats"
        tag = (
            '<span class="ja-lp-tag live">Live discovery available</span>'
            if live
            else '<span class="ja-lp-tag import">Import-only, by policy</span>'
        )
        tiles.append(
            f'<div class="ja-lp-plat">'
            f'<div class="mark" style="background:{colour}">'
            f"{esc(platform.display_name[0])}</div>"
            f'<div class="body"><div class="name">{esc(platform.display_name)}</div>'
            f'<div class="how">{esc(platform.tagline)}</div>{tag}</div></div>'
        )
    st.markdown(f'<div class="ja-lp-grid two">{"".join(tiles)}</div>', unsafe_allow_html=True)


def _how_it_works() -> None:
    st.markdown(
        '<div id="how-it-works"></div>'
        '<div class="ja-lp-sect">How it works</div>'
        '<h2 class="ja-lp-h2">Four steps, and you hold the last one.</h2>',
        unsafe_allow_html=True,
    )
    steps = "".join(
        f'<div class="ja-lp-step"><div class="n">{index}</div><div>'
        f"<h4>{esc(title)}</h4><p>{esc(body)}</p></div></div>"
        for index, (title, body) in enumerate(_STEPS, start=1)
    )
    st.markdown(steps, unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-lp-note"><b>What it will not do.</b> No platform scraping, no '
        "login bots, no CAPTCHA bypass and no automated submission. Those are not missing "
        "features — LinkedIn, Indeed, Naukri and Wellfound each prohibit them, and the "
        "database carries a constraint that refuses to record the capability at all."
        "</div>",
        unsafe_allow_html=True,
    )


def _footer() -> None:
    demo = get_settings().demo_mode
    right = (
        "Demo data is fictional. Resume upload is disabled here."
        if demo
        else "Running locally. Your resume never leaves this machine."
    )
    st.markdown(
        f'<div class="ja-lp-foot"><div>JobOrbit · a personal job-search assistant</div>'
        f"<div>{esc(right)}</div></div>",
        unsafe_allow_html=True,
    )


def render(explore_target: Any) -> None:
    """Draw the landing page. ``explore_target`` is the workspace page the CTA opens."""
    inject_landing_css()
    _nav()
    _hero(explore_target)
    _features()
    _platforms()
    _how_it_works()
    _footer()
