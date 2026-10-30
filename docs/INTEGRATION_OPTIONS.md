# Additional authorized discovery options

Investigated 2026-10-29. Every endpoint below was **called** and the response shape
observed; the "jobs returned" column is what came back, not what the documentation
promises. Nothing here requires scraping, a stealth browser, or bypassing an access
control.

**Status: all seven candidates below have since been implemented and verified.** See
[SOURCES.md](SOURCES.md) for each one's endpoint, paging method, publisher notice and
measured result, and [VALIDATION_REPORT.md](VALIDATION_REPORT.md) section R2.3 for the
per-candidate evidence. This file is kept as the record of the original investigation,
including the two first impressions that turned out to be wrong:

- **SmartRecruiters looked unusable.** Eight company identifiers returned
  `totalFound: 0`, which read like an empty API. `BoschGroup` returned **5,018** postings,
  **585 of them in India** — making it the single best source in this set for this
  candidate, not the weakest.
- **Ashby's 68 postings were not its ceiling.** That was one small board. `openai` returned
  812, `Ramp` 168, `cursor` 123.

## Verified reachable

| Candidate | Endpoint | Auth | Jobs returned | Shape | India coverage |
|---|---|---|---|---|---|
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{slug}` | none | **68** | `{jobs: [...]}` | per-company; depends on the board |
| **SmartRecruiters** | `api.smartrecruiters.com/v1/companies/{id}/postings` | none | 0 for a wrong id, HTTP 200 | `{content: [...]}` | per-company |
| **Arbeitnow** | `arbeitnow.com/api/job-board-api` | none | **300** | `{data: [...]}` | mostly EU/remote |
| **RemoteOK** | `remoteok.com/api` | none | **100** | JSON array | remote-first, global |
| **Remotive** | `remotive.com/api/remote-jobs` | none | 12 (limited) | `{jobs: [...]}` | remote-first, global |
| **Himalayas** | `himalayas.app/jobs/api` | none | 3 (limited) | `{jobs: [...]}` | remote-first, global |
| **Jobicy** | `jobicy.com/api/v2/remote-jobs` | none | 3 (limited) | `{jobs: [...]}` | remote-first, global |

## Original ranked recommendation (now acted on)

**1. Ashby — implement next.** *(Done.)* It is the same shape as the three already supported: an
unauthenticated, documented, per-company job-board API. 68 live postings came back on the
first call. It slots into `AtsBoardAdapter` with only a `board_url` and `parse_board`, so
the marginal cost is one small class plus a mapping test, and the compliance basis is
identical to Greenhouse and Lever. Many AI-native startups — the segment that matches this
resume best — run Ashby.

**2. SmartRecruiters — implement after Ashby.** *(Done, and it proved the most valuable of
the set for Indian roles.)* Same per-company model, unauthenticated,
HTTP 200 against a real request. Needs a correct company identifier to be useful, and the
`content` envelope differs from the others, so it needs its own parser.

**3. Remote aggregators (Arbeitnow, RemoteOK, Remotive, Himalayas, Jobicy) — treat with
care.** *(All five implemented, each off by default behind two switches, with each
publisher's notice quoted in its adapter. The licence caution below was the reason for that
design.)* These are genuinely open APIs and would add volume immediately, but two caveats
matter more than the volume:

- They are **aggregators**, so they will produce heavy cross-platform duplication against
  Greenhouse/Lever/Workable listings. The existing fingerprint dedup handles that, but the
  import counters will look strange until it does.
- Each has its own licence on *redistribution*. Reading them for a single person's own job
  search is within their intent, but anyone reusing this code to republish listings should
  check the licence first. That distinction belongs in `COMPLIANCE.md` before enabling one.

They are also mostly remote/EU-weighted, so for Gurgaon/Bengaluru on-site roles they add
less than Ashby does — and, as it turned out, far less than SmartRecruiters does.

## Deliberately not pursued

| Candidate | Why not |
|---|---|
| **Google Cloud Talent Solution** | Employer-side. A jobseeker cannot search a corpus they do not own; the API is for a company indexing its own requisitions. |
| **Adzuna / Careerjet / Jooble** | Each has a documented developer API with India coverage, but all require a registered API key whose terms are aimed at publishers and affiliates rather than individual jobseekers. Worth revisiting only with the licence read in full. |
| **Greenhouse / Lever submission endpoints** | Documented, but authenticated with a **key issued to the employer** for the employer's own integrations. A candidate holds no credential that authorizes posting through them. |
| **Workday `/wday/cxs/`** | Reachable on every tenant, but an internal interface for Workday's own front end rather than a published integration. |
| **LinkedIn / Indeed / Naukri / Wellfound / Instahyre / Cutshort / Hirist** | No jobseeker search API; terms prohibit automated collection. Unchanged from the earlier audit. |

## On authorized submission

The honest finding, after looking specifically for it: **there is no documented,
candidate-initiated application-submission API on any platform in scope.** Every
submission endpoint found is employer-authenticated. Until that changes, the app prepares
applications and the user submits them. No part of this project claims otherwise, and the
no-submit guarantee is enforced in four independent places.
