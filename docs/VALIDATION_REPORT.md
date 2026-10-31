# Validation report — job-search quality

Candidate: Tushar Gautam, B.Tech CSE (Invertis University, 2022–2026), ~0.4 years
professional experience (Ethara AI, May 2026 – present).

Nothing was pushed to git. No submission automation exists or was added.

This file covers four rounds of work, newest first. **Round 4** measures whether adding
India-hiring ATS boards fixes the coverage gap Round 3 found. **Round 3** covers confidence
in the dashboard, cross-source duplication measured at scale, the benchmark expanded to 190
real listings, and a real application pilot. **Round 2** covers the Ashby and
SmartRecruiters integration, the five open job feeds and the ranking-quality rules.
**Round 1** follows unchanged, because its findings about the resume parser and the original
scoring-honesty defects remain the record of how those were fixed.

---

# Round 4 — India source coverage

Round 3 found the product's biggest limit: only **4 India-located listings** in a
7,791-job pool qualified as suitable, because the configured boards were almost entirely
US and EU employers. This round measured whether adding India-hiring boards fixes that.

## R4.1 What was measured

126 candidate board slugs were probed across Greenhouse, Lever, Ashby, Workable and
SmartRecruiters. **30 returned HTTP 200 and 10 carried India-located postings.** The
per-board counts are in [SOURCES.md](SOURCES.md). No slug was added to application code;
the boards are documented configuration the user opts into.

Discovery was then run against those boards in a scratch database, leaving `var/`
untouched, and scored against the real profile:

| | Value |
|---|---|
| Records received | 2,341 across four platforms |
| Jobs stored | 2,215 |
| India-located | **522** |
| Errors | 0 |
| Eligible in high/review band | **7** |
| Of which India-located | **7 of 7** |

**Before: 2 eligible listings, both outside India. After: 7, all India-located.**

## R4.2 The structural ceiling, measured rather than assumed

Adding boards helps, but it cannot solve the problem. Of the **98 India software roles**
across all ten verified boards, **3 are entry-level** — and the closest of those is a
customer-experience role, not software engineering.

The reason is structural, not a configuration mistake: entry-level hiring in India runs
through Naukri, Instahyre, Cutshort, Hirist and campus channels, and every one of those
prohibits automated access, which is why they are import-only here. Per-company ATS boards
will keep returning mostly senior India roles however many slugs are configured.

**File import therefore remains the primary route for fresher listings**, and these boards
are a supplement. That is a limit of what any compliant tool can do, and it is recorded
here rather than hidden behind a larger job count.

## R4.3 A role-family gap the India run exposed

With the India boards enabled, **3 of the 9 listings that first reached the review band
were not software roles**: "Application Engineer - Heat Pumps" (76.4), "Cost Engineering &
Benchmarking - MAE" (65.0) and, earlier, similar titles from the same employer. A large
engineering company's titles share the generic role noun, so the only signal separating
them from software work is the discipline named beside it — and `pumps`, `hvac`,
`refrigeration`, `cost` and `benchmarking` were not in the foreign-family table.

This was not a single outlier: three separate listings in one measured run, from a real
employer whose board a candidate would plausibly configure. Adding those markers dropped
the review band from 9 to **7**, with the two non-software rows correctly excluded.

`operations` itself was deliberately **not** added, because DevOps and
platform-operations roles are software work. The control is asserted: "Software
Development Engineer", "DevOps Engineer", "Site Reliability Engineer", "Platform
Engineer", "Cloud Engineer" and "IT Application Operations Engineer" all keep their title
credit.

Every benchmark metric held exactly after the change: precision@10 1.00, precision@20
1.00, false-positive rate 0.0, recall 0.4091, 0 unsuitable rows in the high band.

## R4.4 What is still true after this round

- All 7 eligible India listings come from **one employer** (Bosch Group) and all carry
  **low confidence at 0.60 coverage**, because that board publishes no requirements list.
  The ten startup boards contributed **zero** eligible listings — their India roles are
  senior.
- The five sensitive answers still block every application, by design.
- No submission automation exists.

---

# Round 3 — product readiness and the real pilot

## R3.1 Test results (actual)

| Gate | Command | Result |
|---|---|---|
| Tests | `.venv/bin/python -m pytest` | **539 passed in 41.31s** (was 484; +55) |
| Lint | `.venv/bin/ruff check app ui tests` | All checks passed |
| Format | `.venv/bin/ruff format --check app ui tests` | 113 files already formatted |
| Types | `.venv/bin/mypy app` | no issues in 75 source files |
| Static security | `.venv/bin/bandit -r app ui -ll` | 0 medium, 0 high (15,223 lines) |
| Migrations | `upgrade head` / `check` / `downgrade base` | 17 tables, mode 600, no drift, clean teardown |
| Migration heads | `.venv/bin/alembic heads` | single head `890e1d834c56` |
| Submission routes | grep of the OpenAPI document | 0 routes containing "submit" |

## R3.2 Confidence surfaced in the dashboard

`total_score`, `confidence` and `evidence_coverage` were already computed, persisted on
`job_match` and returned by the API, but the dashboard showed only the score ring and the
band — so the honesty work was invisible where jobs are actually read. Each job card now
carries a confidence badge beside the ring and, in the expander, the evidence block: the
coverage percentage, the reasons for the confidence level, and the categories that could
not be assessed with the reason each one was dropped.

A deliberate choice carried over from the design system: **low confidence renders in a
neutral slate, not red**, and the word always accompanies the colour. Low confidence means
the listing published too little to judge, which is not the candidate's failure.

12 UI and API regression tests were added, including one that renders the populated
diagnostics panel and asserts the suspects are tabulated rather than merely counted.

## R3.3 Cross-source duplication, measured on 7,194 records

One run across all ten working discovery sources:

| | Value |
|---|---|
| Records received | 7,194 |
| New jobs created | 2,110 |
| Duplicates detected | 5,084 |
| Invalid rows | 0 |
| Stored jobs after merging | 7,791 |
| Sightings | 8,070 |
| Merged sightings | 279 → **duplicate rate 3.46%** |
| Exact duplicates (source id or canonical URL) | 0 |
| Fuzzy duplicates (fingerprint) | 279 |
| Jobs seen on more than one source | 10 → **cross-source rate 0.13%** |
| Overlapping source pairs | `arbeitnow+greenhouse` 8, `greenhouse+lever` 1, `greenhouse+jobicy` 1 |
| Normalization collisions | 0 |
| Jobs carrying an application | 14, of which 1 on a merged listing — none deleted |

**Cross-source duplication is far lower than expected.** The ATS boards and the open feeds
barely overlap, because the feeds carry mostly remote and EU employers that do not run the
per-company boards configured here. The headline number to watch is therefore the
*within-source* rate, not the cross-source one.

## R3.4 Four defects found by measuring duplication

**One bad posting discarded an entire company board.** Greenhouse's `databricks` board
lists one role whose location is a 300-plus character list of US states. A parse failure
was reported per board, so that single row discarded all 901 of the board's postings and
the run reported an error rather than the loss. Display fields are now clipped and an
unusable row is skipped on its own: `databricks` returns **901 postings, 0 errors** where
it previously returned **0 with an error**.

**Every CJK title collapsed to the same fingerprint.** `normalize_text` keeps only
`[a-z0-9+#.-]`, so a Chinese or Japanese title reduced to the empty string and any two
differing roles at one company and city produced an *identical* fingerprint. Verified on
two live SmartRecruiters postings — `半导体采购质量工程师` and `产品认证项目经理（智舱/智驾）` — which merged
into one job. After the fix the same two payloads create two jobs.

**Every "PhD - <topic>" posting collapsed to "phd".** `_core_title` took the text before
the first dash unconditionally, so a dozen unrelated Bosch research openings merged into
one. A dash-separated prefix is now only treated as the role when it carries at least two
meaningful words; the location-suffix stripping that the rule exists for is unchanged,
asserted by test.

**The detector was blind to both.** It tokenised titles through `dedup._core_title`, the
very function causing the merges, so two "PhD" rows scored 100% overlap and the false merge
was reported as healthy. Tokenising titles as written raised detection from **2 suspects to
25** on the same data.

The 25 remaining false merges are pre-existing rows: a merge is sticky because each sighting
re-matches by its own stored source id. None carries an application, so no historical record
is at risk, and a fresh discovery no longer produces them.

## R3.5 Benchmark expanded to 190 real listings

Rebuilt from the discovered pool with `python -m tests.build_eval_dataset`. Every row keeps
the URL it came from and the stated fact its label rests on. Hand-written listings are
excluded: a listing authored to fail a rule cannot be evidence that the rule works.

| | |
|---|---|
| Rows | **190**, across 15 real publisher hosts |
| India-located / remote / elsewhere | 67 / 32 / 91 |
| Labels | relevant 69, adversarial 25, over_experience_bar 19, senior 20, preference_mismatch 15, location_restricted 12, irrelevant 15, support 10, sparse 8 |
| Relevant rows per family | software_general 21, genai_agentic 18, backend_python 15, cloud_devops 7, frontend 5 |

| Metric | Before (v5, 58 rows) | After (v7, 190 rows) |
|---|---|---|
| precision@10 | 0.60 | **1.00** |
| precision@20 | 0.3684 | **1.00** |
| False-positive rate above the 65 threshold | 0.0 | **0.0** |
| Unsuitable rows in the high band | 0 | **0** |
| Relevant recall | 0.8571 | 0.4091 |

**Recall is not comparable across the two versions and did not regress.** Version 5 held 7
`relevant` rows; version 7 holds 69, chosen on job family, location and stated experience
bar alone — never on whether the candidate's skills match. Of the 69, none is filtered
incorrectly; those that miss the review band sit at 40–60 because skills carry 35% of the
weight and almost no listing in this pool publishes a requirements list, so skills are
inferred and capped. **That was left alone deliberately**: raising the skills score to lift
recall would be tuning against the benchmark and would cost the precision figures.

### Per family

| Family | Relevant rows | Recall | False-positive rate | Mean score of relevant rows |
|---|---|---|---|---|
| software_general | 21 | 0.6667 | undefined (no unsuitable rows) | 70.96 |
| genai_agentic | 18 | 0.3333 | 0.0 | 62.51 |
| backend_python | 15 | 0.2000 | 0.0 | 61.43 |
| cloud_devops | 7 | 0.2857 | 0.0 | 59.06 |
| frontend | 5 | 0.4000 | undefined (no unsuitable rows) | 60.52 |
| non_target | 0 | n/a | 0.0 | n/a |

Every family except `software_general` has a mean suitable score **just below the
candidate's own 65 threshold**, which is exactly why recall is low while the
false-positive rate is zero everywhere. The threshold, not the ranker, is what excludes
them.

### Confidence calibration

| Level | Rows | Judged rows | Share suitable | Mean evidence coverage |
|---|---|---|---|---|
| high | **0** | 0 | undefined | undefined |
| medium | 153 | 109 | **0.5596** | 0.898 |
| low | 37 | 27 | **0.1852** | 0.638 |

A medium-confidence row is suitable **three times as often** as a low-confidence one and
rests on more evidence (0.90 against 0.64), so the label carries real information and is
worth showing. **But no listing in 190 earns `high` confidence**, because the gate needs a
published requirements list and real employers rarely publish one. That is recorded in the
baseline and asserted by test, so a future relaxation has to be deliberate.

## R3.6 Four ranking defects found by the expanded benchmark

**A weaker structured field masked an explicit prose bar.** A Bosch listing carries
`experienceLevel: "Associate"`, which normalises to a 1-year minimum, while its text asks
for 3 years. The filter took the structured field whenever it existed, so a role three
years above the candidate stayed eligible. It now enforces the higher of the two figures
the employer gave, and a listing that welcomes freshers still overrides a boilerplate
years figure.

**A three-way title tie was resolved the worst way.** "Backend Engineer - Python" tied at
42.5 against "Software Engineer", "Backend Developer" and "Python Developer". Keeping the
first left the match resting on the generic word "engineer", so the generic cap cut it to
25/100 — for a genuine backend role. A tie now prefers a target that shares a word saying
what the role does.

**"Engineer" and "Developer" were treated as different jobs.** A profile saying "Backend
Developer" scored a listing saying "Backend Engineer" at 42/100, because the differing role
nouns stayed in the denominator. They are now collapsed. The safety claim is asserted, not
assumed: "Technical Support Engineer" and "Sales Engineer" still score ≤25 and stay below
the threshold.

**"Staff+" and "Sr." escaped the seniority filter entirely.** `normalize_text` keeps `+`
and `.` so that "c++" and "node.js" survive as skills, which left these titles as the
tokens `staff+` and `sr.` — neither matched a seniority marker. That is why "Staff+
Software Engineer, Memory & Search" and "Sr. Controls Software Engineer" appeared in the
review band on real data. Both are now filtered; `c++` and `node.js` are unaffected.

All four metrics held at or above baseline after every one of these changes.

## R3.7 "Score all jobs" never finished

The default scoring query listed `DISCOVERED`, `SCORED` and `FILTERED_OUT` — which
includes everything already scored — and took the first 2000 by discovery date with no
offset. On this 7,791-job database every press re-scored the same 2000 and **5,791 jobs
stayed permanently unscored while the response reported success.**

The incremental path now selects only jobs with no match row, the full-rescore path accepts
an offset, and both report `remaining` so the caller knows work is left. Verified live:
2000 → 2000 → 2000 → 1791 → 0, all 7,791 scored.

## R3.8 Within a band, evidence now orders before the number

Three rows whose title, company and location were each a single character scored **100.0**
from the one category that could be assessed (20% coverage, low confidence) and sat at the
**top of the review band**, above fully-assessed matches at 71–77. The band gate had
already demoted them from `high`; ordering *inside* the band was still score-only. Ordering
is now band, then confidence, then score. The score itself is never adjusted. Every
benchmark metric held exactly.

## R3.9 The real application pilot

Run against the verified profile and the real parsed resume.

**Of 7,791 scored listings, 2 genuinely-discovered rows reach the review band or better.**
Both were prepared:

| Job | Score | Band | Confidence | Coverage |
|---|---|---|---|---|
| Cloud Engineer Automation @ Smile Digital Health (Toronto) | 70.8 | review | medium | 0.95 |
| AV Engineer - Platform @ spotify (Stockholm) | 71.6 | review | low | 0.45 |

Audited on the prepared applications:

- **Resume variants differ per job family** (variant 5 and variant 4), selected by the
  existing rule.
- **Cover letters are job-specific**: 16 applications, 16 distinct letters, each naming its
  own role and company. Where the profile shares no skills with the posting the letter says
  so — *"My profile does not yet list skills overlapping this posting"* — rather than
  inventing a match.
- **Artifacts stored and hashed**: 32 artifacts, a resume variant and a cover letter per
  application, each with a SHA-256 so the exact text sent can be reproduced.
- **Answer provenance**: 128 `profile_verified`, 80 `needs_user_input`, **0 `ai_draft`**
  anywhere, and **0 AI drafts in the answer bank**.
- **Five sensitive questions block every application** and none was guessed: work
  authorization, visa sponsorship, salary expectation, notice period, relocation.
- **Duplicate application prevention works**: re-preparing a job already prepared returns
  HTTP 422 rather than creating a second application.
- **No outcome was recorded.** 16 applications, all `READY_FOR_REVIEW`; 0 `SUBMITTED` and
  0 `CONFIRMED`, because nothing was submitted and there is no evidence to record.

### A defect the pilot found in text sent to employers

A generated letter read *"...multi-agent workflow with 5+ ."* — the project description was
cut on character count alone, leaving a dangling quantifier before a full stop. Truncation
now ends at a clause boundary and drops a trailing numeric quantifier whose noun was cut.
No text is ever reworded, only whole clauses dropped, because this is resume content and
rewording it would be fabrication. `C++` is explicitly preserved.

### Two honest findings about the pilot itself

**The pool is wrong for this candidate.** Only **4 India-located rows** in the entire
7,791-job pool qualify as suitable. The configured boards — Greenhouse, Lever, Ashby,
Workable, SmartRecruiters and five remote feeds — are overwhelmingly US and EU employers.
This is the single biggest limit on the product's usefulness today, and it is a
configuration and source-coverage problem, not a ranking one.

**The live database mixes synthetic fixtures with real listings.** The earliest
hand-written evaluation rows were imported with plausible-looking `boards.greenhouse.io`
and `jobs.lever.co` URLs, and they top the feed precisely because they are the only
listings that publish explicit requirements lists. They are indistinguishable by host. The
benchmark excludes them, but the live feed does not.

## R3.10 Version control and release hygiene

Git was already initialised with one commit. The audit before staging anything found:

- **The candidate's real resume PDF was tracked**, and is in commit `428ede4`. It has been
  untracked (`git rm --cached`, the file kept on disk) and `.gitignore` now excludes
  `*resume*.pdf` and `*resume*.docx`. **The blob is still in history** — see the blockers.
- **A real email address and phone number were in two test files**
  (`tests/test_matching_eval.py`, `tests/test_truthfulness.py`). Replaced with
  `candidate@example.com` and `+91 90000 00000`; both modules still pass.
- No API keys, tokens or assigned secrets in any tracked file. `.env.example` ships empty
  values for `JA_API_TOKEN`, `JA_LLM_API_KEY` and `JA_EMAIL_APP_PASSWORD`.
- `var/` (database, resumes, artifacts, logs) and `.env` are both confirmed ignored.
- The employer contact addresses inside `tests/fixtures/eval_jobs_real.json` come from
  public job postings and are left as published.

Rollback, backup and reproducible-baseline procedures are documented in
[RELEASE.md](RELEASE.md) sections 7 and 8.

## R3.11 Remaining risks

**Technical**

1. **The resume blob remains in git history.** Untracking does not purge it. Until history
   is rewritten or the repository stays private, pushing leaks the candidate's name, email,
   phone and address.
2. **25 pre-existing false merges persist** in the local database. They are reported on the
   diagnostics page with their evidence and carry no applications, but the merged listings
   cannot be recovered without a fresh discovery.
3. **`high` confidence is unreachable on real data** (0 of 190). The badge exists and is
   tested, but a user will never see it unless an employer publishes a requirements list.
4. **Synthetic fixtures in the live database** outrank real listings and cannot be told
   apart by URL.
5. **Scoring is paged, not atomic.** A full rescore of 7,791 jobs takes four requests; a
   crash midway leaves a partially rescored database, which is self-healing on the next run
   but momentarily inconsistent.

**Product**

6. **Source coverage does not match the candidate.** 4 suitable India-located listings out
   of 7,791 is the headline risk: the tool works and has almost nothing to show.
7. **Recall is 0.41 against family-based labels**, because the 65 threshold excludes roles
   whose requirements the employer never published. Lowering the threshold would trade the
   zero false-positive rate away.
8. **No authorized submission mechanism exists anywhere in scope**, so the final step
   remains manual by design, not by omission.

**Needs human verification**

Real IMAP ingestion, actual LLM drafting output, a screen-reader pass, WCAG contrast
measurement, Windows and Linux, and whether the two pilot listings are ones the candidate
actually wants to apply to.

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
