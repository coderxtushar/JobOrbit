"""Application review queue.

This is the screen the compliance requirement turns on: the user sees the complete
application, edits anything, approves it, and then opens the employer's own page to submit
it themselves. There is no submit button here, because there is no submit capability.
"""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import (
    api_error,
    confidence_badge,
    empty_state,
    evidence_block,
    get_client,
    local_time,
    metric_row,
    score_ring,
    section_header,
)

PROVENANCE_LABEL = {
    "profile_verified": ("Verified from your profile", "#d8f0e2"),
    "resume_extracted": ("Extracted from your resume", "#dbe9fb"),
    "ai_draft": ("AI draft — read before using", "#fff3cd"),
    "user_entered": ("You typed this", "#e8e8e8"),
    "needs_user_input": ("Needs your input", "#fde2e1"),
}


def _provenance_badge(provenance: str) -> str:
    label, colour = PROVENANCE_LABEL.get(provenance, (provenance, "#e8e8e8"))
    return (
        f"<span style='background:{colour};padding:1px 8px;border-radius:9px;"
        f"font-size:0.75rem;'>{label}</span>"
    )


def _prepare_section() -> None:
    client = get_client()
    pending_job = st.session_state.pop("prepare_job_id", None)

    section_header("Prepare an application")
    columns = st.columns([2, 2, 1])
    job_id = columns[0].number_input(
        "Job id", min_value=1, step=1, value=int(pending_job) if pending_job else 1
    )
    include_letter = columns[1].checkbox("Include a cover letter", value=True)
    if columns[2].button("Prepare", type="primary", use_container_width=True) or pending_job:
        target = int(pending_job) if pending_job else int(job_id)
        try:
            application = client.prepare_application(target, include_letter)
        except ApiClientError as exc:
            api_error(exc)
        else:
            st.session_state["review_application_id"] = application["id"]
            st.success(
                f"Application {application['id']} is ready for review with "
                f"{len(application['answers'])} questions."
            )
            st.rerun()


def _answer_completeness(application: dict) -> tuple[int, int, int]:
    answers = application.get("answers") or []
    answered = sum(1 for answer in answers if (answer.get("answer") or "").strip())
    drafted = sum(1 for answer in answers if answer.get("provenance") == "ai_draft")
    return answered, len(answers), drafted


def _consolidated_header(application: dict) -> None:
    flash = st.session_state.pop("_review_flash", "")
    if flash:
        st.success(flash)

    answered, total, drafted = _answer_completeness(application)
    blocking = application.get("blocking_questions") or []

    st.info(f"**Next: {application.get('next_action') or 'No action recorded.'}**")

    metric_row(
        [
            ("Status", application["status"], "state machine"),
            ("Answers complete", f"{answered}/{total}", "non-empty responses"),
            ("Needs you", len(blocking), "blocking questions"),
            ("AI drafts", drafted, "read before using"),
            (
                "Employer page",
                "opened" if application.get("employer_page_opened") else "not opened",
                "opening is not submitting",
            ),
        ]
    )

    warnings: list[str] = []
    if not application.get("resume_version_label"):
        warnings.append("No resume variant was selected, so no tailored resume is attached.")
    if not (application.get("cover_letter") or "").strip():
        warnings.append("This application has no cover letter.")
    if not application.get("job_url"):
        warnings.append(
            "The source gave no safe link for this job, so there is no page to open from here."
        )
    if drafted:
        warnings.append(
            f"{drafted} answer(s) are AI drafts. A sensitive question cannot be approved "
            "while it is only a draft."
        )
    for warning in warnings:
        st.warning(warning)


def _job_and_match_tab(application: dict) -> None:
    client = get_client()
    try:
        job = client.get_job(application["job_id"])
    except ApiClientError as exc:
        api_error(exc)
        return

    match = job.get("match") or {}
    ring, facts = st.columns([1, 5])
    with ring:
        st.markdown(
            score_ring(match.get("total_score"), match.get("band", ""), size=84),
            unsafe_allow_html=True,
        )
        if match:
            st.markdown(
                confidence_badge(match.get("confidence", ""), match.get("evidence_coverage")),
                unsafe_allow_html=True,
            )
    with facts:
        st.markdown(f"**{job['title']}** — {job['company']}")
        st.markdown(
            f"- Location: {job.get('location') or 'not stated'}\n"
            f"- Work arrangement: `{job['work_arrangement']}`\n"
            f"- Experience asked: {job.get('experience_raw') or 'not stated'}\n"
            f"- Posted: "
            + (local_time(job["posted_at"]) if job.get("posted_at") else "not provided")
            + f"\n- Discovered: {local_time(job['discovered_at'])}"
        )

    if match:
        st.markdown(evidence_block(match), unsafe_allow_html=True)
    else:
        st.caption("This job has not been scored, so there is no match evidence to show.")

    with st.expander("Full description (treated as untrusted text)"):
        st.text(job.get("description") or "No description was provided.")


def _render_application(application: dict) -> None:
    client = get_client()
    st.markdown(f"### {application['job_title']} — {application['job_company']}")
    st.caption(
        f"Application {application['id']} · status `{application['status']}` · "
        f"platform `{application['platform']}` · resume `{application['resume_version_label'] or 'none selected'}`"
    )

    _consolidated_header(application)

    blocking = application.get("blocking_questions") or []
    if blocking:
        st.warning(
            f"{len(blocking)} question(s) need your input before this can be approved. "
            "Sensitive and legal questions are never drafted for you."
        )

    job_tab, letter_tab, answers_tab, submit_tab, history_tab = st.tabs(
        ["Job and match", "Cover letter", "Answers", "Approve and submit", "History"]
    )

    with job_tab:
        _job_and_match_tab(application)

    with letter_tab:
        st.caption(
            f"Generated by `{application['cover_letter_generated_by'] or 'not generated'}` · "
            f"version {application['cover_letter_version']}"
        )
        letter = st.text_area(
            "Cover letter",
            value=application["cover_letter"],
            height=280,
            key=f"cl{application['id']}",
        )
        if st.button("Save cover letter", key=f"savecl{application['id']}"):
            try:
                client.update_application(application["id"], {"cover_letter": letter})
                st.success("Cover letter saved. Its provenance is now 'you typed this'.")
                st.rerun()
            except ApiClientError as exc:
                api_error(exc)

    with answers_tab:
        st.caption(
            "Every answer carries its provenance. Editing one marks it as yours. Nothing "
            "here is sent anywhere — you copy it into the employer's form."
        )
        edits: list[dict] = []
        for answer in application["answers"]:
            with st.container(border=True):
                st.markdown(
                    f"**{answer['question']}** &nbsp; {_provenance_badge(answer['provenance'])}"
                    + (
                        " <span style='background:#f0e6ff;padding:1px 8px;border-radius:9px;"
                        "font-size:0.75rem;'>sensitive</span>"
                        if answer["is_sensitive"]
                        else ""
                    ),
                    unsafe_allow_html=True,
                )
                if answer["flag_reason"]:
                    st.caption(answer["flag_reason"])
                value = st.text_area(
                    "Answer",
                    value=answer["answer"],
                    key=f"ans{application['id']}_{answer['id']}",
                    height=70,
                    label_visibility="collapsed",
                )
                if value != answer["answer"]:
                    edits.append({"id": answer["id"], "answer": value})

        if st.button("Save answer edits", type="primary", key=f"saveans{application['id']}"):
            if not edits:
                st.info("Nothing changed.")
            else:
                try:
                    client.update_application(application["id"], {"answers": edits})
                    st.success(f"Saved {len(edits)} answer(s).")
                    st.rerun()
                except ApiClientError as exc:
                    api_error(exc)

    with submit_tab:
        st.info(
            "**You submit the application, not this app.** It cannot click Apply on any "
            "platform, and doing so would breach their terms. Approve below, open the "
            "official page, paste your answers, submit, then record what happened."
        )
        approved = st.checkbox(
            "I have reviewed this application and approve it",
            value=application["user_approved"],
            key=f"appr{application['id']}",
        )
        columns = st.columns([1, 1, 2])
        if columns[0].button(
            "Mark approved", key=f"doappr{application['id']}", use_container_width=True
        ):
            try:
                client.update_application(
                    application["id"], {"user_approved": approved, "status": "APPROVED"}
                )
                st.success("Approved.")
                st.rerun()
            except ApiClientError as exc:
                api_error(exc)
        if application["job_url"]:
            columns[1].link_button(
                "Open official page", application["job_url"], use_container_width=True
            )
            if columns[2].button(
                "I opened the employer's page",
                key=f"opened{application['id']}",
                use_container_width=True,
            ):
                try:
                    get_client().record_opened(application["id"])
                except ApiClientError as exc:
                    api_error(exc)
                else:
                    st.session_state["_review_flash"] = (
                        "Recorded that you opened the page. This is not a submission — "
                        "record that separately below once you have actually submitted."
                    )
                    st.rerun()
        else:
            columns[1].caption("The source gave no safe link for this job.")

        st.divider()
        st.markdown("**Record what you did**")
        columns = st.columns([2, 2])
        submitter = columns[0].text_input(
            "Who submitted it",
            value=application["submitted_by"] or "",
            key=f"by{application['id']}",
            help="Your name. A submission must be attributable to a person.",
        )
        if columns[1].button(
            "Record that I submitted it", key=f"sub{application['id']}", use_container_width=True
        ):
            try:
                client.update_application(
                    application["id"], {"status": "SUBMITTED", "submitted_by": submitter}
                )
                st.success("Recorded as submitted by you.")
                st.rerun()
            except ApiClientError as exc:
                api_error(exc)

        evidence = st.text_input(
            "Confirmation evidence",
            value=application["confirmation_evidence"] or "",
            key=f"ev{application['id']}",
            help="A confirmation email subject or a reference number. Required to confirm, "
            "because a click is not a confirmation.",
        )
        columns = st.columns([1, 1, 2])
        if columns[0].button(
            "Confirm with evidence", key=f"conf{application['id']}", use_container_width=True
        ):
            try:
                client.update_application(
                    application["id"],
                    {"status": "CONFIRMED", "confirmation_evidence": evidence},
                )
                st.success("Confirmed.")
                st.rerun()
            except ApiClientError as exc:
                api_error(exc)
        if columns[1].button(
            "Outcome unclear", key=f"unk{application['id']}", use_container_width=True
        ):
            try:
                client.update_application(application["id"], {"status": "SUBMISSION_UNKNOWN"})
                st.info("Recorded as unknown rather than assumed successful.")
                st.rerun()
            except ApiClientError as exc:
                api_error(exc)

    with history_tab:
        events = application.get("events") or []
        if not events:
            st.caption("No status changes recorded yet.")
        else:
            st.dataframe(
                [
                    {
                        "when": local_time(event["created_at"]),
                        "from": event["from_status"] or "—",
                        "to": event["to_status"],
                        "actor": event["actor"],
                        "detail": event["detail"],
                    }
                    for event in events
                ],
                hide_index=True,
                use_container_width=True,
            )


def render() -> None:
    st.title("Application review queue")
    client = get_client()
    _prepare_section()
    st.divider()

    try:
        queue = client.list_applications(
            status=["READY_FOR_REVIEW", "APPROVED", "SHORTLISTED"], limit=50
        )
    except ApiClientError as exc:
        api_error(exc)
        return

    if queue["total"] == 0:
        empty_state(
            "Nothing waiting for review",
            "Shortlist a job on the **Job feed** page and press Prepare, or enter a job id above.",
            "Go to the Job feed.",
        )
        return

    options = {
        f"#{item['id']} · {item['job_title']} @ {item['job_company']} ({item['status']})": item[
            "id"
        ]
        for item in queue["items"]
    }
    preselected = st.session_state.get("review_application_id")
    keys = list(options)
    index = 0
    if preselected in options.values():
        index = list(options.values()).index(preselected)

    chosen = st.selectbox(f"{queue['total']} application(s) in the queue", keys, index=index)
    try:
        application = client.get_application(options[chosen])
    except ApiClientError as exc:
        api_error(exc)
        return
    _render_application(application)
