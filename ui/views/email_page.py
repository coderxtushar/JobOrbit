"""Email tracking: connect Gmail read-only, review matches, accept or dismiss suggestions.

Three things on this page are enforced in the API, not just shown here: the connection is
read-only (one scope, no send), nothing changes an application until you press Accept, and
an Accept the application's current state does not allow is refused with the reason.

The page talks to ``/api/email`` through ``client._request`` because the shared API client
has no email methods of its own yet.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError
from ui.components import api_error, empty_state, get_client, local_time, metric_row
from ui.theme import card_anchor, esc, pill, section_header

_CATEGORY_LABELS = {
    "application_confirmation": ("Confirmation", "green"),
    "rejection": ("Rejection", "amber"),
    "interview_invitation": ("Interview", "indigo"),
    "assessment_invitation": ("Assessment", "indigo"),
    "offer": ("Offer", "green"),
    "process_update": ("Update", "slate"),
    "recruiter_message": ("Recruiter", "slate"),
    "other_job_related": ("Job-related", "slate"),
}
_FLASH_KEY = "email_flash"


def _flash(message: str) -> None:
    st.session_state[_FLASH_KEY] = message
    st.rerun()


def _call(client: ApiClient, method: str, path: str, **kwargs: Any) -> Any | None:
    try:
        return client._request(method, path, **kwargs)
    except ApiClientError as exc:
        api_error(exc)
        return None


def _category_pill(category: str) -> str:
    label, tone = _CATEGORY_LABELS.get(category, (category, "slate"))
    return pill(label, tone)


def _facts_line(extracted: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("employer", "Employer"),
        ("job_title", "Role"),
        ("application_reference", "Ref"),
        ("interview_date", "Interview"),
        ("interview_time", "at"),
        ("interview_timezone", ""),
        ("deadline", "Deadline"),
    ):
        value = extracted.get(key)
        if value:
            parts.append(f"{label} {value}".strip())
    return " · ".join(parts)


# ------------------------------------------------------------------------ connection


def _connection_section(client: ApiClient, status: dict[str, Any]) -> None:
    section_header(
        "Connection",
        "Read-only Gmail access. JobOrbit cannot send, delete or change any email.",
    )
    accounts = [a for a in status.get("accounts", []) if a.get("status") != "disconnected"]
    with st.container(border=True):
        card_anchor()
        if not status.get("enabled"):
            st.warning(
                "Email tracking is off. Set `JA_EMAIL_TRACKING_ENABLED=true` and restart to "
                "connect Gmail. Pasting an email below works without it."
            )
        elif not status.get("oauth_configured"):
            st.warning(
                "No Gmail OAuth client configured. Create a Desktop OAuth client in your own "
                "Google Cloud project and set `JA_GMAIL_CLIENT_ID` (docs/EMAIL_TRACKING.md)."
            )

        if accounts:
            for account in accounts:
                tone = "green" if account["status"] == "connected" else "amber"
                st.markdown(
                    f"<div class='ja-title'>{esc(account['address'] or 'Gmail')}</div>"
                    f"<div>{pill(account['status'], tone)} "
                    f"{pill('gmail.readonly', 'outline')}</div>"
                    f"<div class='ja-meta'>Last sync: {esc(local_time(account.get('last_sync_at')))}"
                    "</div>",
                    unsafe_allow_html=True,
                )
                if account.get("last_error"):
                    st.caption(account["last_error"])
        else:
            st.caption("No mailbox connected.")
        st.caption(
            f"Scope: `{status.get('scope', '')}` · Searches the last "
            f"{status.get('sync_days')} days, at most {status.get('max_messages')} messages · "
            f"Token stored in: {status.get('secret_backend')}"
        )

        columns = st.columns(4)
        can_connect = bool(status.get("enabled") and status.get("oauth_configured"))
        if columns[0].button("Connect Gmail", disabled=not can_connect, key="email-connect"):
            result = _call(client, "GET", "/api/email/gmail/connect")
            if result:
                st.session_state["email_auth_url"] = result["auth_url"]
        if columns[1].button("Sync now", disabled=not accounts, type="primary", key="email-sync"):
            with st.spinner("Reading recent job-related mail…"):
                reports = _call(client, "POST", "/api/email/sync")
            if reports is not None:
                kept = sum(report["kept"] for report in reports)
                suggestions = sum(report["suggestions"] for report in reports)
                review = sum(report["needs_review"] for report in reports)
                _flash(
                    f"Synced: {kept} new job-related email(s), {suggestions} suggestion(s), "
                    f"{review} waiting for you to pick the application."
                )
        if columns[2].button("Disconnect", disabled=not accounts, key="email-disconnect"):
            result = _call(client, "POST", "/api/email/disconnect")
            if result is not None:
                _flash("Disconnected. The token was revoked and deleted from this machine.")
        with columns[3].popover("Delete email data"):
            st.write(
                "Disconnects Gmail and deletes every stored email and suggestion. Changes "
                "you already accepted stay on your applications."
            )
            if st.button("Delete everything", type="primary", key="email-delete"):
                result = _call(client, "DELETE", "/api/email/data")
                if result is not None:
                    _flash(
                        f"Deleted {result['messages']} email(s) and "
                        f"{result['suggestions']} suggestion(s)."
                    )

        auth_url = st.session_state.get("email_auth_url")
        if auth_url:
            st.link_button("Open Google sign-in", auth_url)
            st.caption(
                "Sign in on Google's page and allow read-only access. When the tab says "
                "connected, close it and reload this page."
            )


def _paste_section(client: ApiClient) -> None:
    with st.expander("Paste an email instead (no Gmail connection needed)"):
        st.caption(
            "In Gmail use ⋮ → Download message (or Show original → copy), then paste the "
            "full source here. Only job-related mail is kept, and never its full body."
        )
        with st.form("email-paste", clear_on_submit=True):
            raw = st.text_area("Raw email (.eml)", height=180, label_visibility="collapsed")
            uploaded = st.file_uploader("…or upload a .eml file", type=["eml"])
            submitted = st.form_submit_button("Process email")
        if submitted:
            payload = raw
            if uploaded is not None:
                payload = uploaded.getvalue().decode("utf-8", errors="replace")
            if not payload.strip():
                st.warning("Paste an email or choose a .eml file first.")
                return
            result = _call(client, "POST", "/api/email/ingest", json={"raw": payload})
            if result is None:
                return
            if result["outcome"] == "skipped_not_job_related":
                st.info("That email does not look job-related, so nothing was stored.")
            elif result["outcome"] == "duplicate":
                st.info("That email was already processed.")
            else:
                state = result["message"]["match_state"]
                _flash(
                    f"Stored as {result['category'].replace('_', ' ')} ({state.replace('_', ' ')})."
                )


# ------------------------------------------------------------------------ review inbox


def _review_card(client: ApiClient, message: dict[str, Any]) -> None:
    with st.container(border=True):
        card_anchor()
        st.markdown(
            f"<div class='ja-title'>{esc(message['subject'] or '(no subject)')}</div>"
            f"<div class='ja-meta'>{esc(message['sender_domain'])} · "
            f"{esc(local_time(message.get('received_at')))}</div>"
            f"<div>{_category_pill(message['category'])}</div>",
            unsafe_allow_html=True,
        )
        facts = _facts_line(message.get("extracted") or {})
        if facts:
            st.caption(facts)
        if message.get("snippet"):
            st.caption(message["snippet"][:300])

        candidates = message.get("match_candidates") or []
        options = {
            candidate["application_id"]: (
                f"{candidate['company']} — {candidate['job_title']} "
                f"(#{candidate['application_id']}, {candidate['status']}, "
                f"score {candidate['score']:.2f})"
            )
            for candidate in candidates
        }
        columns = st.columns([4, 1, 1])
        if options:
            chosen = columns[0].selectbox(
                "Which application is this about?",
                list(options),
                format_func=lambda key: options[key],
                key=f"email-pick-{message['id']}",
            )
            best = next((c for c in candidates if c["application_id"] == chosen), None)
            if best and best.get("signals"):
                columns[0].caption("Why: " + "; ".join(best["signals"][:4]))
        else:
            chosen = columns[0].number_input(
                "Application id",
                min_value=1,
                step=1,
                key=f"email-pick-{message['id']}",
            )
        if columns[1].button("Link", key=f"email-link-{message['id']}", type="primary"):
            result = _call(
                client,
                "POST",
                f"/api/email/messages/{message['id']}/link",
                json={"application_id": int(chosen)},
            )
            if result is not None:
                note = " A suggestion is waiting below." if result.get("suggestion") else ""
                _flash(f"Linked to application #{int(chosen)}.{note}")
        if columns[2].button("Not about any", key=f"email-ignore-{message['id']}"):
            if _call(client, "POST", f"/api/email/messages/{message['id']}/dismiss") is not None:
                _flash("Marked as not about any application.")


def _review_section(client: ApiClient) -> None:
    section_header(
        "Needs your pick",
        "These emails could belong to more than one application, or to none we could see.",
    )
    for state in ("needs_review", "unmatched"):
        page = _call(
            client, "GET", "/api/email/messages", params={"match_state": state, "limit": 50}
        )
        if page is None:
            return
        if state == "unmatched" and page["items"]:
            st.caption("No likely application found for these:")
        for message in page["items"]:
            _review_card(client, message)
        if state == "needs_review" and not page["items"]:
            st.caption("No ambiguous matches.")


# ------------------------------------------------------------------------ suggestions


def _suggestion_card(client: ApiClient, suggestion: dict[str, Any]) -> None:
    with st.container(border=True):
        card_anchor()
        target = f"{suggestion['field']} → {suggestion['suggested_value']}"
        current = (
            suggestion["current_status"]
            if suggestion["field"] == "status"
            else suggestion["current_outcome"]
        )
        confidence = f"confidence {suggestion['confidence']:.0%}"
        badges = " ".join(
            (pill(target, "indigo"), pill(f"now {current}", "outline"), pill(confidence, "slate"))
        )
        st.markdown(
            f"<div class='ja-title'>{esc(suggestion['job_company'])} — "
            f"{esc(suggestion['job_title'])}</div><div>{badges}</div>",
            unsafe_allow_html=True,
        )
        st.caption(suggestion["reason"])
        columns = st.columns([1, 1, 4])
        if columns[0].button("Accept", key=f"email-accept-{suggestion['id']}", type="primary"):
            result = _call(client, "POST", f"/api/email/suggestions/{suggestion['id']}/accept")
            if result is not None:
                _flash("Applied: " + result["message"])
        if columns[1].button("Dismiss", key=f"email-dismiss-{suggestion['id']}"):
            if (
                _call(client, "POST", f"/api/email/suggestions/{suggestion['id']}/dismiss")
                is not None
            ):
                _flash("Dismissed. The application was not changed.")


def _suggestions_section(client: ApiClient) -> None:
    section_header(
        "Suggested updates",
        "Nothing changes until you press Accept. A change the application's current state "
        "does not allow is refused with the reason.",
    )
    suggestions = _call(client, "GET", "/api/email/suggestions")
    if suggestions is None:
        return
    if not suggestions:
        empty_state(
            "No suggestions waiting",
            "Sync Gmail or paste an email. Confirmations, rejections, interview and "
            "assessment invitations and offers each suggest one update here.",
        )
        return
    for suggestion in suggestions:
        _suggestion_card(client, suggestion)


def _recent_section(client: ApiClient) -> None:
    with st.expander("All tracked emails"):
        page = _call(client, "GET", "/api/email/messages", params={"limit": 100})
        if not page or not page["items"]:
            st.caption("None stored.")
            return
        rows = [
            {
                "Received": local_time(item.get("received_at")),
                "From": item["sender_domain"],
                "Subject": item["subject"],
                "Category": item["category"],
                "Match": item["match_state"],
                "Application": item.get("application_id") or "",
            }
            for item in page["items"]
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)


def render() -> None:
    st.title("Email tracking")
    st.caption(
        "Finds replies to your applications in your own mailbox and suggests the status "
        "change each one implies. Opt-in and read-only."
    )
    client = get_client()

    flash = st.session_state.pop(_FLASH_KEY, "")
    if flash:
        st.success(flash)

    status = _call(client, "GET", "/api/email/status")
    if status is None:
        return

    metric_row(
        [
            ("Suggestions", status.get("pending_suggestions", 0), "waiting for Accept"),
            ("Needs your pick", status.get("needs_review", 0), "ambiguous matches"),
            (
                "Mailbox",
                "connected" if status.get("connected") else "not connected",
                "read-only",
            ),
        ]
    )
    _connection_section(client, status)
    _paste_section(client)
    _suggestions_section(client)
    _review_section(client)
    _recent_section(client)
