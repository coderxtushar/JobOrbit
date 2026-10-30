# Architecture

## Layers

```
┌────────────────────────────────────────────────────────────────┐
│ ui/                Streamlit, 9 views                          │
│                    state in st.session_state only              │
│                    all data access via ui/api_client.py        │
└──────────────────────────┬─────────────────────────────────────┘
                           │  HTTP, 127.0.0.1
┌──────────────────────────▼─────────────────────────────────────┐
│ app/api/           routers · Pydantic in/out · one error shape │
│                    no business logic, no SQL                   │
└──────────────────────────┬─────────────────────────────────────┘
┌──────────────────────────▼─────────────────────────────────────┐
│ app/services/      all business logic. No SQL, no HTTP.        │
│ app/sources/       adapters + capability flags                 │
│ app/llm/           optional, tool-free                         │
└──────────────────────────┬─────────────────────────────────────┘
┌──────────────────────────▼─────────────────────────────────────┐
│ app/db/repositories/   every query in the project              │
│ app/db/models.py       SQLAlchemy 2.x                          │
└────────────────────────────────────────────────────────────────┘
```

Dependencies point one way. The UI has no database driver and no ORM import; the API layer
has no SQL; the services layer has no HTTP client. Each rule is load-bearing rather than
decorative:

- **UI → HTTP only** is what lets a React frontend replace Streamlit without touching
  anything else, and it is why the dashboard can be tested against a stub client.
- **Services have no SQL** is what makes them unit-testable with plain objects, which is
  how the scoring edge cases are covered without a database round trip.
- **Queries live only in repositories** is what makes the PostgreSQL migration a
  connection-string change. There is exactly one piece of dialect-specific code in the
  project (`PRAGMA foreign_keys=ON` for SQLite, in `app/db/base.py`).

## The pipeline

```
file / mailbox
      │
      ▼
SourceAdapter.discover() | .import_payload()      app/sources/
      │   → RawJobRecord (validated, provenance required)
      ▼
normalize_record()                                 app/services/normalization.py
      │   → canonical values; unparseable fields become None, raw text preserved
      ▼
compute_fingerprint()                              app/services/dedup.py
      │
      ▼
JobIngestService.ingest()                          app/services/ingest.py
      │   source_id → canonical_url → fingerprint
      │   new job, or enrich an existing one + add a JobSourceReference
      ▼
evaluate() hard filters                            app/services/filters.py
      │   → reasons, not numbers
      ▼
score_job() six weighted categories                app/services/matching.py
      │   → JobMatch with per-category scores and explanation lines
      ▼
ApplicationPreparationService.prepare()            app/services/application_prep.py
      │   variant selection · cover letter · answers with provenance
      ▼
READY_FOR_REVIEW ──── the user reviews, approves, and submits on the employer's site
      │
      ▼
ApplicationTracker.transition()                    app/services/tracking.py
```

## Decisions and their reasons

### Filters are separate from scoring
`evaluate()` answers "should this be excluded?" and returns *reasons*. `score_job()`
answers "how well does it fit?" and returns *numbers*. A filtered job is still stored and
still scored, with `filtered_out=True` and its reasons attached, so the UI can explain an
exclusion. Merging the two is what produces a tool that silently drops jobs the user wanted
to see.

Both are conservative by construction: a filter needs *positive* evidence of
ineligibility. Unknown location, unknown employment type and a missing posting date never
trigger rejection, because absence of data is not evidence.

### Unassessable categories are excluded, not zeroed
When a listing gives no posting date, freshness cannot be judged. Scoring it 0 would sink a
good match; scoring it 50 would still drag the total toward the middle. Instead the
category's weight is set to 0 and the remaining weights are rescaled to sum to 1, so the
score reflects only what could actually be assessed — and the explanation names what was
excluded.

### `posted_at` and `discovered_at` are distinct columns
A job discovered today was not necessarily posted today. `posted_at` is nullable and set
only from what the source said; relative phrases like "3 days ago" are resolved at import
and flagged `posted_at_is_approximate`. Discovery time is never substituted.

### Duplicates enrich, never overwrite
Two platforms describe the same role with different detail. Whichever is imported second
must not overwrite the richer version: scalars fill only when currently empty, skill lists
are unioned, and the longest description wins. Before this rule, the stored title depended
on import order and flipped on every re-import. The consequence worth relying on: importing
an unchanged file twice is a true no-op.

### Capability flags live in adapter code, not configuration
Each adapter declares `AdapterCapabilities` with a `policy_basis` string citing the
platform's own terms. The registry computes *effective* capabilities by intersecting the
declaration with user settings, so settings can only narrow. Enabling a capability requires
editing the adapter module and recording the basis in `docs/COMPLIANCE.md` — a `.env` edit
cannot do it. `automated_submission_enabled` is additionally rejected by a validator in
`AdapterCapabilities`, a validator in the `Capabilities` schema, and a database `CHECK`.

### Answer provenance is a column
Every answer records where it came from. Sensitive fields (work authorization, sponsorship,
salary, notice period, experience years, education, legal declarations) are on a deny-list
no generator may fill; they are either `profile_verified` or flagged
`needs_user_input`. `ApplicationTracker` refuses to approve an application while a
sensitive answer is empty or merely `ai_draft`.

### The LLM is a decorator, never a dependency
`NullProvider` implements the full interface and reports itself unavailable, so every
caller must have a rule-based path — and because it is the default in a fresh install and
in tests, that path is the one actually exercised. The interface is text-in/text-out with
no tool surface, so an injection payload inside a job description has nothing to act on.
All third-party text goes through `wrap_untrusted()`, which fences it with a random
per-call marker and a standing data-only instruction.

A generated cover letter is additionally scanned for sensitive claims absent from the
supplied fact list; a draft that trips the scan is discarded in favour of the rule-based
letter.

### Playwright is deliberately absent
The brief allows browser automation "exclusively for workflows permitted by the relevant
platform". The research in `docs/COMPLIANCE.md` found no such workflow: LinkedIn prohibits
browser plugins and automation, Indeed prohibits automating Indeed Apply, Wellfound
prohibits automated systems, and Naukri's terms are unverified. A browser-driver dependency
would therefore exist only to enable a prohibited feature. "Browser assistance" is
implemented as opening the official URL in the user's own browser — a user-initiated
navigation, not automation.

## Testing strategy

| Layer | Approach |
|---|---|
| Pure functions (parsing, normalization, dedup, URL safety, text) | Direct calls, parametrized edge cases |
| Services (matching, filters, tracking, prep) | Real in-memory database, plain ORM objects |
| API | `TestClient` against the real app and a shared in-memory engine |
| Sources | Adapters asserted to *raise with a reason*; IMAP faked at the `imaplib` boundary |
| LLM | `NullProvider` by default; `EchoProvider` to drive the fabrication scan |
| Dashboard | Streamlit `AppTest` against a stub client, asserting empty and error states |

The in-memory engine uses `StaticPool`: each new connection to `:memory:` creates its own
private database, and `TestClient` runs the app on another thread, so without a single
shared connection the API would see an empty schema.

No test touches the network, a platform credential or an LLM key.

## Extending it

**A new job source** — add a module in `app/sources/` subclassing `SourceAdapter` (or
`ImportOnlyAdapter`), declare its capabilities with a cited `policy_basis`, register it in
`app/sources/registry.py`, add the enum member to `SourceName`, and generate a migration.
Nothing in the ingest, scoring or application pipeline changes.

**A new scoring category** — add a `_score_*` function in `app/services/matching.py`
returning a `CategoryScore`, add its weight to `ScoringWeights`, and include it in the
`categories` list. Normalization and redistribution handle the rest.

**PostgreSQL** — set `JA_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db` and run
`alembic upgrade head`.
