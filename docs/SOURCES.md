# Sources: what each platform can actually do

Twenty-two sources are registered. Eleven of them can fetch jobs automatically: your own
mailbox, five per-company ATS board APIs, and five open job feeds. The remaining eleven are
import-only, and the reason for each is recorded below. That split is the honest result of
calling each platform's published interface, not of giving up early.

Capability flags are declared in the adapter module and are a **ceiling**. Configuration
and the UI can only narrow them, never widen them, so no setting turns on something the
adapter has no documented basis for. `automated_submission_enabled` is `False` everywhere,
rejected by a validator in `AdapterCapabilities.__post_init__`, and additionally refused by
the database through `CHECK (NOT automated_submission_enabled)`.

## Summary

| Source | Import | Automated discovery | Submission | Implementation status |
|---|---|---|---|---|
| Manual JSON/CSV | yes | n/a — you supply the file | never | Complete, verified |
| CSV upload | yes | n/a | never | Complete, verified |
| Job-alert email (IMAP) | yes | **yes**, opt-in, off by default | never | Complete; parsing is layout-dependent |
| **Greenhouse** | yes | **yes** | never | **Complete, verified against a live board** |
| **Lever** | yes | **yes** | never | **Complete, verified against a live board** |
| **Workable** | yes | **yes** | never | **Complete, verified against three live boards** |
| **Ashby** | yes | **yes** | never | **Complete, verified against eight live boards** |
| **SmartRecruiters** | yes | **yes** | never | **Complete, verified against a live board with 5,018 postings** |
| **Arbeitnow** | yes | **yes**, opt-in, off by default | never | **Complete, verified; 600 jobs over 2 pages** |
| **Remote OK** | yes | **yes**, opt-in, off by default | never | **Complete, verified; 99 jobs** |
| **Remotive** | yes | **yes**, opt-in, off by default | never | **Complete, verified; 12 jobs, single request by policy** |
| **Himalayas** | yes | **yes**, opt-in, off by default | never | **Complete, verified; cursor paging** |
| **Jobicy** | yes | **yes**, opt-in, off by default | never | **Complete, verified; cursor paging** |
| LinkedIn | yes | no | never | Import only, by policy |
| Indeed | yes | no | never | Import only, by policy |
| Naukri | yes | no | never | Import only, terms unverifiable |
| Wellfound | yes | no | never | Import only, by policy |
| Instahyre | yes | no | never | Import only, by policy |
| Cutshort | yes | no | never | Import only, by policy |
| Hirist | yes | no | never | Import only, by policy |
| Workday | yes | no | never | Import only, deliberately |
| Company career page | yes | no | never | Import only, generic bucket |

## The five per-company ATS boards

Greenhouse, Lever, Workable, Ashby and SmartRecruiters each publish an unauthenticated
endpoint whose documented purpose is to serve one company's own job board. It is the same
endpoint the company's careers page calls. No credentials, no session, no anti-bot measure,
nothing circumvented — reading it is its intended use.

Discovery is **opt-in per company**. Nothing is fetched until you name board identifiers,
because shipping a built-in company list would turn a targeted lookup into a crawl.

```bash
JA_GREENHOUSE_BOARDS=dropbox,stripe       # the slug in boards.greenhouse.io/<slug>
JA_LEVER_BOARDS=spotify                   # the slug in jobs.lever.co/<slug>
JA_WORKABLE_BOARDS=yourcompany            # the subdomain in <sub>.workable.com
JA_ASHBY_BOARDS=ramp,linear               # the slug in jobs.ashbyhq.com/<slug>
JA_SMARTRECRUITERS_BOARDS=BoschGroup      # the identifier in careers.smartrecruiters.com/<id>
JA_SMARTRECRUITERS_DETAIL_LIMIT=60        # how many descriptions to fetch per run
JA_ATS_DISCOVERY_ENABLED=true             # default; set false to switch all five off
JA_ATS_MAX_PAGES=20                       # page cap per board
```

Then press **Run discovery now** on the Job discovery page, or:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/discover \
  -H 'Content-Type: application/json' -d '{"sources":["greenhouse","lever"]}'
```

| | Endpoint | Posting date | Verified |
|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | `first_published` — a real posting date | Yes: a live board returned 19 postings, 14 new and 5 cross-platform duplicates correctly merged |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | `createdAt` — creation time, accurate on most boards | Yes: a live board returned 89 postings |
| Workable | `apply.workable.com/api/v1/widget/accounts/{sub}?details=true` | `published_on` | Yes: 28 postings across three live boards, 0 skipped |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` | `publishedAt` — ISO 8601 with offset, present on every posting observed | Yes: 8 live boards. Largest returned 812 postings; `linear` 32, `Hex` 36, `ashby` 68, `Ramp` 168, `cursor` 123, `Vanta` 79, `sardine` 46. `Deel` is a valid board that returned 0, which is reported as zero rather than as an error |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=N` | `releasedDate` | Yes: `BoschGroup` reported `totalFound` 5,018, of which 585 were in India. Offset paging confirmed across two pages |

Two mapping defects were found by calling these endpoints rather than reading their docs:

- **Workable** does not nest location in an object. It exposes flat `city`, `state` and
  `country` keys. Reading a `location` dict — which is what Greenhouse does — produced an
  empty location for every Workable job, silently zeroing location scoring.
- **SmartRecruiters** returns an ISO-2 country *code* in `location.country`, so building the
  place string from `city` + `country` produced `"bangalore, in"`, which matches no
  human-entered location preference. `location.fullLocation` carries the country name and is
  used instead, with the blank segment it emits (`"bangalore, , India"`) dropped.

SmartRecruiters also carries no job description in its postings list; the description lives
on a per-posting endpoint. Each one therefore costs an extra request, so the number fetched
per run is capped by `JA_SMARTRECRUITERS_DETAIL_LIMIT`. Postings beyond the cap are still
imported, with an empty description, and score as sparse rather than as a false match.

### Limitations that apply to all five

- No free-text search. The board API returns a company's whole board, and filtering happens
  locally after import. Scoring and hard filters then do the ranking.
- No directory. You must know the company's board slug; there is no way to ask "who is
  hiring Python developers".
- A wrong slug returns HTTP 404, which is reported against that board and never retried,
  because retrying cannot fix a typo. Transient failures (429, 5xx, timeouts) are retried
  with exponential backoff up to `JA_ATS_MAX_ATTEMPTS`, then reported.

## The five open job feeds

These differ from the ATS boards in kind, not just in degree: each publisher exposes **one
whole-feed endpoint** rather than a board belonging to a single employer, so there is no
board identifier and the entire feed is in scope on every call. That makes each publisher's
own terms the governing constraint rather than "this is the company's own board".

Because of that, **every feed is off by default** and needs two switches:

```bash
JA_FEED_DISCOVERY_ENABLED=true     # master switch, off by default
JA_ARBEITNOW_ENABLED=true          # plus the per-source switch
JA_REMOTEOK_ENABLED=true
JA_REMOTIVE_ENABLED=true
JA_HIMALAYAS_ENABLED=true
JA_JOBICY_ENABLED=true
JA_FEED_MAX_PAGES=3                # page cap per run
```

| Feed | Endpoint | Paging | Verified result | Publisher's own notice |
|---|---|---|---|---|
| Arbeitnow | `arbeitnow.com/api/job-board-api` | `?page=`, followed via `links.next`, capped at 10 pages | 600 jobs over 2 pages; 583 had a location | "This is a free public API for jobs, please do not abuse. I would appreciate linking back to the site." |
| Remote OK | `remoteok.com/api` | none; single request | 99 jobs from a 100-element array — the first element is a terms object, not a job | Requires linking back to the listing URL and crediting Remote OK |
| Remotive | `remotive.com/api/remote-jobs` | **deliberately none** | 12 jobs — the public feed is small | Grants access so developers can share its jobs further, requires a link back, and advises no more than about four requests a day. This adapter therefore makes exactly one request per run |
| Himalayas | `himalayas.app/jobs/api?limit=20&cursor=` | cursor, the documented method; capped at 10 pages | 40 jobs over 2 pages; `totalCount` 127,889 | Documents cursor paging as preferred and deprecates offset |
| Jobicy | `jobicy.com/api/v2/remote-jobs?count=50&cursor=` | cursor, stops on `hasMore: false`; capped at 10 pages | 100 jobs over 2 pages | Asks that Jobicy be credited with a direct link and that every apply button redirect to the original job URL |

Three consequences worth stating plainly:

- **Attribution is satisfied structurally, not by promise.** Several notices require linking
  back to the original listing. This application stores the publisher's own URL and the only
  apply path it offers is opening that URL, so a listing is never re-hosted or re-published.
  Anyone reusing this code to *republish* listings would need to read each licence first.
- **These are aggregators, so duplication is expected** against the ATS boards. The existing
  fingerprint deduplication merges them into one job with several source references, which
  makes the import counters look odd before it does.
- **They are remote- and EU-weighted.** For on-site Indian roles they add far less than
  SmartRecruiters does, which returned 585 Indian postings from one employer.

## Why the other eleven are import-only

| Source | Basis |
|---|---|
| LinkedIn | User Agreement s.8.2 prohibits scrapers, bots and automated access. No jobseeker job-search API exists. |
| Indeed | No jobseeker search API. Terms state that "use of any automation, scripting, or bots to automate the Indeed Apply process ... is prohibited". |
| Naukri | The Terms & Conditions page could not be retrieved programmatically, so **no clause was verified**. Rather than assume a permission, the adapter applies the most restrictive setting and says so. |
| Wellfound | Terms prohibit harvesting and automated access. No public jobseeker search API. |
| Instahyre | No jobseeker search API; listings sit behind a candidate login and terms reserve the service for personal manual use. |
| Cutshort | No public jobseeker search API; job pages require an authenticated candidate session, which this project never automates. |
| Hirist | No jobseeker search API; terms restrict the site to personal non-automated use. |
| Workday | **A feed is technically reachable** at `/wday/cxs/{tenant}/{site}/jobs` on every tenant. It is deliberately unused: that path is an internal interface for Workday's own front end, not a published integration, and Workday's documented recruiting APIs need tenant credentials issued by the employer. This is exactly the "technically possible, not authorized" case the project refuses. |
| Company career page | A generic bucket for a role found on an employer's own site. There is no single operator to get permission from. If the employer runs Greenhouse, Lever or Workable, use that adapter instead and the listing arrives through a published interface. |

Every import-only adapter raises `CapabilityNotAvailable` with its policy reason rather
than returning an empty list and pretending it searched. The reason is shown verbatim on
the Logs and diagnostics page.

### What would be needed to enable one

Enabling discovery for any of the above requires a maintainer to:

1. Read the platform's current terms and find a clause that permits the access.
2. Record the clause and its URL in [COMPLIANCE.md](COMPLIANCE.md).
3. Change the declared capability in that adapter module.

Configuration alone cannot do it, and `tests/test_compliance.py` asserts that the set of
discovery-enabled sources is exactly the eleven intended ones.

## Deliberately not implemented

| Candidate | Why not |
|---|---|
| Google Cloud Talent Solution | Employer-side. A jobseeker cannot search a corpus they do not own. |
| Adzuna, Careerjet, Jooble | Each has a documented developer API with India coverage, but all require a registered key whose terms target publishers and affiliates rather than individual jobseekers. |
| Greenhouse / Lever / SmartRecruiters **submission** endpoints | Documented, but authenticated with a key issued to the **employer** for its own integrations. A candidate holds no credential that authorizes posting through them, so no submission automation exists anywhere in this project. |

## What is not here, and will not be

No browser automation against a job platform, no credential storage, no session-cookie
capture, no CAPTCHA handling, and no code path that submits an application. Playwright is
used only to test this app's own dashboard; it is a dev dependency and no adapter imports
it. A CI job fails the build if a scraping dependency appears in the manifests.
