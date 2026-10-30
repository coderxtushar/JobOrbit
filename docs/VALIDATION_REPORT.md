# Validation report — job-search quality

Candidate: Tushar Gautam, B.Tech CSE (Invertis University, 2022–2026), ~0.4 years
professional experience (Ethara AI, May 2026 – present).

Nothing was pushed to git. No submission automation exists or was added.

This file covers two rounds of work on 2026-10-29. **Round 2** below is the later one:
Ashby and SmartRecruiters integration, five open job feeds, and the ranking-quality rules.
**Round 1** follows it unchanged, because its findings about the resume parser and the
original scoring-honesty defects remain the record of how those were fixed.

---

# Round 2 — discovery expansion and ranking quality

## R2.1 Test results (actual)

| Gate | Command | Result |
|---|---|---|
| Tests | `.venv/bin/python -m pytest` | **484 passed in 40.33s** (was 403; +81) |
| Lint | `.venv/bin/ruff check app ui tests` | All checks passed |
| Format | `.venv/bin/ruff format --check app ui tests` | 110 files already formatted |
| Types | `.venv/bin/mypy app` | no issues in 74 source files |
| Static security | `.venv/bin/bandit -r app ui -ll` | No issues identified — 0 medium, 0 high |
| Migrations | `.venv/bin/alembic check` | no drift; 4 revisions, single head `890e1d834c56` |

New test modules: `tests/test_discovery_sources.py` (26), `tests/test_ranking_rules.py`
(38), `tests/test_matching_benchmark.py` (16), plus one API regression for the
warnings/errors separation. No test needs network, credentials or an LLM key.

## R2.2 Ashby — verified against eight live boards

Implemented as a subclass of the existing `AtsBoardAdapter`, so it reuses the same fetch
loop, bounded retries, normalization, deduplication and capability enforcement. Its basis
is identical to Greenhouse and Lever: an unauthenticated per-company posting API.

Measured by calling it, not by reading docs:

| Board | Postings |
|---|---|
| `openai` | 812 |
| `Ramp` | 168 |
| `cursor` | 123 |
| `Vanta` | 79 |
| `ashby` | 68 |
| `sardine` | 46 |
| `Hex` | 36 |
| `linear` | 32 |
| `Deel` | 0 — a valid board that is simply empty, reported as zero rather than as an error |
| `Rippling`, `Scale-AI` | HTTP 404 — reported against that board and never retried |

Field facts established from the real payloads: `apiVersion: 1`, no paging (the whole board
arrives in one response), `publishedAt` present on **all 136 postings** across three boards
checked for completeness, `location` is a flat string with extra sites in
`secondaryLocations`, and `employmentType` uses `FullTime` / `Intern` / `Contract` /
`Temporary`. Only `Intern` fails to match the normalizer's employment vocabulary, so the
adapter maps it to `internship`; verified live on `Ramp`, which returned 5 interns.

Postings flagged `isListed: false` are skipped — the company has not published them.

## R2.3 Discovery expansion — all six candidates evaluated individually

Every one was called and its response shape observed. All six were implementable, and all
six were implemented, because each has a documented public interface and a verified schema.

| Candidate | Verdict | Evidence |
|---|---|---|
| **SmartRecruiters** | Implemented | `BoschGroup` reported `totalFound` **5,018**, of which **585 were in India**. Offset paging confirmed across two pages. Eight other company ids returned `totalFound: 0`, which is why the first attempt looked unusable |
| **Arbeitnow** | Implemented | **600 jobs over 2 pages**, 583 with a location. Paging is documented via `?page=` and followed through `links.next` |
| **Remote OK** | Implemented | **99 jobs** from a 100-element array; element 0 is a terms object, not a job |
| **Himalayas** | Implemented | Cursor paging confirmed (page 2 returned different jobs); `totalCount` 127,889, but a page returns at most 20 regardless of `limit` |
| **Jobicy** | Implemented | Cursor paging confirmed; stops correctly on `hasMore: false` |
| **Remotive** | Implemented, single-request | Public feed returned only **12 jobs**. Its notice advises about four requests a day, so this adapter never paginates |

Observability, bounds and honesty, all exercised by tests:

- Timeout and bounded retries are shared with the ATS path through one `fetch_json`
  helper, so the two cannot drift. A 503 retries 3 times with 1s then 2s backoff and then
  reports; a 404 is never retried.
- Page budgets: `JA_ATS_MAX_PAGES` for boards, `JA_FEED_MAX_PAGES` for feeds, and a
  per-adapter `max_pages` ceiling that is `1` for Remotive and Remote OK.
- Every discovery result carries `pages_read`/`pages_per_board` and `jobs_per_board`.
- **Every feed is off by default** and needs both `JA_FEED_DISCOVERY_ENABLED` and its own
  switch. Verified: each adapter raises `CapabilityNotAvailable` with the policy reason
  when either switch is off, and makes no HTTP request.
- 22 sources registered, 11 with discovery, 11 import-only, **0 with submission**.

## R2.4 Two mapping defects found by calling the endpoints

- **SmartRecruiters location was wrong.** `location.country` is an ISO-2 code, so building
  the place string from `city` + `country` produced `"bangalore, in"` — which matches no
  human-entered location preference and silently zeroed location scoring for every Indian
  listing. `fullLocation` carries the country name; it is now preferred, with the blank
  segment it emits (`"bangalore, , India"`) dropped because an empty segment breaks the
  comma-splitting that location normalization relies on. After the fix, live output reads
  `bangalore, India` and `Timișoara, TM, Romania`.
- **Workable's field mapping is no longer unverified.** Round 1 could not find a populated
  board. Three were found this round, and the adapter now parses **28 postings across three
  live boards with 0 skipped**.

## R2.5 Ranking quality — measured on real listings

A benchmark of **58 real listings** was built from the Ashby, SmartRecruiters and Remote OK
APIs and labelled by reading each one, including its stated years of experience:
`tests/fixtures/eval_jobs_real.json` (version 5, provenance recorded per row).

Four defects were measured on it and fixed. Each fix states its reason in the explanation
that the user sees.

**1. Incidental keyword mentions earned full credit.** A listing that publishes no
requirements list has its skills inferred from the description. Before this change every
mention counted equally, so a sales role scored **50/100 on skills** because Python and SQL
were named as tools its customers use. Skills are now credited by *where* the description
puts them — under a requirements heading, under a nice-to-have heading, or merely in
passing — at 1.0 / 0.5 / 0.2 weight. When every match is incidental the category is capped
at 35 and says so.

**2. Role-family mismatches scored as partial title matches.** "AI Agent Support
Specialist" scored **66.8**, above the candidate's own 65 threshold, because its title
contains "AI Agent" — one of her own skills. Title fit is now capped at 12 when the role
belongs to a discipline none of her target titles describe (support, sales, finance,
hardware, recruiting and others). Software-adjacent specialisations are deliberately absent
from that list, and a test asserts 11 of them are untouched.

**3. Experience bars written in prose were invisible.** Seven listings asking five to seven
years carried no structured experience field, so the bar existed only in the description
and was never read. Four of them occupied the **high band, ranked 1st to 4th, above every
genuinely suitable listing**. The description-stated bar is now read and enforced by the
same hard filter that already handled structured fields, using the project's existing
2-year tolerance. An explicit "freshers welcome" overrides a years figure, because that
figure is usually boilerplate.

**4. Relevance and confidence were conflated.** A score is now reported along
`evidence_coverage` and a `confidence` label of high/medium/low with stated reasons, both
persisted on `job_match`. The score itself is never adjusted — it stays auditable — but a
high band requires high confidence. Verified live on 216 real jobs: a Remote OK teaser
scored 99.6 and was correctly reported as `low` confidence in the `review` band, never as a
confident match.

### Measured before and after

| Metric | Before | After |
|---|---|---|
| False-positive rate above the candidate's own 65 threshold | 0.0303 | **0.0** |
| Unsuitable or over-bar rows in the high band | **4** | **0** |
| precision@10 | 0.60 | 0.60 |
| precision@20 | 0.35 | 0.3684 |
| relevant recall | 0.8571 | 0.8571 |

Per-row, directly comparable:

| Listing | Before | After |
|---|---|---|
| Software Engineer - Backend @ sardine (India, states 7+ years) | 85.7, high, ranked 1st | filtered, reason quotes the 7 years |
| Software Engineer, AI Product @ Vanta (states 7 years) | 83.2, high, ranked 2nd | filtered, years quoted |
| Software Engineer, Integrations Platform @ Vanta (states 6+ years) | 82.1, high, ranked 3rd | filtered, years quoted |
| Software Engineer, Developer Velocity @ Hex (states 5+ years) | 82.0, high, ranked 4th | filtered, years quoted |
| AI Agent Support Specialist @ Vanta | 66.8, above threshold | below threshold |

**The precision figures need a caveat, and it is not a flattering one.** Applying the prose
experience bar revealed that seven rows I had labelled `adjacent` should be excluded by the
project's own 2-year tolerance, so dataset versions 4 and 5 relabelled them
`over_experience_bar`. The precision denominators therefore differ between the two runs and
those two numbers should not be subtracted from each other. The false-positive rate and the
per-row table above are directly comparable. `tests/fixtures/eval_baseline.json` records
both sets with this caveat and gates the build against the current values.

`precision@20` is at its ceiling for this dataset: with 7 `relevant` rows, every one of
them ranks inside the top 20 judged rows. `precision@10` cannot exceed 0.70 for the same
reason, and the one relevant row that misses the top 10 is a Spanish-language listing, which
yields few English skill matches.

## R2.6 A reporting defect found by using the API

A clean import of 68 real Ashby jobs reported **10 "errors"**. Normalization *warnings* —
"no skill list was supplied; skills shown were inferred from the description" — were being
concatenated into the import summary's `errors` list, because there was nowhere else to put
them. An employer choosing not to publish a skills list is not a failure. `ImportSummary`
now carries `warnings` separately, the Job discovery page shows errors and notes in separate
expanders, and a re-run reports `errors=0, warnings=10`.

## R2.7 End-to-end, driven live

216 real jobs discovered over HTTP from Ashby (68), SmartRecruiters (100) and Jobicy (50),
with 2 cross-platform duplicates merged. Re-running discovery created 0 new jobs and
reported every record as a duplicate, confirming idempotency. All 216 were scored with 0
failures: **0 high, 9 review, 207 low, 200 filtered with stated reasons**, and every row
carried a confidence label and coverage figure in the API response.

## R2.8 Limitations and residual risks

- **One adversarial row sits exactly at the threshold on live data.** "Security Test
  Engineer" at Bosch scored 65.0, equal to the candidate's own cut-off. It is reported at
  `low` confidence with 60% coverage and in the `review` band, not `high`. I did not add
  "test" or "validation" to the role-family list to push it down, because QA and validation
  engineering are legitimate software-adjacent roles for other candidates and tuning the
  list to one live row would be over-fitting.
- **The role-family list is not exhaustive.** "Partner Solutions Engineer" names no marker
  it knows about and is caught by the weaker generic-token cap at 25 instead of 12. A test
  documents that the generic cap is the intended backstop.
- **The benchmark is 58 rows from three APIs**, weighted towards US and EU remote roles
  because that is what those boards publish. It has 7 `relevant` rows, which bounds how
  finely precision can be measured.
- **Aggregator duplication is untested at scale.** The feeds will overlap heavily with the
  ATS boards; dedup handles it by fingerprint, but no run large enough to characterise the
  overlap rate has been done.
- **Remotive's terms are the most restrictive** of the five feeds and gate bulk programmatic
  use behind a paid tier. The adapter makes one request per run, which respects the stated
  guidance, but anyone increasing that should read the terms again.
- Still unverified by me: live IMAP ingestion, real LLM output, a screen-reader pass, and
  Windows/Linux.

---

# Round 1 — resume parsing and scoring honesty

## 1. Test results (actual)

| Gate | Command | Result |
|---|---|---|
| Tests | `.venv/bin/python -m pytest` | **403 passed in 23.20s** (was 367; +36) |
| Lint | `.venv/bin/ruff check app ui tests` | clean |
| Format | `.venv/bin/ruff format --check` | clean |
| Types | `.venv/bin/mypy app` | no issues in 71 files |
| Static security | `.venv/bin/bandit -r app ui -ll` | No issues identified |
| Migrations | `.venv/bin/alembic check` | no drift |

New test modules: `tests/test_matching_eval.py` (16), `tests/test_truthfulness.py` (11),
plus 6 parser regressions and 2 ATS mapping tests. New fixture:
`tests/fixtures/eval_jobs.json` (32 labelled listings).

## 2. Profile configured from the resume — and only from it

Extracted and accepted: name, email, phone, **4 links**, 39 skills, B.Tech / Invertis
University / 2022–2026, graduation 2026, 2 projects (BrandBot AI Agent, Snap UI),
experience **0.4 years** computed from the stated May 2026 – present.

**Deliberately left blank**, because the resume does not state them and guessing them is
the one thing this tool must never do:

| Field | Status |
|---|---|
| `work_authorization` | blank → flagged on every application |
| `requires_sponsorship` | blank → flagged |
| `salary_expectation` | blank → flagged |
| `notice_period_days` | blank → flagged |
| `open_to_relocation` | blank → flagged |

Verified live: those five appear as `needs_user_input` on all 14 prepared applications
(70 answer slots), while `education`, `graduation_date` and `years_experience` are
`profile_verified` because the resume does supply them.

Target roles and locations were taken from your own brief (the five role families; Remote +
Gurgaon/Delhi NCR/Noida/Bengaluru). **Confirm or change the locations** — Gurgaon is where
the resume says you are, not necessarily where you want to work.

## 3. Resume parser — six real defects found and fixed

Your resume is LaTeX-typeset, which broke the parser in ways no synthetic fixture had:

| Defect | Effect | Status |
|---|---|---|
| Hyphenated line breaks not rejoined | `Work-\nflows` became the skills `terminal-based work` + `flows`; `Tra-\njectory` likewise. Four garbage skills that can never match a requirement. | fixed |
| PDF hyperlinks ignored | All 4 URLs (portfolio, LinkedIn, GitHub, LeetCode) live in link *annotations*, not text. A fresher's strongest evidence was being dropped. | fixed |
| Education year on a separate line | `Aug 2022 - Jun 2026` sits below the degree line, so `graduation_date` was `None` and that question blocked **every** application needlessly. | fixed |
| Every project bullet became a project | 7 "projects" with names like `brand analysis, trend research and content creation.` — which would have gone into cover letters verbatim. | fixed |
| Comma-separated stacks not detected | `Python, FastAPI` never matched because the test required surrounding spaces. | fixed |
| Experience was year-granular | May→Oct 2026 reported as 0.1 years instead of 0.4. | fixed |

One regression I introduced and then caught: appending link URLs to the text put them
inside the skills section (it is the last block on the page), producing skills named
`github.com`, `in` and `u`. Links are now threaded separately. Regression test included.

Net: 41 skills (4 corrupted) → **39 clean skills**, 4 links, correct graduation year,
2 correctly-named projects, 0 parse warnings.

## 4. Match quality — measured, not asserted

`tests/fixtures/eval_jobs.json` holds 32 labelled listings: 12 relevant, 9 irrelevant,
5 **adversarial** (share surface tokens but are unsuitable), 6 edge cases. Observed:

| Metric | Before | After |
|---|---|---|
| Relevant mean score | 90.1 | 89.7 |
| Unsuitable mean score | 39.6 | **38.3** |
| Separation | 50.5 | **51.4** |
| Relevant reaching high band | 11/12 | 11/12 |
| Unsuitable in high band | 0/14 | **0/14** |
| Unsuitable above your own 65 threshold | **2** | **0** |

The 12th relevant job is the internship at 73.6 ("worth a look"), which is honest — it is a
6-month internship, not a full-time role.

## 5. Why unsuitable jobs ranked highly — two root causes, both fixed

**Cause 1: a single generic word earned real title credit.** "Technical Support Engineer –
Tier 1" shares exactly one word with "Software Engineer" — *engineer* — and that scored
**41/100** on title fit, worth 10 points at the 25% weight. Total 67.4, which is **above
your minimum_match_score of 65**, so a bulk run would have prepared an application for a
night-shift helpdesk role.

Fix: an overlap consisting only of generic role nouns (engineer, developer, analyst,
senior, associate, tier…) is capped at 25 and *says so*: *"shares only the generic word
'engineer' with 'Software Engineer', which says nothing about what the role does"*.
Technical Support → 63.4 (below threshold, `low` band). Mechanical Design Engineer →
37.9. Real matches are untouched — Agentic AI Engineer, Cloud Engineer and DevOps Engineer
all still score ≥70 on title, asserted by test.

**Cause 2: an empty listing ranked second in the feed.** "Software Engineer @ Terse
Listings Inc" — whose entire description is *"We are hiring a software engineer. Apply
now."* — scored **99.3** and sat at position 2, above eleven fully-assessed matches. With
skills, experience, and location all unassessable, the redistributed weight landed almost
entirely on the title, which matched perfectly.

The number is defensible and the band already said "worth a look", but **the feed sorts by
score**, so the user saw garbage first. Fix: order by band, then score — the audited number
is untouched, and that listing now falls out of the top 14 entirely. Verified through the
live API, not just in tests.

A third, smaller fix: Workable and LinkedIn publish seniority *labels* instead of year
ranges, so `Director` and `Mid-Senior level` made experience **unassessable** — and an
unassessable category redistributes its weight, meaning a director-level posting received
no seniority penalty at all. Those labels now map to year bounds.

## 6. Tailoring and artifacts — audited on 14 real applications

- **Variant selection is job-family correct**: Backend variant for backend roles, GenAI for
  the three AI roles, Frontend for React, Cloud/DevOps for DevOps. Asserted by test.
- **0 fabricated claims** across all 14 cover letters, scanned for experience durations,
  salary, visa/authorization, notice period, certifications and academic scores.
- **Every letter names its own job and company**; 0 mismatches, and no letter names another
  application's employer.
- **0 duplicate cover letters** — each is unique to its employer.
- **Artifacts correspond correctly.** Resume variants are shared *within* a family (one
  backend variant across 5 backend jobs), which is legitimate reuse, but each application
  keeps its **own** content-addressed snapshot row, so what each employer received stays
  reproducible after a variant is regenerated.

## 7. Answer-bank provenance — cannot be laundered

| Check | Result |
|---|---|
| `ai_draft` can enter the bank | **No** — `UnbankableAnswerError` *and* a database `CHECK` |
| `needs_user_input` or `resume_extracted` can enter | **No** — only `user_entered` / `profile_verified` |
| Reuse promotes provenance | **No** — stays `user_entered`, with `source_field=answer_bank:<key>` |
| Editing an answer marks it verified | **No** — becomes `user_entered` |
| Sensitive answers pre-filled | **No** — all 5 legal/financial fields blank and flagged |
| `ai_draft` answers stored live | **0** |

The database constraint was tested by inserting an `ai_draft` row directly, bypassing the
service layer: it raises `IntegrityError`.

## 8. Workable — now verified, and the verification found a bug

Previously "endpoint reachable, field mapping unverified". I found real boards with live
postings (`trailofbits`, `ottimate`, `huggingface`) and the mapping was **wrong**: it
expected a nested `location` object, which is *Greenhouse's* shape. Workable uses flat
`city`/`state`/`country` plus a `locations` array, so **every Workable job had been stored
with an empty location**, silently zeroing location scoring and weakening dedup.

Now: **28 jobs parsed across 3 live boards, 0 skipped**, with real locations
("Paris, Île-de-France, France"), posting dates, employment types, seniority and education.
Two extras from the live data: Workable sends the literal string `"None"` for education
(now filtered) and seniority labels instead of years (now mapped). Test fixture replaced
with the verified payload.

## 9. Additional integrations investigated — 7 more verified reachable

Full detail in [INTEGRATION_OPTIONS.md](INTEGRATION_OPTIONS.md). Called every endpoint:
**Ashby** (68 jobs, unauthenticated, same per-company model as Greenhouse/Lever),
**SmartRecruiters** (HTTP 200), **Arbeitnow** (300), **RemoteOK** (100), Remotive,
Himalayas, Jobicy.

**On submission, the honest finding:** there is **no documented candidate-initiated
application-submission API** on any platform in scope. Greenhouse and Lever do publish
submission endpoints, but they authenticate with a key **issued to the employer** for the
employer's own integrations — a jobseeker holds no credential authorizing their use. So no
submission automation was added, and none is claimed.

## 10. Limitations and what still needs you

**Needs your input before the app is fully useful:**
1. The five blank legal/financial fields (work authorization, sponsorship, salary, notice
   period, relocation). Answer each **once** in the Action inbox and it fills everywhere.
2. Confirm the preferred locations — I used your resume's city plus Remote.

**Known limitations, unchanged:**
- Matching is rule-based over a skill-alias table; no semantic embedding. A genuinely novel
  skill name must be added to the profile explicitly.
- The evaluation dataset is 32 hand-labelled listings written by me. It captures the failure
  modes I could think of, not the full distribution of real postings.
- Email alert parsing is verified offline only; no live mailbox was tested.
- Greenhouse/Lever/Workable return a company's *whole* board with no search, so volume
  depends on which companies you configure.
- No OCR; a scanned resume still yields nothing.

## Next three highest-value improvements

**1. Implement the Ashby adapter.** Verified reachable with 68 live postings, identical
compliance basis and base class as the three already supported, so it is roughly one small
class plus a mapping test. Many AI-native startups — the segment that best matches this
resume — run Ashby. Highest value per unit of work available.

**2. Weight skill matches by whether the skill is central to the role.** The remaining
false-positive pressure comes from incidental tool mentions: the helpdesk role listed Linux
and Docker and earned 50/100 on skills. Scoring a requirement by its prominence in the
description (title and requirements section over a passing mention) would separate "uses
Docker" from "is a Docker role" and would have caught that case on skills rather than
needing the title rule.

**3. Expand the evaluation dataset with real listings from your own runs.** The current 32
rows are synthetic. Labelling 100 real Greenhouse/Lever/Workable postings as
relevant/irrelevant would turn these quality numbers from "passes my hand-written cases"
into a genuine benchmark, and would almost certainly surface failure modes I did not think
to write.
