# Stage 1 — Repository Inspection and Implementation Plan

## Repository inspection (actual findings)

The working directory `/Users/apple/Desktop/Auto apply bot` contained **no source files** — only
`.kiro/` and `.omo/` tool-state directories. There is no git repository. Nothing existed to preserve,
so this is a greenfield build and modern practice applies rather than matching an existing style.

Runtime actually available on this machine:

| Tool | Version | Notes |
|---|---|---|
| Homebrew Python | 3.14.7 | Too new for several wheels (PyMuPDF) |
| System Python | 3.9.6 | Too old for SQLAlchemy 2.x typing style used here |
| `uv` | 0.13.0 | Used to provision the interpreter |
| Provisioned venv | **CPython 3.12.15** | `uv venv --python 3.12 .venv` |

Decision: pin development to Python 3.12 in `.venv`. `requires-python = ">=3.11"`.

## Architecture

Four layers, one direction of dependency (UI → API → services → repositories → DB).

```
┌──────────────────────────────────────────────────────────────┐
│ ui/  Streamlit dashboard (9 pages)                           │
│      talks to the backend ONLY over HTTP via ui/api_client   │
└───────────────────────────┬──────────────────────────────────┘
                            │  HTTP (127.0.0.1)
┌───────────────────────────▼──────────────────────────────────┐
│ app/api/  FastAPI routers · Pydantic request/response models │
│           pagination · uniform error envelope · no auto-submit│
└───────────────────────────┬──────────────────────────────────┘
┌───────────────────────────▼──────────────────────────────────┐
│ app/services/  business logic, no SQL, no HTTP               │
│   resume_parser  normalization  dedup  filters  matching     │
│   application_prep  questions  tracking(state machine)       │
│   storage  url_safety  metrics                               │
├──────────────────────────────────────────────────────────────┤
│ app/sources/   SourceAdapter protocol + capability flags     │
│   manual_import(JSON/CSV) email_alerts linkedin indeed       │
│   naukri wellfound                                           │
├──────────────────────────────────────────────────────────────┤
│ app/llm/       provider-independent; NullProvider is default │
└───────────────────────────┬──────────────────────────────────┘
┌───────────────────────────▼──────────────────────────────────┐
│ app/db/  SQLAlchemy 2.x models · repositories · Alembic      │
│          SQLite local, PostgreSQL-portable                   │
└──────────────────────────────────────────────────────────────┘
```

Key architectural decisions and why:

1. **Repository layer, not raw ORM in routes.** Routes and services never build queries. This is what
   makes the PostgreSQL migration a URL change: no SQLite-specific SQL leaks upward.
2. **Hard filters are separate from scoring.** A filter returns a *reason*; a score returns *numbers*.
   Mixing them is what produces "the bot silently dropped a job I wanted".
3. **Capability flags live in the source adapter, not in config.** A capability cannot be switched on
   by editing `.env`; it requires a documented legal basis recorded in the adapter module itself.
4. **Answer provenance is a first-class column**, not a convention. Every stored answer carries
   `profile_verified | resume_extracted | ai_draft | user_entered`, and the preview refuses to present
   an `ai_draft` for a sensitive field.
5. **`posted_at` and `discovered_at` are separate non-nullable-distinct columns.** Freshness scoring
   uses `posted_at` and degrades to "unknown" when it is absent, rather than substituting discovery time.
6. **The LLM is a decorator, never a dependency.** `NullProvider` implements the full interface with
   deterministic template output, so every code path is exercised by the default test run.

## Project structure

```
app/
  config.py  logging_conf.py  main.py  scheduler.py
  db/      base.py  models.py  repositories/{profile,resumes,jobs,matches,applications,sources,audit,imports}.py
  schemas/ common.py  profile.py  resume.py  job.py  application.py  source.py
  services/ resume_parser.py  resume_variants.py  normalization.py  dedup.py
            filters.py  matching.py  questions.py  application_prep.py
            tracking.py  storage.py  url_safety.py  metrics.py  text.py
  sources/ base.py  registry.py  manual_import.py  email_alerts.py
           linkedin.py  indeed.py  naukri.py  wellfound.py
  llm/     base.py  null_provider.py  openai_provider.py  factory.py
  api/     deps.py  errors.py  routes/{health,profile,resumes,jobs,applications,sources,audit,metrics}.py
ui/        streamlit_app.py  api_client.py  components.py  pages/*.py
tests/     conftest.py + 14 test modules
docs/      PLAN.md  COMPLIANCE.md  ARCHITECTURE.md  SCHEMA.md  API.md
migrations/  alembic env + versions
var/         (gitignored) sqlite db, uploaded resumes, generated artifacts
```

## Dependencies

Chosen: FastAPI, Uvicorn, Pydantic 2 + pydantic-settings, SQLAlchemy 2.0, Alembic, APScheduler,
PyMuPDF, python-docx, Streamlit, requests, httpx, pytest. Exact pins in `requirements.txt`.

Deliberately **not** used:

- **pandas** — the only tabular need is CSV import; `csv` from the standard library covers it without a
  50 MB dependency.
- **Playwright** — see Risks. No platform in scope authorizes browser automation against it, so a
  browser-driver dependency would exist only to enable a prohibited feature. "Browser assistance" is
  implemented as opening the official application URL in the user's own browser (`webbrowser`), which
  is a user-initiated navigation, not automation.
- **Celery/Redis/Docker** — single-user local app; APScheduler in-process is sufficient.
- **Semantic embeddings** — deferred to the roadmap. Rule-based scoring is the contract; embeddings
  would be an optional reranker, and shipping them first would hide scoring bugs behind a black box.

## Implementation plan (stage → exit criterion)

| Stage | Content | Exit criterion |
|---|---|---|
| 1 | This document, venv, manifests, `.env.example`, `.gitignore` | Deps install cleanly |
| 2 | Config, logging, 12 models, repositories, schemas, resume parsing, normalization, dedup, filters, matching, manual import, API, Streamlit | Import a CSV of jobs, see ranked results in the browser, with no API key |
| 3 | Resume variants, cover letters, question mapping, provenance, application preview, status state machine | Prepare an application, edit it, approve it, open the real page |
| 4 | Source adapters for LinkedIn/Indeed/Naukri/Wellfound with capabilities grounded in researched policy; opt-in email-alert ingestion | Each adapter either works or states precisely why it cannot |
| 5 | Full pytest suite, run it, fix failures | Actual test output pasted into the README |
| 6 | README, API docs, schema diagram, limitations, roadmap | Clean install from the README by a reader |

## Risks and assumptions

**R1 — No jobseeker-facing job-search API exists for the four named platforms.** This is the central
risk to the stated product objective. LinkedIn's job APIs are partner/employer gated, Indeed retired
its public Job Search API, Naukri has no public jobseeker API, and Wellfound has none. Mitigation: the
adapter interface is real and complete, and each platform adapter reports its unsupported capabilities
explicitly instead of pretending. Discovery in practice flows through manual CSV/JSON import and
opt-in email job-alert ingestion. This is documented, not hidden. Stage 4 findings are recorded with
citations in `docs/COMPLIANCE.md`.

**R2 — Automated application submission is prohibited and is not implemented.** There is no code path,
no endpoint, and no UI control that submits an application. The highest-privilege action available is
"open the official page in your browser". `automated_submission_enabled` is a flag that is `False` for
every adapter and is additionally gated by an assertion in the tracking service.

**R3 — Resume parsing from unstructured PDFs is heuristic.** A regex/section-based parser will miss
unusual layouts. Mitigation: the parser reports a per-field confidence and the extracted profile is
presented in an editable confirmation screen; nothing is committed to the profile until the user
accepts it. The parser never invents a field it did not find.

**R4 — Prompt injection via job descriptions.** Imported descriptions are untrusted input. Mitigation:
descriptions are stored as data, never concatenated into a system prompt; the LLM wrapper wraps all
job-derived text in an explicit untrusted-data delimiter with a standing instruction that content
inside it is never an instruction; and the LLM has no tool access at all.

**R5 — Fabrication risk in generated content.** Mitigation: generation is restricted to re-ordering and
re-phrasing facts that exist in the parsed resume and the verified profile. Sensitive fields (work
authorization, salary, notice period, experience years, education, certifications, legal declarations)
are on a deny-list that no generator may fill; they are either `profile_verified` or flagged for
manual entry.

**A1** Single local user; no multi-tenancy, no login, loopback binding.
**A2** The user's own resume is the only source of truth about the user.
**A3** The user supplies verified values for salary, notice period, work authorization and graduation
date through the profile screen; the app ships them empty and never guesses.
