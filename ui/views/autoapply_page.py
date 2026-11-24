"""Auto-apply page.

Set the scope once, press one button, and the run does discovery, filtering, ranking,
preparation, dispatch where a provider permits it, verification and recording.

The page's main job is to keep two numbers apart. **Prepared** means an application exists,
complete and ready. **Submitted** means a provider acknowledged receipt and returned a
confirmation identifier. Only the second is an application that reached an employer, so the
two are never added together and the submitted figure is captioned with where it came from.

The default is a dry run. A live run needs a current preflight and covers only the jobs
ticked in it, and the emergency stop at the top stops every run before its next Submit.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import api_error, empty_state, get_client, local_time, metric_row
from ui.theme import card_anchor, esc, pill, section_header

STATE_TONE: dict[str, str] = {
    "submitted_confirmed": "green",
    "ready_to_submit": "indigo",
    "prepared": "indigo",
    "eligible": "slate",
    "discovered": "slate",
    "submission_in_progress": "indigo",
    "blocked_missing_info": "amber",
    "requires_user_action": "amber",
    "unsupported_platform": "slate",
    "outcome_unknown": "amber",
    "failed": "red",
}

STATE_LABEL: dict[str, str] = {
    "submitted_confirmed": "submitted and confirmed",
    "ready_to_submit": "ready to submit",
    "blocked_missing_info": "needs an answer",
    "requires_user_action": "needs you",
    "unsupported_platform": "platform permits none",
    "outcome_unknown": "outcome unverified",
}

RUN_TONE: dict[str, str] = {
    "completed": "green",
    "completed_with_errors": "amber",
    "running": "indigo",
    "pending": "slate",
    "paused": "slate",
    "cancelling": "amber",
    "cancelled": "slate",
    "interrupted": "amber",
    "failed": "red",
}

ACTIVE_STATUSES = {"running", "pending", "cancelling"}


AGE_WINDOWS = [24, 48, 72, 168, 336, 720]
ROLE_FAMILIES = [
    "backend",
    "frontend",
    "fullstack",
    "data",
    "ai_ml",
    "cloud_devops",
    "mobile",
    "general_software",
]
PLATFORMS = ["greenhouse", "lever", "ashby", "local_test"]
REMOTE_CHOICES = {
    "any": "Any arrangement",
    "remote_only": "Remote only",
    "remote_or_hybrid": "Remote or hybrid",
    "onsite_or_hybrid": "Onsite or hybrid",
}


def _window_label(hours: int) -> str:
    return f"last {hours} hours" if hours <= 72 else f"last {hours // 24} days"


def _scope_controls(saved: dict[str, Any]) -> dict[str, Any]:
    """The run's scope. Score and confidence are thresholds; everything in the second
    block is a hard constraint that removes a job whatever its score."""
    columns = st.columns(4)
    bands = columns[0].multiselect(
        "Match band", ["high", "review", "low"], default=saved.get("bands") or ["high", "review"]
    )
    min_score = columns[1].slider("Minimum score", 0, 100, int(saved.get("min_score", 70)))
    window_default = int(saved.get("max_age_hours", 48))
    window = columns[2].selectbox(
        "Posted within",
        AGE_WINDOWS,
        index=AGE_WINDOWS.index(window_default) if window_default in AGE_WINDOWS else 1,
        format_func=_window_label,
    )
    confidence_options = ["low", "medium", "high"]
    confidence = columns[3].selectbox(
        "Minimum confidence",
        confidence_options,
        index=confidence_options.index(saved.get("min_confidence", "medium")),
    )

    st.caption("Hard constraints: each one removes a job on its own, whatever it scores.")
    hard = st.columns(4)
    families = hard[0].multiselect(
        "Role families", ROLE_FAMILIES, default=saved.get("role_families") or []
    )
    locations = hard[1].text_input(
        "Allowed locations",
        value=", ".join(saved.get("locations") or []),
        placeholder="empty = your profile's",
    )
    remote_keys = list(REMOTE_CHOICES)
    remote = hard[2].selectbox(
        "Remote preference",
        remote_keys,
        index=remote_keys.index(saved.get("remote_preference", "any")),
        format_func=REMOTE_CHOICES.get,
    )
    tolerance = hard[3].number_input(
        "Experience tolerance (years)",
        min_value=0.0,
        max_value=20.0,
        value=float(saved.get("experience_tolerance_years") or 1.0),
        step=0.5,
    )

    limits = st.columns(4)
    platforms = limits[0].multiselect(
        "Platforms", PLATFORMS, default=saved.get("platforms") or [], help="Empty means all"
    )
    max_submissions = limits[1].number_input(
        "Maximum submission attempts",
        min_value=1,
        max_value=500,
        value=int(saved.get("max_submissions", 100)),
        step=10,
    )
    daily_cap = limits[2].number_input(
        "Daily cap (0 = installation cap)",
        min_value=0,
        max_value=500,
        value=int(saved.get("daily_cap") or 0),
    )
    excluded = limits[3].text_input(
        "Exclude employers",
        value=", ".join(saved.get("excluded_companies") or []),
        placeholder="comma separated",
    )

    return {
        "bands": bands or ["high", "review"],
        "min_score": float(min_score),
        "max_age_hours": int(window),
        "min_confidence": confidence,
        "max_submissions": int(max_submissions),
        "max_discover": int(saved.get("max_discover", 200)),
        "excluded_companies": [part.strip() for part in excluded.split(",") if part.strip()],
        "role_families": families,
        "locations": [part.strip() for part in locations.split(",") if part.strip()],
        "remote_preference": remote,
        "experience_tolerance_years": float(tolerance),
        "daily_cap": int(daily_cap) or None,
        "platforms": platforms,
    }


def _counts(run: dict[str, Any]) -> list[tuple[str, Any, str]]:
    """The run's figures, with ``submitted`` kept separate from ``prepared``.

    Each caption says what its number actually means, so "prepared" can never be read as
    "sent". The two are never summed into one total for the same reason.
    """
    return [
        ("Eligible", run.get("eligible_count", 0), "matched your scope"),
        ("Prepared", run.get("prepared_count", 0), "ready, not sent"),
        (
            "Submitted and confirmed",
            run.get("confirmed_count", 0),
            "provider returned a confirmation",
        ),
        (
            "Needs an answer",
            run.get("blocked_count", 0) + run.get("needs_user_count", 0),
            "waiting on you",
        ),
        ("Platform permits none", run.get("unsupported_count", 0), "prepared for you to send"),
        ("Outcome unverified", run.get("unknown_count", 0), "check before resending"),
    ]


def _render_capabilities(client: Any) -> None:
    try:
        capabilities = client.submission_capabilities()
    except ApiClientError as error:
        api_error(error)
        return

    supported = capabilities.get("supported_targets") or []
    if supported:
        st.info(
            "Submission is enabled for: "
            + ", ".join(esc(target) for target in supported)
            + ". Every other provider prepares the application for you to send."
        )
    else:
        st.info(esc(capabilities.get("note", "")))

    with st.expander("What each platform permits", expanded=False):
        for row in capabilities.get("platforms", []):
            tone = "green" if row.get("submission_supported") else "slate"
            label = "submission authorized" if row.get("submission_supported") else "no submission"
            st.markdown(
                f"**{esc(row.get('display_name', ''))}** &nbsp; {pill(label, tone)} "
                f"{pill('credential: ' + esc(row.get('credential_owner', '')), 'slate')}",
                unsafe_allow_html=True,
            )
            st.caption(esc(row.get("reason", "")))
            quote = row.get("evidence_quote") or ""
            if quote:
                st.caption(f"> {esc(quote)}")
            url = row.get("evidence_url") or ""
            if url:
                st.caption(esc(url))
            st.divider()


def _render_attempt_detail(client: Any, attempt_id: int, state: str) -> None:
    """What was sent, what happened, and — for an unclear outcome — how to settle it."""
    try:
        detail = client.get_attempt(attempt_id)
    except (ApiClientError, AttributeError) as error:
        if isinstance(error, ApiClientError):
            api_error(error)
        return
    if detail.get("confirmation_evidence"):
        st.success(f"Confirmation: {esc(detail['confirmation_evidence'])}")
    answers = detail.get("answers_sent") or {}
    if answers:
        st.markdown("**Answers typed into the form**")
        st.dataframe(
            [{"question": key, "answer": value} for key, value in answers.items()],
            hide_index=True,
            use_container_width=True,
        )
    events = detail.get("events") or []
    if events:
        st.markdown("**Timeline**")
        for event in events:
            st.caption(
                f"{local_time(event.get('created_at'))} · {esc(event.get('kind', ''))} · "
                f"{esc(event.get('name', ''))} {('— ' + esc(event['detail'])) if event.get('detail') else ''}"
            )
    if detail.get("has_evidence"):
        try:
            st.image(client.attempt_evidence(attempt_id), caption="Evidence screenshot (private)")
        except ApiClientError:
            st.caption("The screenshot is no longer kept (retention period passed).")
    if state in ("outcome_unknown", "requires_user_action"):
        st.markdown(
            "**Settle this outcome.** JobOrbit never presses Submit again on an unclear "
            "outcome. Check the employer's page or your email, then record what you found."
        )
        evidence = st.text_input(
            "What showed it was submitted (email subject, reference number)",
            key=f"resolve-evidence-{attempt_id}",
        )
        buttons = st.columns(3)
        try:
            if buttons[0].button("Recheck the page", key=f"recheck-{attempt_id}"):
                client.recheck_attempt(attempt_id)
                st.rerun()
            if buttons[1].button(
                "It was submitted", key=f"resolve-yes-{attempt_id}", disabled=len(evidence) < 4
            ):
                client.resolve_attempt(attempt_id, "submitted", evidence)
                st.rerun()
            if buttons[2].button("It was not submitted", key=f"resolve-no-{attempt_id}"):
                client.resolve_attempt(attempt_id, "not_submitted", evidence)
                st.rerun()
        except ApiClientError as error:
            api_error(error)


def _render_attempts(client: Any, run: dict[str, Any]) -> None:
    attempts = run.get("attempts") or []
    if not attempts:
        st.caption("No jobs were queued for this run.")
        return

    for attempt in attempts[:60]:
        state = str(attempt.get("state", ""))
        card_anchor()
        with st.container(border=True):
            top = st.columns([3, 2, 3])
            top[0].markdown(
                f"<div class='ja-title'>Job {esc(attempt.get('job_id', ''))}</div>"
                f"<div class='ja-meta'>{esc(attempt.get('target_key', ''))}</div>",
                unsafe_allow_html=True,
            )
            top[1].markdown(
                pill(
                    STATE_LABEL.get(state, state.replace("_", " ")), STATE_TONE.get(state, "slate")
                ),
                unsafe_allow_html=True,
            )
            confirmation = attempt.get("confirmation_id") or ""
            top[2].markdown(
                f"<div class='ja-meta'>{'confirmation ' + esc(confirmation) if confirmation else '&nbsp;'}</div>",
                unsafe_allow_html=True,
            )
            if attempt.get("detail"):
                st.caption(esc(attempt["detail"]))
            meta = []
            if attempt.get("checkpoint"):
                meta.append(f"reached: {attempt['checkpoint'].replace('_', ' ')}")
            if attempt.get("failure_category"):
                meta.append(f"reason: {attempt['failure_category'].replace('_', ' ')}")
            if attempt.get("duration_ms") is not None:
                meta.append(f"{attempt['duration_ms'] / 1000:.0f}s")
            if meta:
                st.caption(" · ".join(esc(item) for item in meta))
            attempt_id = int(attempt.get("id", 0))
            if st.toggle("Evidence and timeline", key=f"evidence-{attempt_id}"):
                _render_attempt_detail(client, attempt_id, state)
    if len(attempts) > 60:
        st.caption(f"Showing the first 60 of {len(attempts)} attempts.")


PLAN_TONE: dict[str, str] = {
    "ready": "green",
    "needs_answers": "amber",
    "unsupported": "slate",
    "blocked": "red",
    "ineligible": "red",
    "below_threshold": "slate",
    "stale": "slate",
    "applied": "slate",
    "duplicate": "slate",
}


def _render_control(client: Any) -> bool:
    """The emergency stop and circuit breakers. Returns whether the stop is on."""
    try:
        control = client.autoapply_control()
    except (ApiClientError, AttributeError):
        return False
    stopped = bool(control.get("emergency_stop"))
    columns = st.columns([3, 1])
    if stopped:
        columns[0].error(
            "Emergency stop is ON. No run will start or continue until you clear it. "
            + esc(control.get("emergency_stop_reason", ""))
        )
        if columns[1].button("Clear stop", use_container_width=True):
            try:
                client.clear_emergency_stop()
                st.rerun()
            except ApiClientError as error:
                api_error(error)
    else:
        cap = control.get("daily_cap")
        columns[0].caption(
            f"Browser submission {'on' if control.get('browser_submission_enabled') else 'off'}"
            + (f" · {control.get('dispatched_today', 0)} of {cap} sent today" if cap else "")
            + f" · evidence kept {control.get('evidence_retention_days', 30)} days"
        )
        if columns[1].button("Emergency stop", type="primary", use_container_width=True):
            try:
                client.emergency_stop("pressed on the Auto-apply page")
                st.rerun()
            except ApiClientError as error:
                api_error(error)
    for breaker in control.get("breakers") or []:
        if breaker.get("open"):
            row = st.columns([3, 1])
            row[0].warning(
                f"{esc(breaker.get('target', ''))} is paused: {esc(breaker.get('reason', ''))}"
            )
            if row[1].button("Reset", key=f"breaker-{breaker.get('target')}"):
                try:
                    client.reset_circuit(str(breaker.get("target")))
                    st.rerun()
                except ApiClientError as error:
                    api_error(error)
    return stopped


def _render_preflight(plan: dict[str, Any]) -> list[int]:
    """The itemised plan, with a tick box per queued job. Returns the approved job ids."""
    counts = plan.get("counts") or {}
    metric_row(
        [
            ("Discovered", counts.get("total_discovered", 0), f"{counts.get('new_jobs', 0)} new"),
            ("Ready to submit", counts.get("ready", 0), "all known answers on file"),
            ("Need your answers", counts.get("missing_answers", 0), "prepared, then wait"),
            ("Planned submissions", counts.get("planned_attempts", 0), "after limits and cap"),
        ]
    )
    metric_row(
        [
            ("Duplicates", counts.get("duplicates", 0), "merged listings"),
            ("Already applied", counts.get("previously_applied", 0), "never sent twice"),
            ("Expired or stale", counts.get("expired_or_stale", 0), "outside the age window"),
            (
                "Blocked",
                counts.get("blocked_by_constraints", 0) + counts.get("blocked_by_eligibility", 0),
                "a hard constraint failed",
            ),
        ]
    )
    st.caption(
        f"Scored {counts.get('scored', 0)} · meeting score {counts.get('meeting_score', 0)} · "
        f"meeting confidence {counts.get('meeting_confidence', 0)} · experience fit "
        f"{counts.get('meeting_experience', 0)} · location fit {counts.get('meeting_location', 0)}"
        f" · platform permits none {counts.get('unsupported_platform', 0)}"
    )
    for note in plan.get("notes") or []:
        st.info(esc(note))

    approved: list[int] = []
    jobs = plan.get("jobs") or []
    show_all = st.toggle("Show jobs that are not in this run", value=False)
    for job in jobs:
        queued = bool(job.get("queued"))
        if not queued and not show_all:
            continue
        status = str(job.get("status", ""))
        score = job.get("score")
        title = (
            f"{job.get('title', '')} · {job.get('employer', '')} · "
            f"{status.replace('_', ' ')}"
            + (f" · {score:.0f}" if isinstance(score, int | float) else "")
        )
        with st.expander(title, expanded=False):
            st.markdown(
                pill(status.replace("_", " "), PLAN_TONE.get(status, "slate"))
                + " "
                + pill(esc(job.get("platform_name", "")), "slate"),
                unsafe_allow_html=True,
            )
            if queued:
                if st.checkbox(
                    "Include in this run", value=True, key=f"approve-{job.get('job_id')}"
                ):
                    approved.append(int(job["job_id"]))
            facts = st.columns(3)
            facts[0].caption(
                f"Sources: {esc(', '.join(job.get('sources') or []))}  \n"
                f"Posted: {local_time(job.get('posted_at')) if job.get('posted_at') else 'not stated'}"
            )
            coverage = job.get("evidence_coverage")
            facts[1].caption(
                f"Confidence: {esc(job.get('confidence') or '-')}  \n"
                f"Evidence coverage: {f'{coverage:.0%}' if isinstance(coverage, int | float) else '-'}"
            )
            facts[2].caption(f"Role family: {esc(job.get('role_family', ''))}")
            location, experience = job.get("location_fit") or {}, job.get("experience_fit") or {}
            st.caption(
                f"Location: {esc(location.get('status', ''))} — {esc(location.get('detail', ''))}"
            )
            st.caption(
                f"Experience: {esc(experience.get('status', ''))} — "
                f"{esc(experience.get('detail', ''))}"
            )
            if job.get("url"):
                st.caption(esc(job["url"]))
            st.caption(f"Resume: {esc(job.get('resume_artifact', ''))}")
            if job.get("capability_reason"):
                st.caption(f"Submission: {esc(job['capability_reason'])}")
            for reason in job.get("blocking_reasons") or []:
                st.markdown(f"- {esc(reason)}")
            for warning in job.get("warnings") or []:
                st.caption(f"⚠ {esc(warning)}")
            if job.get("unresolved_questions"):
                st.markdown("**Questions still open**")
                for question in job["unresolved_questions"]:
                    st.markdown(f"- {esc(question)}")
            answers = job.get("screening_answers") or []
            if answers:
                st.markdown("**Answers that would be sent**")
                st.dataframe(
                    [
                        {
                            "question": row.get("question", ""),
                            "answer": row.get("answer", ""),
                            "from": row.get("source", ""),
                        }
                        for row in answers
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            preview = job.get("cover_letter_preview") or ""
            if preview and preview not in ("none", "drafted at preparation"):
                st.caption("Cover letter (start):")
                st.text(preview)
    return approved


def render() -> None:
    st.title("Auto-apply")
    section_header(
        "Preview, approve, then run",
        "Every job in scope is checked against your constraints before anything is sent.",
    )
    client = get_client()
    stopped = _render_control(client)
    _render_capabilities(client)

    try:
        saved = client.autoapply_preferences() or {}
    except (ApiClientError, AttributeError):
        saved = {}
    scope = _scope_controls(saved)
    dry_run = st.toggle(
        "Dry run (fill forms and screenshot them, send nothing)",
        value=True,
        help="Leave this on to see exactly what a run would do before anything is dispatched.",
    )

    actions = st.columns([1, 1, 4])
    if actions[0].button("Build preflight", use_container_width=True):
        try:
            st.session_state["autoapply_plan"] = client.autoapply_preflight(
                {**scope, "dry_run": dry_run}
            )
            st.session_state["autoapply_plan_scope"] = {**scope, "dry_run": dry_run}
        except ApiClientError as error:
            api_error(error)
        except AttributeError:
            st.session_state["autoapply_preview"] = client.preview_autoapply(
                {**scope, "dry_run": dry_run}
            )

    plan = st.session_state.get("autoapply_plan")
    plan_current = plan is not None and st.session_state.get("autoapply_plan_scope") == {
        **scope,
        "dry_run": dry_run,
    }
    approved: list[int] = []
    if plan and plan_current:
        approved = _render_preflight(plan)
    elif plan:
        st.caption("The scope changed since the preflight was built. Build it again.")

    needs_plan = not dry_run and not plan_current
    start = actions[1].button(
        "Start run",
        type="primary",
        use_container_width=True,
        disabled=stopped or needs_plan,
        help="A live run needs a current preflight, and covers only the jobs ticked in it."
        if needs_plan
        else None,
    )
    if start:
        payload = {**scope, "dry_run": dry_run}
        if plan_current:
            if not approved:
                st.warning("No job is ticked in the preflight, so there is nothing to run.")
                return
            payload["approved_job_ids"] = approved
        try:
            # A live run fills real forms at a human pace (a pause between applications),
            # so it runs in the background and this page shows its progress.
            started = client.start_autoapply(payload, background=not dry_run)
            if dry_run:
                message = f"Run {started.get('id')} finished: {started.get('message', '')}"
            else:
                message = (
                    f"Run {started.get('id')} started on {len(approved)} approved job(s). It "
                    "applies one job at a time in JobOrbit's Chrome window; refresh this page "
                    "to follow it."
                )
            st.session_state["autoapply_flash"] = message
            st.session_state.pop("autoapply_plan", None)
            st.rerun()
        except ApiClientError as error:
            api_error(error)

    flash = st.session_state.pop("autoapply_flash", "")
    if flash:
        st.success(esc(flash))

    legacy = st.session_state.get("autoapply_preview")
    if legacy:
        st.markdown(f"**{esc(legacy.get('note', ''))}**")

    st.divider()
    section_header("Runs")
    try:
        runs = client.list_autoapply_runs(limit=10).get("items", [])
    except ApiClientError as error:
        api_error(error)
        return

    if not runs:
        empty_state(
            "No runs yet",
            "Set the scope above and press Start run. Leave Dry run on for the first one.",
        )
        return

    for run in runs:
        status = str(run.get("status", ""))
        with st.expander(
            f"Run {run.get('id')} · {status} · {run.get('confirmed_count', 0)} confirmed",
            expanded=run is runs[0],
        ):
            header = st.columns([2, 2, 3])
            header[0].markdown(pill(status, RUN_TONE.get(status, "slate")), unsafe_allow_html=True)
            header[1].markdown(
                pill("dry run" if run.get("dry_run") else "live", "slate"),
                unsafe_allow_html=True,
            )
            header[2].caption(f"started {local_time(run.get('started_at'))}")

            metric_row(_counts(run))
            if run.get("message"):
                st.caption(esc(run["message"]))

            controls = st.columns([1, 1, 1, 3])
            run_id = int(run.get("id", 0))
            if status in ACTIVE_STATUSES and controls[0].button(
                "Pause", key=f"pause-{run_id}", use_container_width=True
            ):
                try:
                    client.pause_autoapply(run_id)
                    st.rerun()
                except ApiClientError as error:
                    api_error(error)
            if status in {"paused", "interrupted", "cancelled"} and controls[1].button(
                "Resume", key=f"resume-{run_id}", use_container_width=True
            ):
                try:
                    client.resume_autoapply(run_id)
                    st.rerun()
                except ApiClientError as error:
                    api_error(error)
            if status in ACTIVE_STATUSES and controls[2].button(
                "Stop", key=f"stop-{run_id}", use_container_width=True
            ):
                try:
                    client.cancel_autoapply(run_id)
                    st.rerun()
                except ApiClientError as error:
                    api_error(error)

            try:
                report = client.autoapply_report(run_id)
            except ApiClientError:
                report = ""
            if report:
                st.download_button(
                    "Download report",
                    data=report,
                    file_name=f"autoapply-run-{run_id}.txt",
                    mime="text/plain",
                    key=f"report-{run_id}",
                    use_container_width=True,
                )

            _render_attempts(client, run)
