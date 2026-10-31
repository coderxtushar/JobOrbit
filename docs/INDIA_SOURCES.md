# India-relevant job sources

Everything in this file is a **measured** result from a real discovery run, not a plan. The
run that produced it:

```bash
JA_GREENHOUSE_BOARDS=druva,groww \
JA_LEVER_BOARDS=hevodata,meesho,cred \
JA_ASHBY_BOARDS=tekion,sarvam,atlan,composio,spotdraft \
JA_SMARTRECRUITERS_BOARDS=BoschGroup \
  # then press "Run discovery now" on the Job discovery page
```

Measured 31 October 2026: **2,341 postings fetched, 2,215 stored, 126 duplicates, 0 errors.**

No company list ships in application code. A bundled directory would turn a per-company
board lookup into a crawl across companies that never agreed to it, which is the whole
distinction the capability model rests on. The slugs below are published on each company's
own careers page; you choose which to enable.

## Verified boards

| Provider | Board slug | Postings fetched | India-located |
|---|---|---|---|
| Greenhouse | `druva` · `groww` | 36 | yes |
| Lever | `hevodata` · `meesho` · `cred` | 116 | yes |
| Ashby | `tekion` · `sarvam` · `atlan` · `composio` · `spotdraft` | 189 | yes |
| SmartRecruiters | `BoschGroup` | 2,000 (capped per run) | yes, 585 of 5,018 on the board |

SmartRecruiters is capped by `JA_SMARTRECRUITERS_DETAIL_LIMIT` because each posting needs a
second request for its description. Raising the cap raises the request count against
somebody else's API in direct proportion.

## What the normalization fixes changed

Measured on the same 2,215 stored jobs, before and after — comparable denominators:

| | Before | After |
|---|---|---|
| Recognised as India-located | 333 | **467** (+134) |
| Carrying an assessable entry-level bar | 110 | **577** (+467) |
| Remote roles identified as fenced to another region | 0 | **876** |

The second row matters most. Those listings previously had **unassessable** experience, and
an unassessable category has its weight redistributed across the others — which is how a
senior role can escape its seniority penalty entirely. The phrases that parsed to nothing
were `new grad`, `new graduate`, `recent graduate`, `university graduate`, `campus hire`,
`campus placement`, `apprenticeship` and `Graduate Engineer Trainee`.

Separately, `less than 1 year` returned a **one-year floor** — the opposite of what the
listing says, and on its own enough to filter the job out for a fresher.

## Remote-in-India versus global remote

**876 of 2,215 remote listings are fenced to another country**: `Remote, Poland`,
`Remote (US only)`, `Remote - EMEA`, `Remote, United Kingdom`. Treating all remote roles
alike credited a candidate's "Remote" preference for roles they cannot legally hold.

`remote_scope()` classifies each listing as:

| Result | Meaning |
|---|---|
| `india` | The location names an Indian place, or the text requires eligibility to work in India |
| `elsewhere` | A fence is stated and it is not India |
| `unstated` | No fence is written — **never** read as a restriction, because most employers simply omit it |

Acting on `elsewhere` is **opt-in**, via *I can only work from India* on the Resume and
profile page. It is off by default on purpose: this project's rule is that a hard filter
needs positive evidence of ineligibility, and an unstated work authorization is not
evidence. Switching it on excluded 12 further listings from the measured run, none of them
in the review band.

## The honest ceiling

Adding boards helps and cannot solve the problem. Of the India-located software roles
across every board above, **very few are entry-level**. Indian fresher hiring runs through
Naukri, Instahyre, Cutshort, Hirist and campus channels — every one of which prohibits
automated access, which is why they are import-only here (see
[SOURCES.md](SOURCES.md) and [COMPLIANCE.md](COMPLIANCE.md)).

More slugs will keep returning senior India roles. **File import and saved-job URL import
remain the primary route for fresher listings**, and no amount of ranking work changes
that. Treat this as a source-coverage limitation, not a matching defect.

## Per-source tracking

Every discovery attempt writes an `import_run` row before it runs, so a source that fails
is visible rather than silently absent. The Logs and diagnostics page reads these back and
shows, per source: last attempt, status, records received, jobs created, duplicates
detected, invalid rows, and the error and warning lists.

Warnings are reported separately from errors. An employer omitting a skills list produces a
warning, not a failure — previously the two were concatenated and a clean import of 68
Ashby jobs reported "10 errors".
