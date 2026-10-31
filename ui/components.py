"""Shared dashboard components."""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from ui.api_client import ApiClient, ApiClientError
from ui.theme import (
    AMBER_100,
    BANDS,
    GREEN_100,
    INDIGO_100,
    SLATE_100,
    card_anchor,
    category_bars,
    confidence_badge,
    esc,
    evidence_block,
    inject_css,
    metric_card,
    monogram,
    pill,
    pills,
    score_ring,
    section_header,
    skill_row,
    unassessable_fields,
)

#: Retained for callers and tests that expect (label, colour) per band.
BAND_STYLE: dict[str, tuple[str, str]] = {
    band: (label, solid) for band, (label, solid, _pale) in BANDS.items()
}

STATUS_LABELS: dict[str, str] = {
    "DISCOVERED": "New",
    "SCORED": "Scored",
    "SHORTLISTED": "Shortlisted",
    "SKIPPED": "Skipped",
    "FILTERED_OUT": "Filtered out",
    "EXPIRED": "Expired",
    "DUPLICATE": "Duplicate",
}

STATUS_TONES: dict[str, str] = {
    "DISCOVERED": "indigo",
    "SCORED": "indigo",
    "SHORTLISTED": "green",
    "SKIPPED": "slate",
    "FILTERED_OUT": "amber",
    "EXPIRED": "slate",
    "DUPLICATE": "slate",
}

__all__ = [
    "BAND_STYLE",
    "STATUS_LABELS",
    "api_error",
    "band_badge",
    "category_bars",
    "confidence_badge",
    "demo_session_key",
    "display_timezone",
    "empty_state",
    "evidence_block",
    "get_client",
    "inject_css",
    "job_card",
    "local_date",
    "local_time",
    "metric_card",
    "metric_row",
    "pill",
    "require_api",
    "score_ring",
    "section_header",
    "skill_chips",
    "unassessable_fields",
]


def display_timezone() -> ZoneInfo:
    name = os.environ.get("JA_DISPLAY_TIMEZONE", "Asia/Kolkata")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_time(value: str | None, fmt: str = "%d %b %Y, %H:%M") -> str:
    """Render a UTC ISO timestamp in the configured display timezone.

    Storage is UTC everywhere; conversion happens only here, at the edge.
    """
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone(display_timezone()).strftime(fmt)


def local_date(value: str | None) -> str:
    return local_time(value, "%d %b %Y")


_DEMO_SESSION_STATE_KEY = "_joborbit_demo_session"


def demo_session_key() -> str:
    """An unguessable key identifying this browser session's copy of the demo data.

    Minted per Streamlit session, which is per browser tab, so two visitors never share a
    demo database. This is **isolation, not authentication**: the key proves nothing about
    who is calling, it only keeps two honest visitors apart. Every row it protects is
    fictional, which is why resume upload stays refused outright rather than isolated.
    """
    existing = st.session_state.get(_DEMO_SESSION_STATE_KEY)
    if isinstance(existing, str) and existing:
        return existing
    minted = secrets.token_urlsafe(32)
    st.session_state[_DEMO_SESSION_STATE_KEY] = minted
    return minted


def get_client() -> ApiClient:
    """The API client for this browser session.

    Deliberately not ``st.cache_resource``: that cache is process-wide, so every visitor
    would share one client and therefore one demo session key, which is the isolation bug
    this exists to prevent. Constructing it is a dataclass instantiation.
    """
    return ApiClient.from_env(demo_session=demo_session_key())


def api_error(exc: ApiClientError) -> None:
    """Show an API error with its actionable message and any field details."""
    st.error(exc.message)
    if exc.field_errors:
        for field, problems in exc.field_errors.items():
            st.caption(f"**{field}**: {'; '.join(problems)}")


def empty_state(title: str, body: str, action: str = "") -> None:
    st.info(f"**{title}**\n\n{body}" + (f"\n\n**Next:** {action}" if action else ""))


def require_api() -> dict | None:
    """Check the API is reachable, rendering a clear message if it is not."""
    try:
        return get_client().health()
    except ApiClientError as exc:
        st.error(exc.message)
        st.code(
            "cd 'Auto apply bot'\n"
            ".venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
            language="bash",
        )
        return None


def band_badge(band: str, score: float) -> str:
    """A compact score pill. The band word is always present, not just its colour."""
    label, solid, pale = BANDS.get(band, ("Unscored", "#6B7486", SLATE_100))
    return (
        f"<span class='ja-pill' style='background:{pale};color:{solid};font-weight:650'>"
        f"{score:g} · {esc(label)}</span>"
    )


def skill_chips(skills: list[str], colour: str) -> str:
    """Render skills as pills.

    ``colour`` is mapped onto a design token rather than used literally, so every skill
    row across the app draws from the same palette. Missing skills resolve to amber, never
    red: an absent skill is a gap in the profile, not a judgement about the person.
    """
    tone_by_colour = {
        GREEN_100: "green",
        "#d8f0e2": "green",
        AMBER_100: "amber",
        "#fde2e1": "amber",
        "#fff3cd": "amber",
        INDIGO_100: "indigo",
        "#dbe9fb": "indigo",
    }
    return pills(skills, tone_by_colour.get(colour, "slate"))


def metric_row(items: list[tuple[str, Any, str]], kind: str = "counted") -> None:
    """Render a row of KPI cards from (label, value, caption) tuples."""
    if not items:
        return
    columns = st.columns(len(items))
    for column, (label, value, caption) in zip(columns, items, strict=False):
        with column:
            st.markdown(metric_card(label, value, caption, kind), unsafe_allow_html=True)


def _header_html(job: dict[str, Any]) -> str:
    sources = sorted({reference["source"] for reference in job.get("source_references", [])})
    chips = [
        pill(job.get("work_arrangement") or "unknown", "indigo"),
        pill((job.get("employment_type") or "unknown").replace("_", " "), "slate"),
    ]
    status = job.get("status", "")
    chips.append(pill(STATUS_LABELS.get(status, status), STATUS_TONES.get(status, "slate")))

    meta: list[str] = []
    if job.get("posted_at"):
        approximate = " (approx.)" if job.get("posted_at_is_approximate") else ""
        meta.append(f"Posted {esc(local_date(job['posted_at']))}{approximate}")
    else:
        meta.append("Posted date not provided by the source")
    meta.append(f"Discovered {esc(local_date(job.get('discovered_at')))}")
    meta.append("Sources: " + esc(", ".join(sources)))
    if len(sources) > 1:
        meta.append(f"<strong>Same job seen on {len(sources)} platforms</strong>")
    if job.get("salary_raw"):
        meta.append(f"Salary: {esc(job['salary_raw'])}")
    if job.get("experience_raw"):
        meta.append(f"Experience: {esc(job['experience_raw'])}")

    return (
        f'<div class="ja-row">{monogram(job.get("company", ""))}'
        f'<div style="flex:1">'
        f'<div class="ja-title">{esc(job.get("title", ""))}</div>'
        f'<div class="ja-sub">{esc(job.get("company", ""))} · '
        f"{esc(job.get('location') or 'location not stated')}</div>"
        f"<div>{''.join(chips)}</div>"
        f'<div class="ja-meta">{" · ".join(meta)}</div>'
        f"</div></div>"
    )


def job_card(job: dict[str, Any], *, key_prefix: str = "", on_change=None) -> None:
    """Render one job with its match explanation and actions."""
    match = job.get("match") or {}
    score = match.get("total_score")
    band = match.get("band", "")

    with st.container(border=True):
        card_anchor()
        body, ring = st.columns([6, 1])
        with body:
            st.markdown(_header_html(job), unsafe_allow_html=True)
        with ring:
            st.markdown(score_ring(score, band), unsafe_allow_html=True)
            if match:
                st.markdown(
                    confidence_badge(match.get("confidence", ""), match.get("evidence_coverage")),
                    unsafe_allow_html=True,
                )

        if match:
            rows = [skill_row("You have", match.get("matched_skills") or [], "green")]
            if match.get("missing_required_skills"):
                rows.append(skill_row("Not in profile", match["missing_required_skills"], "amber"))
            if match.get("uncertain_requirements"):
                rows.append(skill_row("Uncertain", match["uncertain_requirements"], "outline"))
            st.markdown("".join(rows), unsafe_allow_html=True)

            if match.get("uncertain_requirements"):
                st.caption(
                    "Uncertain skills were inferred from the description, not stated by "
                    "the employer."
                )
            if match.get("filtered_out"):
                st.warning(
                    "Excluded by your filters: " + "; ".join(match.get("filter_reasons", []))
                )

        action_columns = st.columns([1, 1, 1, 1, 2])
        with action_columns[0]:
            if st.button("Shortlist", key=f"{key_prefix}sl{job['id']}", use_container_width=True):
                try:
                    get_client().shortlist(job["id"])
                    st.toast(f"Shortlisted {job['title']}")
                    if on_change:
                        on_change()
                    st.rerun()
                except ApiClientError as exc:
                    api_error(exc)
        with action_columns[1]:
            if st.button("Skip", key=f"{key_prefix}sk{job['id']}", use_container_width=True):
                try:
                    get_client().skip(job["id"], reason="skipped from the job feed")
                    st.toast(f"Skipped {job['title']}")
                    if on_change:
                        on_change()
                    st.rerun()
                except ApiClientError as exc:
                    api_error(exc)
        with action_columns[2]:
            if st.button("Details", key=f"{key_prefix}dt{job['id']}", use_container_width=True):
                st.session_state["detail_job_id"] = job["id"]
                st.session_state["goto_page"] = "Job detail"
                st.rerun()
        with action_columns[3]:
            if st.button("Prepare", key=f"{key_prefix}pr{job['id']}", use_container_width=True):
                st.session_state["prepare_job_id"] = job["id"]
                st.session_state["goto_page"] = "Review queue"
                st.rerun()
        with action_columns[4]:
            if job.get("url"):
                st.link_button("Open listing", job["url"], use_container_width=True)
            else:
                st.caption("No safe link was provided by the source.")

        with st.expander("Why this score"):
            if not match:
                st.caption("This job has not been scored yet. Run scoring on the Job feed page.")
            else:
                st.markdown(
                    category_bars(match.get("category_scores") or {}),
                    unsafe_allow_html=True,
                )
                st.markdown(evidence_block(match), unsafe_allow_html=True)
                st.caption(
                    "The score measures relevance; confidence measures how much evidence "
                    "stood behind it. A low-confidence score is never promoted to the high "
                    "band, and the number itself is never adjusted."
                )
                st.caption(
                    "Scores compare the listing against what your profile records. A skill "
                    "missing from your profile is not a judgement that you lack it."
                )
