"""Action inbox and answer bank.

One question answered here is written to every open application waiting on it, which is
what makes a hundred-job run finishable. The questions are grouped by key and counted, so
the work is proportional to the number of distinct questions, not the number of jobs.

Two rules are visible in the interface because they are enforced in the backend: a
sensitive or legal question is never drafted for you, and an AI draft can never be saved
for reuse.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClientError
from ui.components import api_error, empty_state, get_client, local_time, metric_row
from ui.theme import card_anchor, esc, pill, section_header


def _entry_card(entry: dict[str, Any]) -> None:
    client = get_client()
    key = entry["question_key"]

    with st.container(border=True):
        card_anchor()
        badges = [pill(f"{entry['occurrences']} application(s)", "indigo")]
        if entry["is_sensitive"]:
            badges.append(pill("sensitive — never drafted", "amber"))
        if entry["has_saved_answer"]:
            badges.append(pill("saved answer exists", "green"))
        st.markdown(
            f"<div class='ja-title'>{esc(entry['question'])}</div>"
            f"<div class='ja-meta'><code>{esc(key)}</code></div>"
            f"<div>{' '.join(badges)}</div>",
            unsafe_allow_html=True,
        )

        if entry["is_sensitive"]:
            st.caption(
                "This is a legal or sensitive question. Type the true answer yourself; "
                "nothing is generated for it."
            )

        # A form, not a bare text area plus button: Streamlit commits a text area on blur,
        # so clicking the button directly would spend the first click committing the text
        # and discard it. A form submits both together, so one click saves.
        with st.form(f"inbox-form-{key}", clear_on_submit=False):
            answer = st.text_area(
                "Your answer",
                key=f"inbox-answer-{key}",
                height=80,
                label_visibility="collapsed",
                placeholder="Type the answer once. It will be applied everywhere it is needed.",
            )
            columns = st.columns([2, 2, 3])
            apply_all = columns[0].checkbox(
                "Apply to all open applications",
                value=True,
                key=f"inbox-apply-{key}",
            )
            submitted = columns[1].form_submit_button("Save answer", type="primary")
            if entry["application_ids"]:
                columns[2].caption(
                    "Waiting on applications: " + ", ".join(entry["application_ids"][:5])
                )

        if submitted:
            if not answer.strip():
                st.warning("Type an answer first. A blank answer is not saved.")
            else:
                try:
                    result = client.save_answer(
                        key,
                        {
                            "answer": answer,
                            "question": entry["question"],
                            "apply_to_open_applications": apply_all,
                        },
                    )
                except ApiClientError as exc:
                    api_error(exc)
                else:
                    st.session_state["inbox_flash"] = (
                        f"Saved '{key}' and applied it to "
                        f"{result['applications_updated']} open application(s). It will "
                        "fill in automatically on future ones."
                    )
                    st.rerun()


def _bank_section() -> None:
    client = get_client()
    section_header(
        "Answer bank", "Answers you verified once. They fill in automatically from now on."
    )
    try:
        saved = client.list_answers()
    except ApiClientError as exc:
        api_error(exc)
        return

    if not saved:
        st.caption("Empty. Answer anything in the inbox above and it is kept here for reuse.")
        return

    metric_row(
        [
            ("Saved answers", len(saved), "reusable across applications"),
            (
                "Total reuses",
                sum(entry["times_used"] for entry in saved),
                "times an answer was filled for you",
            ),
            (
                "Sensitive",
                sum(1 for entry in saved if entry["is_sensitive"]),
                "you typed every one of these",
            ),
        ]
    )

    for entry in saved:
        with st.container(border=True):
            card_anchor()
            badges = [pill(entry["provenance"].replace("_", " "), "green")]
            if entry["is_sensitive"]:
                badges.append(pill("sensitive", "amber"))
            st.markdown(
                f"<div class='ja-title'>{esc(entry['question'] or entry['question_key'])}"
                "</div>"
                f"<div class='ja-meta'><code>{esc(entry['question_key'])}</code> · used "
                f"{entry['times_used']} time(s)"
                + (f" · last {local_time(entry['last_used_at'])}" if entry["last_used_at"] else "")
                + f"</div><div>{' '.join(badges)}</div>",
                unsafe_allow_html=True,
            )
            with st.form(f"bank-form-{entry['question_key']}"):
                updated = st.text_area(
                    "Answer",
                    value=entry["answer"],
                    key=f"bank-{entry['question_key']}",
                    height=70,
                )
                columns = st.columns([1, 1, 4])
                save = columns[0].form_submit_button("Update")
                forget = columns[1].form_submit_button("Forget")

            if save:
                try:
                    client.save_answer(
                        entry["question_key"],
                        {
                            "answer": updated,
                            "question": entry["question"],
                            "apply_to_open_applications": True,
                        },
                    )
                except ApiClientError as exc:
                    api_error(exc)
                else:
                    st.session_state["inbox_flash"] = (
                        f"Updated '{entry['question_key']}' and reapplied it to your open "
                        "applications."
                    )
                    st.rerun()
            if forget:
                try:
                    client.delete_answer(entry["question_key"])
                except ApiClientError as exc:
                    api_error(exc)
                else:
                    st.session_state["inbox_flash"] = (
                        f"Removed '{entry['question_key']}'. Applications already filled "
                        "keep the answer they were given."
                    )
                    st.rerun()


def render() -> None:
    st.title("Action inbox")
    st.caption(
        "Everything waiting on a decision only you can make, grouped so you answer each "
        "question once rather than once per job."
    )
    client = get_client()

    flash = st.session_state.pop("inbox_flash", "")
    if flash:
        st.success(flash)

    try:
        inbox = client.action_inbox()
    except ApiClientError as exc:
        api_error(exc)
        return

    if inbox:
        metric_row(
            [
                ("Questions waiting", len(inbox), "distinct questions"),
                (
                    "Applications blocked",
                    sum(entry["occurrences"] for entry in inbox),
                    "answer slots to fill",
                ),
                (
                    "Sensitive",
                    sum(1 for entry in inbox if entry["is_sensitive"]),
                    "never drafted for you",
                ),
            ]
        )
        section_header("Answer once, apply everywhere")
        for entry in inbox:
            _entry_card(entry)
    else:
        empty_state(
            "Nothing is waiting on you",
            "Every prepared application has an answer for every question. Prepare more "
            "jobs from the Bulk preparation page, or open the Review queue to approve "
            "what is ready.",
        )

    st.divider()
    _bank_section()
