# Security audit: auto-apply stack (Phase 3)

Scope: everything that touches the browser runner, submission evidence, email tracking, the
capture extension and the local API. Audited 21 November 2026 against the code in this
working tree. "Fixed" means changed in this phase and covered by a test; "By design" means
the existing behaviour was checked and kept; "Recommended" is for the operator to do.

## Summary

No credential for any job platform or mailbox is stored by JobOrbit, nothing personal is
served by URL, and every new mutating endpoint is either refused or isolated in demo mode.
Five issues were fixed during the audit. The main residual risks are operational: the
`.env` file's permissions, and running the API on a non-loopback address.

## Findings

| # | Area | Finding | Status |
|---|---|---|---|
| 1 | Browser profile | `var/browser/chrome` holds cookies for anything the user signs into in JobOrbit's Chrome window. Created mode 700, inside gitignored `var/`, never the user's everyday profile. JobOrbit never types into a password field: a form showing one is refused before anything is filled. | By design |
| 2 | Authentication state | No platform passwords or session tokens are read, stored or logged. Sign-in, CAPTCHAs and verification codes are always handed to the user with the tab left open. | By design (MFA detection **fixed**: it was previously reported as a missing answer) |
| 3 | Credentials | Gmail refresh tokens are kept in the macOS Keychain (`security` CLI) or, without one, a mode-600 file in `var/secrets` (dir 700). Never in the database, `.env` or logs. OAuth uses PKCE plus a single-use, 10-minute `state`. The callback cannot carry the bearer token (Google redirects the browser), so `state` is its protection; a forged or replayed state returns 400. | By design, tested |
| 4 | Résumé files | Uploads are validated by magic bytes and stored mode 600. The copy staged for a browser upload was left in `var/uploads` indefinitely. | **Fixed**: deleted when the job's tab is released; anything left is swept after a day |
| 5 | Cover letters and answers | Stored in SQLite (mode 600). Artifacts sent to an employer are now locked: the ORM refuses to change or delete them. Sensitive answers are masked in `answers_sent` and in the preflight. | **Fixed / new** |
| 6 | Screenshots | Evidence screenshots were new in this phase, and they may show the user's details. They are written mode 600 into `var/screenshots` (dir 700), served only by `GET /api/autoapply/attempts/{id}/evidence` behind the bearer token, with `Cache-Control: no-store`, and only if the stored path really resolves inside the evidence folder. Deleted after `JA_EVIDENCE_RETENTION_DAYS`. Dry-run screenshots were previously world-readable. | **Fixed** (dry-run permissions), tested (path traversal, retention) |
| 7 | Logs | Strings in log records, attempt events and error details pass through `app.services.redaction.redact` (emails, phone numbers, bearer/API tokens, `code=`/`token=`/`state=` URL parameters, known token prefixes). Secret-named keys were already redacted. | **Fixed**, tested |
| 8 | Email data | Opt-in (`JA_EMAIL_TRACKING_ENABLED=false` by default). Scope is `gmail.readonly` only. The sync query is narrowed to job-related terms and ATS senders. Only messages classified as job-related are kept, with a redacted snippet of 500 characters or fewer; bodies are never stored. Disconnect revokes and deletes the token; `DELETE /api/email/data` removes all mail rows. Meeting and assessment links keep their tokens (the user needs them), as documented. | By design, tested |
| 9 | API authorization | Bound to `127.0.0.1` by default; a non-loopback host without `JA_API_TOKEN` is refused at start-up. Every new router uses the `Authorized` dependency (the OAuth callback is the documented exception, see #3). | By design |
| 10 | Demo mode | All 13 email routes, job capture, the emergency stop, breaker reset, evidence cleanup and evidence download, attempt recheck/resolve and the website fetch are refused in demo mode. Research and interview writes go only to the visitor's isolated copy. An audit test fails if a new mutating route is unclassified. | **Fixed**, tested |
| 11 | SQLite | Database file mode 600 on both the app and Alembic paths (existing test). New columns are added by migration `5830f1dd2837`. The app now refuses to start on an un-migrated database instead of failing mid-run. | **Fixed** (start-up schema check) |
| 12 | Local server exposure | No CORS is enabled. The extension reaches the API through its host permission for loopback only, so no web page can call the API cross-origin, and JSON bodies are required (no form-post CSRF). | By design |
| 13 | Extension permissions | `activeTab`, `scripting`, `storage`; host permissions `http://127.0.0.1/*` and `http://localhost/*` only. No content scripts, no background worker, no cookies/history/tabs permissions. The extractor reads visible text only and never touches cookies, storage, form values or password fields (tested with traps in a real browser). | By design, tested |
| 14 | Git ignore rules | `var/`, `.env*`, keys and résumé files were already ignored. Added: `screenshots/`, `secrets/`, `*.har`, `trace*.zip`, `*.crx`, `extension/*.zip`. Verified that no untracked file in the tree is sensitive. | **Fixed** |
| 15 | Dependencies | No new runtime dependency. The CI guard still bans scraping, stealth and CAPTCHA-solving packages. `bandit -ll` reports no medium or high findings (one SHA-1 use for stable ids was marked `usedforsecurity=False`). | **Fixed** |
| 16 | Personal data in git history | The original résumé PDF remains reachable in public commit `428ede4`. | **Recommended**: rewrite history (e.g. `git filter-repo`) and force-push, or rotate what it exposes |
| 17 | `.env` permissions | The local `.env` is mode 644 (readable by other local users). It holds no secret today, but would if Gmail or LLM keys are added. | **Recommended**: `chmod 600 .env` |

## What was not changed, deliberately

- **No credential collection.** Morrow-style "put your passwords in `.env`" is not
  supported. Sign in by hand in JobOrbit's Chrome window when a site needs it.
- **No CAPTCHA, MFA or bot-detection bypass,** and no hiding that a browser is automated.
- **Streamlit Cloud stays a fictional demo.** The personal runner (browser, mailbox,
  résumé) only runs locally; nothing here uploads browser state anywhere.

## How to verify

```bash
.venv/bin/python -m pytest -o addopts="" -q tests/test_autoapply_reliability.py \
  tests/test_email_tracking.py tests/test_secrets.py tests/test_capture.py \
  tests/test_workspace_and_landing.py tests/test_persistence_and_permissions.py
.venv/bin/bandit -r app ui -ll -x tests
```
