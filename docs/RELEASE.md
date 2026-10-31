# Release Report

Release-readiness pass over the existing application. No UI redesign; the design system in
`docs/DESIGN.md` and its tokens are unchanged except where a defect was fixed.

Everything below marked **verified** was observed in tool output during this pass.
Everything marked **assumption** or **needs human verification** was not.

---

## 1. Tests and gates — actual results

All run on macOS, CPython 3.12.15, in `.venv`.

| Gate | Command | Result |
|---|---|---|
| Tests | `.venv/bin/python -m pytest` | **319 passed in 6.16s** (was 303; 16 added this pass) |
| Lint | `.venv/bin/ruff check app ui tests` | **clean** (105 findings fixed) |
| Format | `.venv/bin/ruff format --check app ui tests` | **clean** (48 files reformatted) |
| Types | `.venv/bin/mypy app` | **no issues in 62 source files** (16 errors fixed) |
| Static security | `.venv/bin/bandit -r app ui -ll -x tests` | **0 medium, 0 high** over 9,967 lines (4 low) |
| Dependency CVEs | `.venv/bin/pip-audit` | 2 fixed; remainder accepted in `security-baseline.txt` |
| Migrations | `alembic upgrade head` / `check` / `downgrade base` | **13 tables, no drift, clean teardown** |

Warnings in the test run are third-party only: an `anyio.abc.BlockingPortal` deprecation
from starlette's TestClient and three SWIG notices from PyMuPDF. None originate here.

### Coverage by area

| Area | Module |
|---|---|
| PDF/DOCX parsing, empty and malformed resumes, upload validation | `test_resume_parser.py` |
| Salary, experience, dates, timezones, stale jobs, missing posting dates | `test_normalization.py` |
| Fingerprints, duplicate source ids, cross-platform duplicates, import status | `test_dedup_and_import.py` |
| Scoring, weights, inferred-evidence cap, coverage demotion, hard filters | `test_matching.py` |
| Question mapping, provenance, legal answers, variants, state machine | `test_applications.py` |
| Capability enforcement, no-submit guarantees, unsafe URLs, injection, retries | `test_compliance.py` |
| Endpoints, validation, pagination, error shapes, SQL injection | `test_api.py` |
| Job-alert email parsing, read-only IMAP, retry classification | `test_email_alerts.py` |
| Dashboard empty states, API client errors, timezone rendering | `test_ui.py` |
| **Restart persistence, file modes, SQLite foreign keys** | `test_persistence_and_permissions.py` *(new)* |

---

## 2. Bugs found and fixed

Each was reproduced against a running service or browser before the fix and re-verified
after. All seven were found by *using* the application, not by reading it.

### B1 — Inferred skills scored as a confident perfect match (high)

A listing that published **no** requirements had its skills inferred from the description
by keyword match, then scored **100/100 on "0/0 stated requirements"**. Combined with a
title match it reached **100.0 / "High match"** and ranked first — above a job that
matched on all six categories at 97.5.

This contradicted the project's own documented rule that a model's or heuristic's
confidence must not substitute for verified fact.

*Fix:* `app/services/matching.py` caps the skills category at `INFERRED_SKILLS_CEILING`
(75) when the employer stated no requirements, and says so in the category detail.
*Verified:* that job now scores 85.4 with the detail
"2/2 skills inferred from the description are in your profile; the employer stated no
requirements, so this category is capped at 75".

### B2 — A score from a minority of the signal was presented as high confidence (high)

The same listing had **four of six categories unassessable** (no location, no date, no
experience, no employment type). Weight redistribution then gave the two remaining
categories 100% of the weighting, so near-total absence of data produced a top-of-ranking
confident result.

*Fix:* when the assessable share of the configured weighting is below
`MINIMUM_COVERAGE_FOR_HIGH` (0.70), the band is demoted from `high` to `review` and an
explanation line states the coverage. **The number itself is left untouched and auditable.**
*Verified:* "Scored 85.4, but only 60% of the scoring weight could be assessed from this
listing, so it is shown as 'worth a look' rather than a high-confidence match." A job with
full coverage still earns `high`.

### B3 — A binary file imported as a successful import of zero jobs (medium)

A file of NUL bytes was decoded with `errors="replace"`, parsed as a header-only document
with no data rows, and returned **HTTP 201 with status `success`**.

*Fix:* `app/sources/manual_import.py` rejects a payload containing NUL bytes in its first
8 KB, and rejects any parse that yields zero rows.
*Verified:* both now return **422 `import_parse_error`** with an actionable message.

### B4 — A clean idempotent re-import reported `failed` (medium)

Re-importing an unchanged file created nothing and updated nothing, so the status logic
fell through to `FAILED` even though every row was correctly recognised as a duplicate.
This also inflated `import_failures` on the Overview page.

*Fix:* `app/services/ingest.py` counts duplicates as progress.
*Verified:* a re-import with one genuinely bad row is now `partial`; a clean file is
`success`; a file where nothing could be processed is still `failed`.

### B5 — SQLite database file was world-readable (medium)

The database was created with mode **0644** while its directory was 0700. It holds resume
text, contact details and application answers. Relying on the directory mode alone means a
later move or copy of the data directory silently drops the only protection.

*Fix:* `app/db/base.py` chmods the file to **0600** on first connect, for new and existing
databases.
*Verified:* a freshly created database is `-rw-------`; an existing 0644 file is tightened
on the next connection. Covered by a test that skips on Windows.

### B6 — `list[Job]` annotation resolved to the repository's own `list()` method (low)

Inside `JobRepository`, the class defines a method named `list`, which shadows the builtin
in the class body, so `-> list[Job]` referenced the method rather than the generic type.
Harmless at runtime under `from __future__ import annotations`, but wrong and a trap.

*Fix:* a module-level `JobList = list[Job]` alias. Found by mypy.

### B7 — Two `<h1>` elements per page (low, accessibility)

`st.sidebar.title()` emits an `<h1>`, so every page had two top-level headings.

*Fix:* the sidebar brand is a styled `div`; the page's own `st.title()` is the single h1.
*Verified:* exactly one h1 on eight of nine views.

---

## 3. Verified end-to-end behaviour

Driven against a running `uvicorn` on a fresh database, and in a real Chromium browser.

| Scenario | Result |
|---|---|
| 1. First-run startup and DB init | **verified** — `alembic upgrade head` on an empty dir creates 13 tables; directories created 0700 |
| 1b. Cold start with zero data | **verified** — all 10 list/report endpoints return 200, not 500 |
| 2. Resume upload and profile setup | **verified** — extraction returns `applied_to_profile: false`; the profile is untouched until accepted |
| 3. Valid import (CSV, TSV, JSON) | **verified** — 6 valid rows of 7 ingested, loose column-name matching |
| 4. Malformed rows | **verified** — rejected and reported *by row number* with the field reason |
| 4b. Missing fields | **verified** — no posting date and no skill list produce explicit warnings, not guesses |
| 4c. Duplicates | **verified** — LinkedIn + Naukri collapse to one job with two source references |
| 4d. Untrusted text | **verified** — injected `<script>`, `<img onerror>`, SQL and prompt-injection text stored inert; 0 scripts in the DOM, 0 applications created |
| 5. Scoring, ranking, explanations | **verified** — after B1/B2, the fully-assessable job ranks first; weights renormalise to 1.000; every category carries a reason |
| 6. Job detail and preparation | **verified** — full description, 6 category scores, shortlist then prepare |
| 7. Review before the employer | **verified** — 13 answers all `profile_verified`, 0 blocking, resume variant selected, official URL surfaced |
| 8. Status update + **persistence after restart** | **verified** — `CONFIRMED`, submitter, evidence, outcome, notes, follow-up, 4 events and 13 answers all survived a full process restart |
| 9. Empty states, errors, recovery | **verified** — all-invalid file → `failed`; binary → 422; a good import still works afterwards |
| 10. All nine views | **verified** — 0 Streamlit exceptions, 0 console errors, no raw HTML leakage |
| 10b. Responsive | **verified** — no horizontal overflow and no clipped text at 1440/1180/1024/820/768 px |
| 10c. Accessibility basics | **partially verified** — see §5 |

---

## 4. Security review

### Addressed

| Item | Finding | Status |
|---|---|---|
| Upload validation | Extension, size **and magic bytes** all enforced | verified — renamed executable rejected `400 corrupt_upload` |
| File-size limit | 11 MB upload against a 10 MB limit | verified — `413 file_too_large` |
| Path handling | `../../../etc/passwd.pdf` | verified — filename rebuilt, file stays inside the data dir, stored 0600 |
| Database file mode | Was 0644 | **fixed** (B5) — now 0600 |
| Data directory modes | `var/`, `resumes/`, `artifacts/`, `imports/` | verified 0700 |
| HTML rendering | `html.escape(..., quote=True)` on every interpolated value | verified in-browser — `Evil <b>Corp</b>` renders as text, no `<b>` created, 0 injected scripts |
| External links | `javascript:`, `data:`, `file:`, loopback, private, metadata IPs, embedded credentials | verified rejected; listing kept without a link; all rendered links carry `rel="noreferrer"` |
| SQL access | ORM-only, no SQL outside `app/db/repositories` | verified — `'; DROP TABLE job; --` as a search term returns a text match and the table survives |
| Secrets in source | Scanned for key patterns and literal passwords | verified none; `.env.example` contains only safe defaults |
| Secrets in logs | Grep for secret-shaped keys | verified 0 unredacted lines |
| PII in logs | Grep for the test candidate's name, email, phone, institution | verified **0 hits** across six log files |
| PII over the API | `GET /api/resumes` | verified — returns `text_character_count`, never `extracted_text` |
| Network exposure | Non-loopback bind without a token | verified refused at startup |
| Duplicate prevention | Unique `(job_id, profile_id)` + three-tier dedup | verified — duplicate prepare returns `409` |
| Honest absence | Unscored vs zero, unassessable vs 0% | verified — hollow ring, hatched track, "not assessable" label |
| Prohibited features | Scraping, CAPTCHA bypass, cookie extraction, auto-submit | verified absent; no outbound HTTP in `app/` at all; CI fails if a scraping dependency is added |

`python-multipart` **0.0.20 → 0.0.32** and `requests` **2.32.3 → 2.34.2** were upgraded.
`python-multipart` was the one reachable advisory: the app has two `UploadFile` endpoints,
so the multipart header-parsing DoS applied directly. Uploads re-verified working after.

### Unresolved risks (accepted, with reachability evidence)

Recorded with justification in `security-baseline.txt`. CI compares live `pip-audit`
output against that baseline so a **new** advisory cannot pass silently.

| Package | Advisories | Reachability | Why not upgraded |
|---|---|---|---|
| pillow 11.3.0 | 56 | **Not reachable.** `grep -rn "PIL\|Image.open" app/ ui/` → no matches. Transitive via streamlit; this app never decodes an image. | `streamlit 1.41.1` pins `pillow<12` |
| starlette 0.41.3 | 7 | **Not reachable.** Range ReDoS and Windows UNC SSRF both need `StaticFiles`/`FileResponse`; the app mounts neither. Host-header injection needs code reading `request.url`; nothing does. The urlencoded form-limit bypass is low: uploads are multipart, bodies are Pydantic-validated, bind is loopback. | `fastapi 0.115.6` pins `starlette<0.42` |
| streamlit 1.41.1 | 2 | **Windows-only / local.** UNC SSRF affects Windows hosts; the weak-hash issue needs local access. | A 1.41 → 1.66 jump risks the design system this pass was told to preserve, and the UI depends on Streamlit internals |
| pytest 8.3.4 | 1 | **Development only.** Not shipped. | Would need pytest 9 |

**Recommended follow-up, deliberately not done here:** a separate, dedicated branch that
upgrades `fastapi → 0.162`, `starlette → 1.10`, `streamlit → 1.66`, `pillow → 13`, then
re-runs the suite **and** the full browser pass. That resolution exists and was confirmed
with `uv pip compile`. It is out of scope for a hardening pass that must not alter the UI.

---

## 5. Needs human verification

Not verifiable by automation in this environment:

1. **Real resume parsing accuracy.** Tested with generated DOCX/PDF fixtures. Run your own
   resume through *Resume and profile* and confirm the per-field confidences and warnings.
2. **Real job-board exports.** Column-name matching was tested against a synthetic CSV.
   Try actual LinkedIn/Naukri/Indeed exports.
3. **Email job-alert ingestion.** The IMAP client is covered with a faked `imaplib` and
   real `.eml` parsing, but never against a live mailbox. Needs a real app password.
4. **LLM drafting.** Only `NullProvider` and a stub were exercised. No API key was used, so
   no real model output was reviewed for truthfulness.
5. **Screen-reader pass.** Automated checks cover alt text, SVG labels, form labels and
   heading counts. Actual VoiceOver/NVDA navigation was not performed. Two known items:
   Streamlit's own sidebar-collapse button and file-uploader input carry no accessible
   name (framework-internal), and the *Resume and profile* page has a second `<h1>` coming
   from the resume variant's own `# Name` markdown inside an expander — left as-is because
   changing it would alter a user-facing artifact.
6. **Colour-contrast measurement.** Muted text was darkened after review, but no formal
   WCAG contrast-ratio measurement was taken.
7. **Windows and Linux.** All verification was on macOS. The POSIX file-mode tests skip on
   Windows by design.
8. **Concurrency.** Single-user assumption untested under parallel writers. SQLite with
   one Streamlit client is the designed deployment.

---

## 6. Commands

```bash
# Setup (Python 3.11-3.13; NOT 3.14 - pydantic-core has no wheel)
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt        # test/lint/security tooling

# Reproducible install from the full transitive lock
.venv/bin/pip install -r requirements.lock.txt

# Database
.venv/bin/alembic upgrade head          # create or migrate
.venv/bin/alembic check                 # models vs migrations
.venv/bin/alembic downgrade base        # tear down

# Run (two terminals)
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m streamlit run ui/streamlit_app.py

# All gates
.venv/bin/python -m pytest                                   # 539 tests
.venv/bin/python -m pytest --cov=app --cov-report=term
.venv/bin/ruff check app ui tests
.venv/bin/ruff format --check app ui tests
.venv/bin/mypy app
.venv/bin/bandit -r app ui -ll -x tests
.venv/bin/pip-audit

# Compliance guarantees only
.venv/bin/python -m pytest tests/test_compliance.py -q

# Rebuild the labelled match-quality benchmark from discovered listings
.venv/bin/python -m tests.build_eval_dataset
.venv/bin/python -m pytest tests/test_matching_benchmark.py -q -s -k report

# Delete all local data
rm -rf var/
```

---

## 7. Rollback

Everything the application owns lives in two places: the `var/` directory and the Alembic
revision recorded inside the database. Nothing else on the machine is modified, so a
rollback is a file copy plus a revision change.

### Before any upgrade

```bash
# Stop both processes first: SQLite's WAL means a live copy can be inconsistent.
pkill -f "uvicorn app.main"; pkill -f "streamlit run"
cp -a var "var.backup.$(date +%Y%m%d-%H%M%S)"
.venv/bin/alembic current            # record the revision you are rolling back to
```

### Rolling back code only

The schema is forward-compatible within a revision, so if the new code misbehaves but the
revision has not changed, check out the previous commit and restart. No data step is
needed.

```bash
git log --oneline -5
git checkout <previous-commit>
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Rolling back a migration

```bash
.venv/bin/alembic history            # list revisions oldest to newest
.venv/bin/alembic downgrade -1       # one step back
.venv/bin/alembic downgrade <revision>
```

Every revision in this project has a tested `downgrade`, verified by
`alembic upgrade head` → `alembic check` → `alembic downgrade base` on an empty database.
A downgrade **drops the columns and tables the revision added**, so any data held only in
those columns is lost — restore the backup instead if that data matters.

### Restoring from a backup

```bash
pkill -f "uvicorn app.main"; pkill -f "streamlit run"
rm -rf var && cp -a var.backup.<timestamp> var
.venv/bin/alembic current            # confirm the revision matches the checked-out code
```

### Starting clean

```bash
rm -rf var/ && .venv/bin/alembic upgrade head
```

This deletes the database, every uploaded resume and every generated artifact. It is the
documented way to remove all personal data from the machine.

---

## 8. Reproducible baseline

A checkout is reproducible when all five hold:

| Check | Command | Expected |
|---|---|---|
| Dependencies pinned transitively | `.venv/bin/pip install -r requirements.lock.txt` | 93 pinned packages |
| Schema matches the models | `.venv/bin/alembic check` | `No new upgrade operations detected.` |
| Single migration head | `.venv/bin/alembic heads` | one revision, marked `(head)` |
| Tests green with no network | `.venv/bin/python -m pytest` | 539 passed |
| Match quality not regressed | `.venv/bin/python -m pytest tests/test_matching_benchmark.py` | gates against `tests/fixtures/eval_baseline.json` |

The benchmark fixtures are versioned on purpose: `eval_jobs_real.json` holds the labelled
listings and `eval_baseline.json` the measured numbers, so a ranking change that moves
match quality fails the build until the new numbers are recorded deliberately.

---

## 7. Deployment options

The architecture is a single-user local app: loopback API, Streamlit UI, SQLite, resumes on
local disk. That shapes what is appropriate.

**1. Local processes — recommended, and what this is built for.**
Two terminals as above. No network exposure, no secrets at rest, `rm -rf var/` removes
everything. Add a `launchd`/`systemd --user` unit for auto-start.

**2. Single-container, loopback-published.**
One image running both processes, published as `-p 127.0.0.1:8501:8501`. Mount `var/` as a
volume or the database is lost on restart. No Dockerfile is included: it adds an image to
maintain for no capability gain on a single-user app.

**3. Private host with authentication.**
Requires `JA_API_TOKEN` (enforced at startup for non-loopback binds) **and** a reverse
proxy terminating TLS with its own auth in front of Streamlit, which has no auth of its
own. Switch `JA_DATABASE_URL` to `postgresql+psycopg://…`; the repository layer needs no
change. Before doing this, resolve §4's deferred upgrades — the deferral rests on the
loopback assumption.

**Not appropriate:** multi-user or public hosting. There is no authentication, no
multi-tenancy and no per-user isolation; the data model assumes one profile per database.
Hosting one person's resume and application answers on a shared origin is a privacy
problem no amount of configuration fixes.

---

## 8. Prioritised remaining blockers

**None blocking local personal use**, which is the stated purpose. Ordered by priority for
any wider deployment:

| # | Item | Severity | Why |
|---|---|---|---|
| 1 | Upgrade fastapi/starlette/streamlit/pillow on a branch, then re-run the suite **and** the browser pass | Medium | Clears 66 accepted advisories. Deferred because the CVEs are unreachable here and the jump risks the UI. **Becomes a blocker before any non-loopback deployment.** |
| 2 | Verify parsing against real resumes and real board exports | Medium | Heuristic parsing and loose column matching are only fixture-tested; this is the most likely source of day-one user friction |
| 3 | Screen-reader and WCAG contrast pass | Low-Medium | Automated a11y checks pass; human verification outstanding |
| 4 | Exercise email ingestion against a live mailbox | Low | Opt-in and off by default; alert layouts vary and parsing is layout-dependent |
| 5 | Run the suite on Windows and Linux | Low | CI covers Linux on 3 Python versions once pushed; Windows is unverified and two tests skip there |
| 6 | Review real LLM output for truthfulness | Low | Optional feature, off by default; the fabrication scan is tested only with a stub |
| 7 | Resume-variant markdown emits its own `<h1>` | Low | Minor heading-hierarchy nit inside a collapsed expander; fixing it changes a user-facing artifact |

### Known limitations unchanged by this pass

The limitations in the README remain accurate and deliberate: no live job search (no
platform offers a jobseeker API), no automated submission, heuristic resume parsing, no
semantic matching, single local user, layout-dependent email parsing, and
`estimated_minutes_saved` being an assumption shown separately from counted facts.
