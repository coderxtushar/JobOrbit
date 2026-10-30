# Source capability matrix

Generated from `app/sources/registry.py` on 2026-10-29 and verified by calling each live
endpoint. Four distinct things are kept apart on purpose, because conflating them is how a
tool ends up claiming an integration it does not have:

| Term | Meaning |
|---|---|
| **Live discovery** | The adapter fetches real listings from a documented interface, and that was confirmed against a real board returning real postings. |
| **Authorized submission** | A documented mechanism lets *this candidate* submit an application programmatically. **Nothing in this project has it.** |
| **Manual import** | You supply the listings (CSV/JSON/paste). Always available, never depends on a platform. |
| **Unverified integration** | Code exists and a basis is documented, but it has not been confirmed against live data. Treated as untrustworthy until it is. |

## The matrix

| Source | Manual import | Live discovery | Browser assist | Authorized submission | Verification status |
|---|---|---|---|---|---|
| Manual JSON/CSV | yes | n/a | yes | **no** | Verified — used throughout the test suite |
| CSV upload | yes | n/a | yes | **no** | Verified |
| Job-alert email (IMAP) | yes | **yes**, opt-in, off by default | yes | **no** | Parsing verified offline; no live mailbox tested |
| **Greenhouse** | yes | **yes** | no | **no** | **Verified live** — 19 postings from a real board, `first_published` present |
| **Lever** | yes | **yes** | no | **no** | **Verified live** — 89 postings from a real board |
| **Workable** | yes | **yes** | no | **no** | **Verified live** — 28 postings across 3 real boards; field mapping corrected against them |
| LinkedIn | yes | no | yes | **no** | Import only by policy (User Agreement s.8.2) |
| Indeed | yes | no | yes | **no** | Import only by policy; Indeed Apply automation expressly prohibited |
| Naukri | yes | no | yes | **no** | Import only; **terms could not be retrieved**, so defaults to most restrictive |
| Wellfound | yes | no | yes | **no** | Import only by policy |
| Instahyre | yes | no | yes | **no** | Import only; no jobseeker API, login-gated |
| Cutshort | yes | no | yes | **no** | Import only; no jobseeker API, login-gated |
| Hirist | yes | no | yes | **no** | Import only; no jobseeker API |
| Workday | yes | no | yes | **no** | Import only **deliberately** — a tenant feed is reachable but is an internal interface |
| Company career page | yes | no | yes | **no** | Import only; no single operator to authorize |

`automated_submission_enabled` is `False` for all fifteen and cannot be set:
`AdapterCapabilities.__post_init__` raises, the API schema rejects it, the state machine
requires a named human submitter, and the database enforces
`CHECK (NOT automated_submission_enabled)`.

## What changed in this pass

**Workable moved from unverified to verified, and the verification found a real bug.** The
earlier mapping expected a nested `location` object — which is Greenhouse's shape. Workable
exposes flat `city` / `state` / `country` plus a `locations` array, so *every* Workable job
had been stored with an empty location, silently zeroing location scoring and weakening
deduplication. Confirmed against three live boards:

| Board | Jobs parsed | Skipped | Example location |
|---|---|---|---|
| `trailofbits` | 7 | 0 | `United States` |
| `ottimate` | 15 | 0 | `United States`, `Mexico` |
| `huggingface` | 6 | 0 | `Paris, Île-de-France, France` |

Two further improvements came out of the live data: Workable returns the literal string
`"None"` for education (now filtered rather than stored as a requirement), and it publishes
a seniority *label* (`Entry level`, `Associate`, `Mid-Senior level`, `Director`) instead of
a year range. Those labels are now mapped to year bounds, because an unassessable
experience category has its weight redistributed — which is how a director-level posting
previously escaped any seniority penalty.

## On submission, specifically

Greenhouse and Lever both publish application-submission endpoints. They are not used and
are not implemented, for a reason that is not squeamishness: those endpoints authenticate
with a **key issued to the employer**, for the employer's own integrations. A jobseeker has
no credential that authorizes posting an application through them. There is no documented,
candidate-initiated submission API on any source in this project.

If one ever appears, enabling it requires more than a config change: the capability
validator, the API schema, the state machine and a database `CHECK` constraint all have to
be amended together, and `tests/test_compliance.py` asserts every one of them.

## Enabling live discovery for a source that lacks it

1. Read the platform's current terms and locate a clause that permits the access.
2. Record the clause and its URL in [COMPLIANCE.md](COMPLIANCE.md).
3. Change the declared capability in that adapter module.
4. Verify against a real board and record the result here.

Configuration alone cannot do it. `tests/test_compliance.py` asserts that the set of
discovery-enabled sources is exactly `{email_alert, greenhouse, lever, workable}`, so
adding a fifth is a deliberate, reviewed change rather than an accident.
