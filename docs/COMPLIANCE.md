# Platform Compliance

Research performed **2026-10-28** by fetching each platform's own legal pages. Every claim
below is either a direct quote from the platform with its URL, or explicitly marked
`UNVERIFIED`. Where a fact could not be verified from the platform's own page, the adapter
defaults to the **most restrictive** setting rather than an assumed permission.

The outcome of this research is the single most important design constraint in this
project: **no platform in scope offers an authorized job-search interface to an individual
jobseeker, and automated application submission is prohibited.** The application is built
around that fact instead of around it.

---

## Summary table

| Platform | Scraping prohibited | Jobseeker job-search API | Automated submission prohibited | Legitimate jobseeker feed | `authorized_discovery_enabled` |
|---|---|---|---|---|---|
| LinkedIn | **Yes** (quoted below) | No — partner/employer gated | **Yes** | Email job alerts (user's own inbox) | `False` |
| Indeed | Yes (license revoked for non-personal use) | No public jobseeker search API | **Yes** (explicit) | "Recommended jobs" email alerts | `False` |
| Naukri | `UNVERIFIED` — page not retrievable | `UNVERIFIED` — none found | `UNVERIFIED` | Email job alerts | `False` (most restrictive) |
| Wellfound | **Yes** (quoted below) | No | Yes (automated access restricted) | None found | `False` |
| Manual import | Not applicable — you supply the file | Not applicable | Not applicable | JSON / CSV you provide | `False` (nothing to discover) |
| Email alerts | Not applicable — your own mailbox | Not applicable | Not applicable | IMAP, opt-in | `True` when you enable it |

`automated_submission_enabled` is `False` for **every** source, is rejected by a validator
in `AdapterCapabilities`, by a validator in the `Capabilities` schema, and by a
`CHECK (NOT automated_submission_enabled)` constraint on the `source_configuration` table.

---

## LinkedIn

**1. Scraping — PROHIBITED.** LinkedIn's User Agreement (effective 3 November 2025),
Section 8.2 "Dos and Don'ts", as reproduced on LinkedIn's own help page, states that
members agree not to:

> "Develop, support or use software, devices, scripts, robots or any other means or
> processes (such as crawlers, browser plugins and add-ons or any other technology) to
> scrape or copy the Services, including profiles and other data from the Services"

> "Use bots or other unauthorized automated methods to access the Services, add or
> download contacts, send or redirect messages, create, comment on, like, share, or
> re-share posts, or otherwise drive inauthentic engagement"

> "Override any security feature or bypass or circumvent any access controls or use limits
> of the Services (such as search results, profiles, or videos)"

> "Copy, use, display or distribute any information (including content) obtained from the
> Services, whether directly or through third parties (such as search tools or data
> aggregators or brokers), without the consent of the content owner"

(https://www.linkedin.com/help/linkedin/answer/a1341387 — "Prohibited software and
extensions"; https://www.linkedin.com/legal/user-agreement)

The same help page is unambiguous about third-party tooling: *"we don't permit the use of
any third party software, including 'crawlers', bots, browser plug-ins, or browser
extensions that scrape, modify the appearance of, or automate activity on LinkedIn's
website"*, and warns that *"any member who uses tools for such purposes is in violation of
the User Agreement... they risk having their accounts restricted or shut down."*

**2. Jobseeker job-search API — NOT AVAILABLE.** LinkedIn's job-related APIs are part of
Talent Solutions and are gated behind partner approval for employers and ATS vendors. No
self-serve API grants an individual jobseeker programmatic job search.

**3. Automated submission — PROHIBITED**, by the "bots or other unauthorized automated
methods to access the Services" clause above.

**4. Legitimate feed.** LinkedIn sends job-alert emails to the member's own mailbox. Those
emails are the member's own data in their own inbox, which is why the email-ingestion
adapter is the compliant path. LinkedIn also lets a member export their own data.

**5. Precedent.** *hiQ Labs v. LinkedIn* concerned whether scraping **public** pages
violates the US Computer Fraud and Abuse Act; the Ninth Circuit's holding was that it
likely does not constitute CFAA "unauthorized access". It did **not** hold that scraping
is permitted: on remand the parties settled with hiQ subject to an injunction, and the
breach-of-contract question under the User Agreement is separate from and unaffected by
the CFAA question. A CFAA defence is not a licence to breach the User Agreement.

**Capabilities set:** `manual_import_enabled=True`, `authorized_discovery_enabled=False`,
`browser_assistance_enabled=True` (opens the official page in your browser, a
user-initiated navigation), `automated_submission_enabled=False`.

---

## Indeed

**1. Scraping — PROHIBITED for any non-personal use.** Indeed's Terms of Service (last
updated 29 September 2026), Section A "Terms for Job Seekers":

> "As a Job Seeker, you are permitted to use the Site and its content for your personal,
> non-commercial purpose of seeking employment or information related to your job search.
> You agree that your license to use the Site is automatically revoked upon your attempt
> to use the Site for any other purpose."

(https://www.indeed.com/legal)

**2. Jobseeker job-search API — NOT AVAILABLE.** Indeed's API documentation and Developer
Portal are framed around employers and their integrations; the Terms define an API
"End User" as *"an entity, such as an Employer client"*. Indeed's former public Job Search
API for publishers is no longer offered for this use case.

**3. Automated submission — EXPLICITLY PROHIBITED.** Section A.3 "Applying to Jobs",
under "Limits":

> "Use of any automation, scripting, or bots to automate the Indeed Apply process outside
> of Indeed's official vendors and tooling is prohibited."

This is the clearest statement across all four platforms and is the direct basis for this
application having no submission code path at all.

Indeed's Terms also state the principle this application is designed around — that the
tool must not replace the user's own judgement:

> "You agree, as a condition of using the Site, that you will not use the Site, in whole
> or in part, as a substitute for your own independent judgment or decision-making."

**4. Legitimate feed.** Indeed sends "recommended jobs" alert emails to the address
associated with the account, controllable in communication settings. These arrive in the
user's own mailbox and are therefore ingestible via the opt-in email adapter.

**Capabilities set:** `manual_import_enabled=True`, `authorized_discovery_enabled=False`,
`browser_assistance_enabled=True`, `automated_submission_enabled=False`.

---

## Naukri (Naukri.com, Info Edge India Ltd.)

**1-3. `UNVERIFIED`.** `https://www.naukri.com/termsconditions` returned an empty body to
a programmatic fetch on 2026-10-28 (the page appears to require a browser to render, and
fetching it with a browser-like client specifically to defeat that would itself be the kind
of automated access the research is meant to establish the legality of). **No clause is
quoted here because none was verified.**

Because nothing was verified, the adapter applies the most restrictive defaults:
`authorized_discovery_enabled=False` and no scraping of any kind. The adapter's
`policy_basis` string says exactly this to the user on the Sources page, rather than
implying a permission that was never confirmed.

**4. Legitimate feed.** Naukri offers email job alerts / recommended-jobs mailers to
registered jobseekers. Those land in the user's own mailbox and are ingestible via the
opt-in email adapter.

**To enable Naukri discovery**, a maintainer must read Naukri's current Terms &
Conditions, record the relevant clause and its URL in this file, and only then change the
adapter's declared capability. Editing `.env` cannot do it, by design.

---

## Wellfound (formerly AngelList Talent)

**1. Scraping — PROHIBITED.** Wellfound's Talent General Terms, Section III "Covenants",
state that you will not:

> "copy, disclose or distribute Content except as expressly permitted by the Terms
> (including through the use of automated or non-automated harvesting, collection or
> 'scraping') or otherwise use the Site or Services for competitive purposes"

> "use any automated system (including a spider, robot, or offline reader) to access the
> Site or Services in a manner that takes more bandwidth or produces greater load on
> Wellfound's network or servers than a human can reasonably produce in the same period of
> time by using a conventional on-line web browser"

> "use any Content, or other information acquired from the Site or through your use of the
> Services for commercial activity"

(https://wellfound.com/terms)

Section VIII adds: *"You agree not to copy, distribute or disclose any Content contained on
the Site or accessible through the Services unless we have given you express written
permission to do so."* Section X requires that on termination you *"destroy and remove from
all computers, cloud storage and other storage media all Content that you acquired through
use of the Site or Services"* — which is why the application provides a per-source data
deletion control.

**2. Jobseeker job-search API — NOT AVAILABLE.** No public job-search API is offered.

**3. Automated submission — PROHIBITED** under the automated-system clause above.

**4. Legitimate feed.** No RSS or public machine-readable jobseeker feed was found.

**Note on scope.** Wellfound's terms restrict the Site to Candidates and Employers:
*"If you are not a Candidate or an Employer, for example, if you are an external
third-party recruiter or agency (including talent marketplaces), then you may not use the
Site or the Services for any purpose."* A personal assistant used by the candidate
themselves is within the Candidate role; redistributing its output would not be.

**Capabilities set:** `manual_import_enabled=True`, `authorized_discovery_enabled=False`,
`browser_assistance_enabled=True`, `automated_submission_enabled=False`.

---

## General legal position (US and India, 2026)

Scraping publicly accessible pages and breaching a site's terms of service are two
separate questions. In the US, *hiQ Labs v. LinkedIn* indicates that accessing public data
is unlikely to be CFAA "unauthorized access", but contract, copyright and trespass claims
remain available to the platform, and *Van Buren v. United States* narrowed the CFAA on
"exceeds authorized access" grounds without touching contract law. In India, the
Information Technology Act, 2000 (notably s.43 on unauthorized access and s.66 on computer
related offences) plus Indian contract and copyright law govern; the Digital Personal Data
Protection Act, 2023 additionally regulates processing of personal data, which job
listings and recruiter contact details can contain.

The practical conclusion for this project: "technically reachable" is not "permitted", a
favourable CFAA ruling is not a licence, and the only durable basis for data acquisition
here is data the user already possesses — their own files and their own mailbox.

---

## What this application does and does not do

**Does:**

- Import JSON and CSV files that the user supplies. The only fully working discovery path.
- Ingest job-alert emails from the user's own mailbox over IMAP, read-only, opt-in,
  disabled by default, with the password read from the environment and never stored.
- Normalize, deduplicate, score and explain those jobs locally.
- Prepare a complete application for review, and open the employer's official page in the
  user's own browser so they can submit it themselves.

**Does not, and has no code to do:**

- Scrape, crawl or fetch job listings from any platform's website.
- Log into any platform, or store any platform password or session cookie.
- Use a stealth browser, a bot-detection bypass, a CAPTCHA solver, or a proxy rotator.
- Click a Submit or Apply button, or fill a form on a live page.
- Expose any endpoint that submits an application. `POST /api/applications/prepare` stops
  at `READY_FOR_REVIEW`; recording a submission requires the user to name who submitted it.

**Verification.** `tests/test_compliance.py` asserts these properties mechanically: every
registered adapter reports `automated_submission_enabled=False`, every adapter without
`authorized_discovery_enabled` raises `CapabilityNotAvailable` with a non-empty reason
instead of returning data, the capability schema rejects an enabled submission flag, the
database rejects the row, and no route in the FastAPI app contains "submit" as an
operation.

---

## Greenhouse, Lever and Workable — why these three are different

These are applicant tracking systems, not job platforms. Each publishes an
**unauthenticated endpoint whose documented purpose is to serve one company's own job
board**, and it is the same endpoint that company's careers page calls to render its
openings.

| ATS | Endpoint | Nature |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{board}/jobs` | Public Job Board API |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | Public Postings API |
| Workable | `apply.workable.com/api/v1/widget/accounts/{sub}` | Public careers-widget API |

Reading them involves no credentials, no session, no rate-limit evasion, no anti-bot
measure and no access control of any kind — it is the interface's intended use. That is
why these three are the only platform adapters with `authorized_discovery_enabled=True`.

Two safeguards keep this narrow:

1. **Opt-in per company.** No company list ships with the application. Nothing is fetched
   until the user names board identifiers in `JA_GREENHOUSE_BOARDS`, `JA_LEVER_BOARDS` or
   `JA_WORKABLE_BOARDS`. A targeted lookup of boards the user chose is not a crawl.
2. **Discovery only.** These adapters read listings. They do not create candidate
   accounts, upload resumes, or submit applications — Greenhouse and Lever both have
   application-submission APIs that require an employer-issued key, and neither is used.

**Verification status.** Greenhouse and Lever were each confirmed against a live board
returning real postings. Workable's endpoint returns the documented envelope, but no
populated board was found, so its per-job field mapping is unverified and
[SOURCES.md](SOURCES.md) says so rather than implying it was tested.

## Workday — reachable but deliberately unused

Every Workday tenant serves its careers page from `/wday/cxs/{tenant}/{site}/jobs`, so a
feed is technically obtainable. It is not used. That path is an internal interface for
Workday's own front end rather than a published integration, and Workday's documented
recruiting APIs require tenant credentials issued to the employer. This is precisely the
"technically possible, not authorized" case, and the adapter states that reason verbatim.

## Bulk preparation does not change any of this

`POST /api/batches` prepares many applications at once. It reuses the same preparation
service as the single-job path and stops at the same place: `READY_FOR_REVIEW`. It opens no
browser, touches no platform, and has no submit route. `tests/test_batch.py` asserts that
no path under `/api/batches` mentions submission and that the OpenAPI document contains no
submit route at all.

The answer bank adds a reuse mechanism, not a generation mechanism. Only an answer the user
typed or one read from a verified profile field can be banked; an `ai_draft` is rejected by
`UnbankableAnswerError` and, independently, by a database `CHECK` constraint. Sensitive and
legal questions — work authorization, sponsorship, salary, notice period, experience,
education, legal declarations — are never drafted at any batch size.
