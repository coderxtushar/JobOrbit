# Job Search Assistant

A local-first job search and application assistant. It reads your resume, imports job
listings you supply, ranks them against your profile with a transparent rule-based score,
and prepares complete, truthful applications for you to review and submit yourself.

**Two things this tool will not do**, because the platforms in scope prohibit them and
because the design would be dishonest otherwise:

1. **It does not scrape any job platform.** LinkedIn, Indeed, Naukri, Wellfound,
   Instahyre, Cutshort and Hirist all prohibit automated collection, and none offers a
   job-search API to an individual jobseeker. Automated discovery happens only where a
   platform publishes an interface for it: the **Greenhouse, Lever and Workable** job-board
   APIs, plus job-alert emails in your own mailbox. Everything else is file import. Every
   citation is in [docs/COMPLIANCE.md](docs/COMPLIANCE.md) and the full per-platform table
   is in [docs/SOURCES.md](docs/SOURCES.md). India-relevant boards, with the measured
   results of a real run, are in [docs/INDIA_SOURCES.md](docs/INDIA_SOURCES.md).
2. **It never applies behind a platform's back.** It does not log in to LinkedIn, Naukri,
   Indeed or Wellfound to click Apply; those platforms prohibit it ("use of any
   automation, scripting, or bots to automate the Indeed Apply process ... is
   prohibited"), and for them the app prepares the application and opens the page so you
   submit it. What it *can* do, once you switch it on, is fill and submit an **employer's
   own Greenhouse, Lever or Ashby application form** in its own Chrome window — the same
   public form you would fill by hand — from answers you have verified. See
   [Auto-apply in the browser](#auto-apply-in-the-browser).

Everything works with **no API key**. The LLM is optional and only ever drafts prose from
facts you have already verified.

---

## Quick start

```bash
cd "Auto apply bot"

# 1. Create the environment with Python 3.11, 3.12 or 3.13.
#    Not 3.14: pydantic-core has no 3.14 wheel yet and will fail to build from source.
#    Check what `python3` is first, because on many machines it is now 3.14.
python3 --version

# Option A - standard library venv, using an explicit interpreter:
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Option B - uv (it will download Python 3.12 if you do not have it).
#   Note: `uv venv` does not install pip, so use `uv pip install` here.
#   uv venv --python 3.12 .venv
#   uv pip install -r requirements.txt

# 2. Optional. Every setting has a safe default, so the app runs without this.
cp .env.example .env

# 3. Create the database schema.
.venv/bin/alembic upgrade head

# 4. Start the API (terminal 1).
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 5. Start the dashboard (terminal 2): the Next.js workspace (needs Node 20+).
cd frontend && npm install && cp .env.example .env.local && npm run dev

# The original Streamlit dashboard still works if you prefer it:
# .venv/bin/python -m streamlit run ui/streamlit_app.py
```

Then open **http://localhost:3000** (or **http://localhost:8501** for the Streamlit
dashboard). The API docs are at **http://127.0.0.1:8000/docs**. The Next.js app is
described in [frontend/README.md](frontend/README.md).

### First run, in order

1. **Resume and profile** → upload your PDF or DOCX. The parser shows what it found; it is
   a proposal, and nothing reaches your profile until you press *Accept into my profile*.
2. Still on that page, fill in **Verified answers** (work authorization, notice period,
   salary, graduation date). Anything you leave blank is flagged for manual entry on every
   application rather than guessed.
3. **Job discovery** → upload a CSV or JSON file of jobs. Press *Download a CSV template*
   if you want the expected shape. Column names are matched loosely, so most board exports
   import unedited.
4. **Job feed** → press *Score all jobs*. Open *Why this score* on any card to see the
   per-category breakdown.
5. **Bulk preparation** → select by band, score and freshness, press *Count matches*, then
   *Prepare them*. A hundred-plus jobs are prepared in one run, and it can be stopped and
   resumed. See [docs/BULK_WORKFLOW.md](docs/BULK_WORKFLOW.md).
6. **Action inbox** → answer each outstanding question **once**. It is written to every
   open application waiting on it and reused on every future one.
7. **Review queue** → edit the cover letter and answers, mark approved, open the official
   page, submit it yourself, then record what happened.
8. **Application tracker** → record outcomes, follow-up dates and interview stages.

---

## The two surfaces

One Streamlit app serves a public landing page and a private workspace.

**The landing page** is the root URL. It renders markup and reads `JA_DEMO_MODE`, and does
nothing else: no API start, no database session, no migration, no demo seed. Arriving costs
a template render, which is asserted two ways — a test walks its AST for banned calls, and
a browser run confirms no database file is created. Its stylesheet hides the sidebar, so
the operational chrome only appears once you are inside.

**The workspace** is 20 pages across four sections. Routing is `st.navigation`, so every
page has a real URL that survives refresh, bookmarking and the back button:

| Section | Pages |
|---|---|
| Main | Overview · Set up your search · Resume and profile · Job discovery · Job feed · Job detail · Saved searches |
| Platform assistants | Naukri · LinkedIn · Indeed · Wellfound · ATS & other platforms |
| Applications | Auto-apply · Bulk preparation · Action inbox · Review queue · Application tracker · Analytics |
| System | Settings and sources · Logs and diagnostics |

`/overview`, `/linkedin`, `/review` and the rest are all deep-linkable. The embedded API is
started by one wrapper shared by every workspace page, so it comes up lazily on whichever
page you open first — including a deep link — and never from the landing page.

## The auto-apply engine

One click authorises a whole run inside the scope you set: discover from the authorized
sources, score, filter, prepare each application, dispatch it **where a provider permits
dispatch**, verify the outcome, and record what happened. `POST /api/autoapply/runs` is
that click, and `dry_run` defaults to true so the first run prepares everything and sends
nothing.

**Where it can dispatch.** By default, nowhere: every platform reports submission
unsupported with its own citation ([docs/SUBMISSION_FEASIBILITY.md](docs/SUBMISSION_FEASIBILITY.md)).
With `JA_BROWSER_SUBMISSION_ENABLED=true`, jobs whose application form is hosted on
**Greenhouse, Lever or Ashby** are filled and submitted in the browser — see
[Auto-apply in the browser](#auto-apply-in-the-browser). LinkedIn, Indeed, Naukri, Wellfound,
SmartRecruiters, Workable and unrecognised career sites stay unsupported.

The loopback test server (`tests/support/application_server.py`) is still the provider the
API-submission path is verified against. It is unregistered unless
`JA_LOCAL_SUBMISSION_BASE_URL` is set, and refuses any non-loopback address.

### Auto-apply in the browser

```bash
# .env
JA_BROWSER_SUBMISSION_ENABLED=true
JA_GREENHOUSE_BOARDS=groww,druva          # the company boards to discover from
JA_LEVER_BOARDS=cred,meesho
JA_ASHBY_BOARDS=sarvam,atlan
```

Restart the API (after `.venv/bin/alembic upgrade head` if you are upgrading), then on the
**Auto-apply** page press **Build preflight**. The preflight lists every job in scope with
its score, evidence, location and experience fit, the resume and answers that would be
sent, the questions still open and whether its platform can be submitted to. Jobs a hard
constraint removes are listed with the reason. Untick anything you do not want, run once
with **Dry run on** (each form is filled and screenshotted without being submitted), then
build the preflight again with Dry run off and start the run. A live run covers only the
jobs ticked in a current preflight.

For every job, in order:

1. The employer's form opens in JobOrbit's **own Chrome profile** (`var/browser/chrome`,
   never your everyday profile). Nothing is ever logged into for you.
2. Every question is read off the live page — text boxes, selects, comboboxes, radios,
   Ashby's yes/no buttons, checkbox groups, file inputs, including shadow DOM.
3. Each question is matched to a stored answer. **Anything not on file is raised in the
   Action inbox and that job waits**; answer it once and every later form asking the same
   thing is filled from it. "Years of experience with Java" is never answered with your
   total experience; a consent box is ticked only from your own answer to that exact text.
4. Your **uploaded resume PDF** is attached.
5. The page is checked against the queued job's title and company — before filling and
   again just before Submit — so a different job that happens to be open is never applied to.
6. Submit is pressed, and the outcome is read back: a new confirmation message or a
   confirmation page counts as **submitted and confirmed**; a CAPTCHA leaves the tab open as
   **needs you**; a form error is **failed** (nothing was accepted); silence is **outcome
   unverified**, which is never retried.

Pace and limits: a randomised pause between every action and 20–60 s between applications,
at most `JA_BROWSER_DAILY_SUBMISSION_CAP` (default 25) a day, and a live run works in the
background so Pause and Stop take effect between jobs. CAPTCHAs are never solved and
automation is never hidden from the site. Settings are in [Configuration](#configuration).

A run reports these separately and never sums them:

| Figure | Meaning |
|---|---|
| eligible | matched the run's scope |
| prepared | a complete application exists — **not sent** |
| submitted and confirmed | a provider acknowledged receipt and returned an identifier |
| needs an answer | a required answer is missing, or a CAPTCHA/MFA needs a person |
| platform permits none | prepared for you to send yourself |
| outcome unverified | the request left this machine and nothing came back |

The last row is the one worth understanding: it is **never retried automatically**, because
retrying an unknown outcome is how one application silently becomes two. Open the attempt's
**Evidence and timeline** to recheck the tab, or record what you found ("it was submitted",
with your evidence, or "it was not submitted", which lets a later run try again).

#### Reliability

| Mechanism | What it guarantees |
|---|---|
| Checkpoints | `submit_requested` is committed *before* Submit is pressed. A worker that dies after it leaves an unknown outcome, never a silent retry; one that dies before it leaves a safe retry. |
| Crash recovery | A run whose heartbeat is older than `JA_RUN_STALE_AFTER_S` is marked interrupted at start-up and its in-flight attempt settled from its checkpoint. |
| Job locks | One worker per job across runs and processes; a dead worker's lock expires after `JA_JOB_LOCK_TTL_S`. |
| Duplicate check | Re-read immediately before dispatch: a job you marked submitted meanwhile, or that another run reached, is not sent. |
| Retry policy | Only transient failures (page load, browser crash, timeout, upload) are retried, with exponential backoff from `JA_RETRY_BACKOFF_S`. A wrong page, a closed posting or a rejected form is not. |
| Circuit breaker | `JA_CIRCUIT_BREAKER_THRESHOLD` consecutive platform failures (CAPTCHAs, timeouts, unreadable outcomes) pause that platform for 30 minutes. |
| Emergency stop | Cancels every run, refuses new ones and is checked at the last checkpoint before Submit, until you clear it. |
| MFA / CAPTCHA / sign-in | Detected and handed to you with the tab left open. Never solved, read or bypassed. |
| Evidence | Every attempt keeps its answers sent (sensitive ones masked), locked copies of the resume hash, answers and profile snapshot, a redacted event timeline, its duration, and an owner-only screenshot served only through the authorised API. Kept `JA_EVIDENCE_RETENTION_DAYS` days. |

Salary questions are answered in the unit the form asks for. A saved "12 LPA" is typed into
a free-text "Expected CTC" box as it is, but a form asking for a monthly figure, USD or a
bare LPA number gets nothing until you approve the converted value, which is then kept for
that unit. Current and expected pay are never substituted for each other.

### Email tracking, job capture, research and interview prep

- **Email tracking** (opt-in, read-only Gmail OAuth). Job-related mail is classified
  (confirmation, rejection, interview, assessment, offer...), matched to applications, and
  turned into *suggested* status changes you accept or dismiss. Nothing is applied
  automatically; ambiguous matches wait in a review inbox. Setup, scopes and what is stored
  are in [docs/EMAIL_TRACKING.md](docs/EMAIL_TRACKING.md). Without Gmail you can paste an
  email on the **Email tracking** page.
- **Job capture extension** for platforms with no discovery integration (LinkedIn, Naukri,
  Indeed, Wellfound, careers pages). It runs only when you click it, reads only the page you
  are on, and sends the listing into the normal pipeline (deduplicated, scored, explained).
  It never submits. See [extension/README.md](extension/README.md).
- **Company research** built only from sources it can cite (your stored listings, their
  "About" sections, optionally the company website you name), and **interview preparation**
  with job-, resume-, project- and gap-based questions, mock-interview practice and your
  own round notes. Both are on the **Company and interview prep** page.
- **Outcome analytics**: attempts, confirmations, unknown outcomes, interviews and offers by
  source, job family, employer and score band. Rates need at least five sent applications;
  "time saved" is labelled as an estimate.

### Platform assistants

The five platform sections are a *view* of the source adapters, not a second source of
truth. Each one names the `SourceName` values it covers; every capability, policy citation,
limitation and count is read back from the adapter and the database at request time through
`GET /api/platforms/{key}`. A hand-written capability list would drift from the adapters,
and the one thing this project must not get wrong is telling you a platform supports
something it does not.

Three rules the pages follow:

- **No count is invented.** A platform with nothing stored says so, in an empty state.
- **Unavailable actions are shown, not hidden.** "This platform publishes no search API" is
  information; a missing button looks like an unfinished feature.
- **Submission is labelled permanently unavailable** on every platform, and the adapter
  dataclass plus a database `CHECK` constraint make that impossible to override.

Only the ATS group reports automated discovery, because only those publishers expose an
interface whose documented purpose is serving one company's own board. The other four are
import-only *by policy*, and each page quotes the specific reason.

---

## Deploying a public demo

This app normally runs as **two processes** — a FastAPI service and a Streamlit dashboard
that talks to it only over HTTP. Streamlit Community Cloud runs exactly one process, so a
plain deployment shows "Cannot reach the API" on every page. Two things close that gap.

**The dashboard starts the API itself when there is nothing to connect to.**
[`ui/embedded_api.py`](ui/embedded_api.py) runs the migrations and then serves the API on
loopback inside the same container, once per process. It is a no-op locally, where the API
is already listening, and a no-op when `JA_API_BASE_URL` names an API elsewhere, so a real
two-process deployment is never hijacked.

**Demo mode replaces your data with sample data.** A shared URL has no per-user login, so
`JA_DEMO_MODE=true` seeds a fictional candidate plus seven listings and **refuses the writes
whose cost or blast radius lands on somebody else**:

| Refused in demo mode | Why |
|---|---|
| Resume upload | No per-user login, so one visitor's resume would be readable by the next |
| Job import (JSON and CSV) | Writes arbitrary text that every later visitor would see |
| Discovery runs | Calls other companies' job-board APIs, spending their rate limit per visitor |
| Bulk preparation runs | A hundred-plus preparations is too expensive for a shared container |
| Source capability changes | Capabilities are a compliance setting, not a preference |

Light writes stay enabled — shortlist, skip, score, prepare one application, answer an
inbox question — because exercising them is the point of the demo and they only touch data
that is already fictional. Every refusal is enforced in the API, not hidden in the UI, so it
holds if somebody calls the endpoint directly, and a test fails if a new mutating route is
added without classifying it.

### Steps

1. Push the repository to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), create an app pointing at
   **`ui/streamlit_app.py`**.
3. Under **Advanced settings → Secrets**, add:

   ```toml
   JA_DEMO_MODE = "true"
   ```

4. Deploy. The landing page appears immediately. The first workspace page you open takes
   about half a minute while migrations run and the sample feed is scored.

The seeded feed is chosen to show every honesty case in one screen: three genuine matches
in the high band, a senior role filtered with its stated years quoted, a content-free
listing that scores 100 and is still demoted to *worth a look* at low confidence, a
support role below the threshold, and a sales role filtered out.

### Sign-in is designed for, not enabled

[`app/auth.py`](app/auth.py) defines `AuthProvider` and `CurrentUser`, and the landing page
marks sign-in "coming soon". **Nothing authenticates anything today**: the only provider
returns the same principal for every request and reports `is_authenticated=False`, because
no credential was presented and none was checked. `st.session_state` is per-session
scratch space and is never treated as a security boundary.

Real sign-in needs four things, in order, and a shared deployment must stay in demo mode
until all four exist:

1. A `user` table and a `user_id` foreign key on `candidate_profile`, `resume`, `job_match`,
   `application` and `saved_answer`. Jobs can stay shared; anything derived from a person
   cannot.
2. `current_principal` resolved from a verified OIDC ID token, not a client-controlled
   header.
3. Authorization in the repository layer, so a query cannot return another user's rows even
   if a route forgets to filter.
4. Per-user artifact paths under `var/` with the owner in the key.

### What not to deploy

**Do not deploy with your own resume.** Streamlit Cloud's filesystem is ephemeral and
shared-by-URL: the database resets on redeploy, and until it does, anyone with the link
reads your profile, your answers and your applications. If you want your real data on a
hosted instance, host the API separately with `JA_API_TOKEN` set and keep the Streamlit app
private — and understand that you are then responsible for a server holding your own PII.

For your own job search, run it locally. That is what the Quick start above does, and it is
the only configuration where your resume never leaves your machine.

---

## Test results

Run the whole suite:

```bash
.venv/bin/python -m pytest
```

Actual output, from this machine (macOS, CPython 3.12.15):

```
........................................................................ [ 89%]
...................................................                      [100%]
595 passed in 38.35s
```

All quality gates, as run in CI:

| Gate | Command | Result |
|---|---|---|
| Tests | `.venv/bin/python -m pytest` | 595 passed |
| Lint | `.venv/bin/ruff check app ui tests` | clean |
| Format | `.venv/bin/ruff format --check app ui tests` | clean |
| Types | `.venv/bin/mypy app` | no issues in 80 files |
| Static security | `.venv/bin/bandit -r app ui -ll` | 0 medium/high |
| Dependency CVEs | `.venv/bin/pip-audit` | see `security-baseline.txt` |

Install the tooling with `.venv/bin/pip install -r requirements-dev.txt`.

No test needs a network connection, a platform credential or an LLM key. The suite covers
every area the brief asked for; `tests/test_compliance.py` in particular asserts the
compliance promises mechanically rather than trusting the documentation:

| Area | Module |
|---|---|
| PDF/DOCX parsing, empty and malformed resumes, upload validation | `test_resume_parser.py` |
| Salary, experience, dates, timezones, stale jobs, missing posting dates | `test_normalization.py` |
| Fingerprints, duplicate source ids, cross-platform duplicates, CSV/JSON import | `test_dedup_and_import.py` |
| Scoring, weights, empty profile, fresher vs senior, hard filters | `test_matching.py` |
| Question mapping, provenance, unverified legal answers, variants, state machine | `test_applications.py` |
| Capability enforcement, no-submit guarantees, unsafe URLs, prompt injection, retries | `test_compliance.py` |
| Endpoints, validation, pagination, error shapes, SQL injection | `test_api.py` |
| Job-alert email parsing, read-only IMAP, retry classification | `test_email_alerts.py` |
| Dashboard empty states, API client errors, timezone rendering | `test_ui.py` |
| Answer bank provenance, one-answer backfill, artifact snapshots | `test_answer_bank.py` |
| 120-job batch, idempotency, retries, cancel, resume after interruption | `test_batch.py` |
| Greenhouse/Lever/Workable mapping, retries, wrong board, import-only basis | `test_ats_sources.py` |
| Ashby and SmartRecruiters mapping, offset and cursor paging, bounded detail fetches, feeds off by default | `test_discovery_sources.py` |
| Required vs preferred vs incidental skills, role-family mismatch, prose experience bars, confidence | `test_ranking_rules.py` |
| precision@10/@20, false-positive rate, recall, measured against a versioned baseline | `test_matching_benchmark.py` |
| Restart persistence, file modes, SQLite foreign keys | `test_persistence_and_permissions.py` |

### Manual verification performed

Beyond the suite, the application was driven end to end:

- **API**: the full workflow over `curl` against a running `uvicorn` — resume upload,
  profile update, CSV import of 6 rows (one cross-platform duplicate, one invalid row, one
  `javascript:` URL), scoring, then every state-machine guard. Re-importing the same file
  three times produced `0 new, 0 enriched, 5 duplicate`, confirming idempotency.
- **Dashboard**: all nine pages opened in a real Chromium browser. The resume was uploaded
  through the file input, accepted into the profile, the CSV imported through the UI
  (`4 new, 1 duplicate, 1 invalid`), jobs scored (`2 high, 2 low, 2 filtered`), and an
  application prepared and inspected across all four tabs. Console errors: 0.
- **Migrations**: `alembic upgrade head` from empty creates 12 tables, `alembic check`
  reports no drift against the models, and `alembic downgrade base` is clean.

---

## Troubleshooting

Every item below was hit and resolved during setup on a real machine.

**`pydantic-core` fails to build / no matching wheel.**
You are on Python 3.14. Check with `python3 --version`. Use 3.11, 3.12 or 3.13 — the
upper bound is declared in `pyproject.toml`.

**`.venv/bin/pip: No such file or directory` after `uv venv`.**
`uv venv` does not install pip. Use `uv pip install -r requirements.txt` instead, or
create the environment with `python3.12 -m venv .venv`.

**`alembic upgrade head` fails with "unable to open database file".**
The `var/` directory did not exist. Fixed in `migrations/env.py`, which now creates the
private data directory before connecting. If you see this on an older checkout, run
`mkdir -p var` first.

**The dashboard shows "Cannot reach the API at http://127.0.0.1:8000".**
The API is a separate process. Start it in another terminal with
`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. If you run the
API on a different port, set `JA_API_PORT` for the dashboard process too.

**`Address already in use` on 8000 or 8501.**
Something is already bound. Find it with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, or pick
another port and set `JA_API_PORT` so the dashboard follows.

**Startup refuses with "JA_API_HOST is not a loopback address".**
Intentional. Binding to a non-loopback interface exposes resume and application data, so
it requires `JA_API_TOKEN` to be set. Prefer leaving the host at `127.0.0.1`.

**A job shows no score, or a category says "not assessable".**
That is the honest result, not a bug. A listing with no posting date cannot be scored on
freshness; the category is dropped from the weighting and labelled. Run *Score all jobs*
on the Job feed if a job shows "Unscored".

**An import reports `partial`.**
At least one row was rejected. The response and the Job discovery page list each bad row
by number with the reason. `failed` means nothing at all could be imported.

**Importing a file reports "this looks like a binary file".**
The upload contained NUL bytes. Export the jobs as CSV, TSV or JSON text.

**Resume parsing found nothing.**
Scanned or image-only PDFs contain no text layer and there is no OCR in this build. Type
the details into the profile form instead.

**`streamlit run` warns about `watchdog`.**
Cosmetic. Install it for faster reloads (`pip install watchdog`) or ignore it.

---

## Architecture

```
ui/            Landing page + workspace (20 pages). Talks to the backend only over HTTP.
  │  http
app/api/       FastAPI routers, Pydantic validation, one error envelope
app/services/  business logic: parsing, normalization, dedup, filters, matching,
               question mapping, application preparation, the status state machine
app/sources/   SourceAdapter protocol + capability flags, one module per source
app/llm/       provider-independent, tool-free, NullProvider by default
app/db/        SQLAlchemy 2.x models, repository layer, Alembic migrations
```

Dependencies point one way only: UI → API → services → repositories → database. No SQL is
written outside `app/db/repositories`, which is what makes the PostgreSQL migration a
connection-string change. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
reasoning and [docs/SCHEMA.md](docs/SCHEMA.md) for the schema diagram.

### Design decisions worth knowing

- **`posted_at` and `discovered_at` are separate columns.** A job discovered today was not
  necessarily posted today. When a source gives no posting date, freshness is reported as
  unassessable and dropped from the weighting rather than guessed.
- **Hard filters are separate from scoring.** Filters produce *reasons*; scoring produces
  *numbers*. An excluded job is still stored, still scored, and shows exactly why it was
  excluded, so nothing silently disappears.
- **Unassessable categories are excluded, not zeroed.** Their weight is redistributed
  across the rest, so missing data does not drag a good match toward the middle.
- **Answer provenance is a column, not a convention.** Every answer is
  `profile_verified`, `resume_extracted`, `ai_draft`, `user_entered` or
  `needs_user_input`, and an application cannot be approved while a sensitive field is
  unanswered or merely AI-drafted.
- **Duplicates enrich, never overwrite.** When the same job arrives from a second
  platform, scalars fill only if empty and skill lists are unioned. Without this the stored
  title depended on import order and flipped on every re-import.
- **The LLM has no tools.** It receives text and returns text, and all third-party text is
  fenced with a random delimiter and a standing data-only instruction, so a job
  description cannot redirect it.

---

## Scoring

A transparent weighted model over six categories, each scored 0-100. Weights are
configurable per profile and normalized before use, so only their ratios matter.

| Category | Default weight | What it measures |
|---|---|---|
| Skills | 35% | Stated requirements present in your profile, weighted 4:1 over preferred |
| Title | 25% | Token overlap with your target titles |
| Experience | 15% | Your years against the stated range, or the title's implied seniority |
| Location | 10% | Work arrangement and preferred locations |
| Freshness | 10% | Age from the *posting* date, if the source gave one |
| Other preferences | 5% | Employment type, salary floor, education requirement |

Bands: **high** 80-100, **worth a look** 65-79, **low** below 65. These are ranking
thresholds, not predictions of interview probability.

Alongside the score, every match reports **evidence coverage** and a **confidence** label
of high, medium or low with the reasons for it. Relevance and confidence are different
questions: a listing can look like a strong match and still be impossible to judge, so a
teaser description that scores 99 is reported as low confidence and is not allowed into the
high band. The score itself is never adjusted — it stays auditable — only the band is.

Skills the employer did not publish as requirements are credited by *where* the description
mentions them: under a requirements heading, under a nice-to-have heading, or merely in
passing. A role from a different discipline cannot earn title credit for sharing a generic
word, and an experience bar stated only in prose is enforced like a structured one.

A skill the listing requires that is absent from your profile is reported as *"not in your
profile"*, never as a judgement that you lack it. Where a listing publishes no explicit
requirements, inferred skills are labelled uncertain and shown as preferred, not required.

---

## Sources and what each can actually do

Twenty-two sources are registered; eleven can fetch jobs automatically. The complete table
with every policy citation, publisher notice and measured result is in
[docs/SOURCES.md](docs/SOURCES.md).

| Source | Import | Automated discovery | Submission |
|---|---|---|---|
| Manual JSON/CSV, CSV upload | yes | n/a (you supply the file) | never |
| Job-alert email (IMAP) | yes | **yes**, opt-in, off by default | never |
| **Greenhouse** | yes | **yes** — public Job Board API, verified live | never |
| **Lever** | yes | **yes** — public Postings API, verified live | never |
| **Workable** | yes | **yes** — public widget API, verified on 3 live boards | never |
| **Ashby** | yes | **yes** — public Posting API, verified on 8 live boards | never |
| **SmartRecruiters** | yes | **yes** — public Posting API, 5,018 postings verified | never |
| **Arbeitnow, Remote OK, Remotive, Himalayas, Jobicy** | yes | **yes**, opt-in, off by default — open job feeds | never |
| LinkedIn | yes | no — User Agreement s.8.2 prohibits bots and scrapers | never |
| Indeed | yes | no — no jobseeker search API; automation of Indeed Apply prohibited | never |
| Naukri | yes | no — terms unverifiable, so defaults to most restrictive | never |
| Wellfound | yes | no — terms prohibit harvesting and automated access | never |
| Instahyre, Cutshort, Hirist | yes | no — no jobseeker API, login-gated listings | never |
| Workday | yes | no — tenant endpoint is internal, not a published integration | never |
| Company career page | yes | no — no single operator to authorize it | never |

A source's capabilities are declared in its adapter module with a policy citation.
Configuration can only *narrow* them; enabling one requires editing the adapter and
recording the basis in `docs/COMPLIANCE.md`. The database additionally enforces
`CHECK (NOT automated_submission_enabled)`.

### Enabling email job-alert ingestion

This is the one authorized discovery path, because the data is your own mail. It is
read-only and off by default.

```bash
JA_EMAIL_INGEST_ENABLED=true
JA_EMAIL_IMAP_HOST=imap.gmail.com
JA_EMAIL_USERNAME=you@example.com
JA_EMAIL_APP_PASSWORD=your-app-specific-password   # never your account password
```

Then press *Run discovery now* on the Job discovery page. Alert emails carry a title,
company and link but rarely a posting date, so those jobs usually cannot be scored on
freshness. The password is read from the environment per run and never stored.

---

## Security and privacy

- Binds to `127.0.0.1`. Pointing `JA_API_HOST` at a non-loopback address without setting
  `JA_API_TOKEN` is refused at startup rather than silently exposing your resume.
- Uploads are validated on extension, size **and magic bytes**, and filenames are rebuilt
  from scratch, so `../../.ssh/authorized_keys` cannot escape the data directory.
- `var/` holds the database, resumes and generated artifacts. It is gitignored, created
  mode 700, and never served as a static route.
- No platform password or session cookie is ever stored.
- Job URLs are checked before being linked: non-http schemes, embedded credentials and
  loopback/private/metadata addresses are rejected and the listing is kept without a link.
- Logs are JSON with secret keys redacted and long values truncated, so resume text and
  credentials cannot reach a log file.
- Screenshots (`var/screenshots`, mode 600) may show your answers, so they are never served
  by URL, only through the authorised API, and are deleted after
  `JA_EVIDENCE_RETENTION_DAYS`. Staged resume copies are deleted after each attempt.
- Log lines and attempt events pass through a redactor that removes email addresses, phone
  numbers, tokens and secret-bearing URL parameters.
- Gmail tokens live in the macOS Keychain (or a mode-600 file when no keychain exists),
  never in the database or `.env`. The scope is `gmail.readonly`.
- Keep `.env` owner-only: `chmod 600 .env`.
- The full audit is in [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).
- To delete everything: stop both processes and remove `var/`.

---

## Configuration

Every variable, its default and its effect are documented in
[`.env.example`](.env.example). The ones that change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `JA_DATABASE_URL` | SQLite in `var/` | Set a `postgresql+psycopg://…` URL to switch backends |
| `JA_GREENHOUSE_BOARDS` | empty | Comma-separated company board slugs to fetch from Greenhouse |
| `JA_LEVER_BOARDS` | empty | Comma-separated company slugs to fetch from Lever |
| `JA_WORKABLE_BOARDS` | empty | Comma-separated subdomains to fetch from Workable |
| `JA_ASHBY_BOARDS` | empty | Comma-separated board slugs to fetch from Ashby |
| `JA_SMARTRECRUITERS_BOARDS` | empty | Comma-separated company identifiers to fetch from SmartRecruiters |
| `JA_FEED_DISCOVERY_ENABLED` | `false` | Master switch for the five open job feeds; each also needs its own switch |
| `JA_BATCH_CONCURRENCY` | `4` | Workers in a bulk preparation run |
| `JA_LLM_PROVIDER` | `none` | `openai` or `openai_compatible` enables AI drafting |
| `JA_SCHEDULER_ENABLED` | `false` | Background discovery. Nothing runs in the background while false |
| `JA_DISPLAY_TIMEZONE` | `Asia/Kolkata` | Display only; all timestamps are stored in UTC |
| `JA_EMAIL_INGEST_ENABLED` | `false` | Opt-in mailbox reading |
| `JA_BROWSER_SUBMISSION_ENABLED` | `false` | Fill and submit Greenhouse/Lever/Ashby forms in the browser during live auto-apply runs |
| `JA_BROWSER_DAILY_SUBMISSION_CAP` | `25` | Most applications submitted through the browser per day |
| `JA_BROWSER_MAX_CONCURRENT_PER_PLATFORM` | `1` | Simultaneous browser submissions on one platform |
| `JA_CIRCUIT_BREAKER_THRESHOLD` | `3` | Consecutive failures that pause a platform for 30 minutes |
| `JA_JOB_LOCK_TTL_S` | `900` | Lease on a job's submission lock |
| `JA_RUN_STALE_AFTER_S` | `180` | Heartbeat age after which a run counts as interrupted |
| `JA_RETRY_BACKOFF_S` | `30` | First retry delay for transient failures, doubled each time |
| `JA_EVIDENCE_RETENTION_DAYS` | `30` | Screenshots and browser events are deleted after this |
| `JA_EVIDENCE_SCREENSHOTS` | `true` | Screenshot every browser attempt's outcome |
| `JA_EMAIL_TRACKING_ENABLED` | `false` | Allow connecting Gmail read-only |
| `JA_GMAIL_CLIENT_ID` / `JA_GMAIL_CLIENT_SECRET` | empty | Your own Desktop OAuth client |
| `JA_SECRET_BACKEND` | `auto` | `keychain` or `file` for OAuth tokens |
| `JA_USD_INR_RATE` | empty | Only used to show USD salaries in INR; never guessed |
| `JA_COMPANY_RESEARCH_EXTERNAL` | `false` | Allow fetching a company website you name |
| `JA_MINUTES_PER_MANUAL_APPLICATION` | `12` | Basis of the "time saved" estimate |
| `JA_BROWSER_BETWEEN_APPLICATIONS_MIN_S` / `_MAX_S` | `20` / `60` | Random pause between two submitted applications |
| `JA_BROWSER_PROFILE_DIR` | `var/browser/chrome` | JobOrbit's own Chrome profile; never point it at your everyday one |
| `JA_BROWSER_HEADLESS` | `false` | Keep false: you need to see the window to finish CAPTCHAs |

Optional LLM support: `.venv/bin/pip install -e '.[llm]'`.

---

## Known limitations

These are real and deliberate, not oversights.

0. **Browser submission covers three form providers.** Greenhouse, Lever and Ashby hosted
   forms are filled and submitted; a Greenhouse job whose listing points at the company's own
   careers site (not a `greenhouse.io` URL) is not yet routed to its hosted form. All three
   providers run an invisible CAPTCHA; when it escalates to a visible challenge the job
   becomes *needs you*, so some share of applications will always end with you pressing
   Submit. Salary answers are sent as recorded — there is no LPA/annual/monthly conversion.
1. **No live job search.** The central limitation. No platform in scope offers a jobseeker
   search API, so there is no compliant way to fetch listings automatically. Discovery is
   file import plus opt-in email alerts. The adapter interface is complete, so an
   authorized API can be added without touching the pipeline.
2. **No automated form filling or submission.** The app prepares answers for you to copy
   and opens the official page. Playwright is deliberately not a dependency: no platform
   authorizes browser automation against it, so the dependency would exist only to enable a
   prohibited feature.
3. **Resume parsing is heuristic.** Section- and pattern-based, so unusual layouts will be
   parsed imperfectly. It reports per-field confidence and warns about missing sections,
   and the review screen exists precisely because of this. Scanned/image PDFs yield no
   text; there is no OCR.
4. **Naukri's terms could not be verified programmatically**, so that adapter defaults to
   the most restrictive setting and says so, rather than assuming a permission.
5. **No semantic matching yet.** Scoring is rule-based over a canonical skill alias table.
   A genuinely novel skill name will not be recognised; add it to your profile explicitly.
6. **Single local user.** No multi-tenancy, no login, no sharing.
7. **Email alert parsing is layout-dependent.** Alert templates change, and the diagnostics
   page reports when messages were read but nothing could be extracted rather than silently
   returning zero jobs.
8. **`estimated_minutes_saved` is an assumption**, not a measurement, and is shown in a
   separate "Estimates" section for that reason.

---

## Roadmap

1. Optional embedding-based reranking *on top of* the rule-based score, with both shown,
   so the deterministic score stays auditable.
2. Export the review queue to a filled PDF/DOCX pack per application.
3. Follow-up reminders and a weekly digest built on the existing `follow_up_date` field.
4. An authorized ATS integration (Greenhouse, Lever and Workable publish real public job
   APIs for a company's own board) — genuine automated discovery within clear terms.
5. A React frontend against the same API; the UI already talks only over HTTP.
6. OCR fallback for scanned resumes.
7. Interview preparation notes generated from the job description and your matched skills.

---

## Project layout

```
app/
  config.py  logging_conf.py  main.py  scheduler.py
  api/      deps.py  errors.py  routes/{health,profile,resumes,jobs,applications,sources}.py
  db/       base.py  models.py  repositories/
  llm/      base.py  null_provider.py  openai_provider.py  factory.py
  schemas/  common.py  profile.py  resume.py  job.py  application.py  source.py
  services/ resume_parser.py  resume_variants.py  normalization.py  dedup.py
            filters.py  matching.py  scoring.py  ingest.py  questions.py
            application_prep.py  tracking.py  metrics.py  storage.py
            url_safety.py  text.py
  sources/  base.py  registry.py  manual_import.py  email_alerts.py
            linkedin.py  indeed.py  naukri.py  wellfound.py
ui/         streamlit_app.py  api_client.py  components.py  views/
tests/      conftest.py + 23 test modules (595 tests) + fixtures/ (labelled benchmark)
docs/       PLAN.md  COMPLIANCE.md  ARCHITECTURE.md  SCHEMA.md  API.md  DESIGN.md
            RELEASE.md
.github/    workflows/ci.yml - tests, lint, types, security on 3.11/3.12/3.13
migrations/ Alembic environment and the initial revision
var/        gitignored: database, resumes, artifacts, import payloads
```

## Licence and intent

Written for personal use by a single jobseeker on their own data. It is not a scraping
tool, not a bulk application bot, and not safe to point at someone else's account.
