# JobOrbit walkthrough

JobOrbit reads your resume, ranks job listings against it with a score you can inspect,
and prepares honest applications (cover letter, form answers, a tailored resume) that you
review before anything is sent.

There are two ways to use it:

| | **Try the live demo** | **Use it for your own job search** |
|---|---|---|
| Where | [job-orbit-chi.vercel.app](https://job-orbit-chi.vercel.app) | Your own computer |
| Setup | None. Open the link | About 10 minutes, once |
| Data | A fictional candidate and 7 sample jobs | Your resume and real listings |
| Who sees it | Only you. Each visitor gets a private copy for 2 hours | Only you. Nothing leaves your machine |

---

## Part 1: Try the live demo (5 minutes)

### Before you start

The demo's API runs on a free server that sleeps when nobody is using it. **The first page
you open may take up to a minute to load.** After that, everything is quick.

### 1. Open the site

Go to **https://job-orbit-chi.vercel.app** and press **Open the dashboard**.

A yellow banner at the top says you are in the live demo. Anything you change is saved
only in your own copy, which is deleted after 2 hours. Other visitors never see it.

### 2. Dashboard: see what needs doing

The dashboard is the home screen. It shows how many jobs match, what is waiting for you,
and where each application stands. Every card links to the page that deals with it.

### 3. Job discovery: see why a job matches

Open **Job discovery** in the sidebar. The seven sample jobs are ranked best match first.

- Each job has a **score out of 100**. Open a job and look at the breakdown to see exactly
  which skills, experience and location rules earned or lost points. Nothing is hidden.
- Some jobs are deliberately bad matches: a senior role that asks for far more experience,
  a sales role, a listing with almost no description. Notice how the app explains why they
  rank low, instead of quietly dropping them.
- Press **Save** on a job you like, or **Skip** on one you don't. Saved jobs appear under
  **Saved jobs**.

### 4. Prepare an application

Open a good match (try *Backend Developer (Python)* at Northwind Systems) and press
**Prepare application**. In a few seconds JobOrbit writes:

- a cover letter built only from facts in the candidate's profile,
- answers to the usual application questions,
- a note of anything it could not answer, instead of a guess.

### 5. Action inbox: answer a question once

Open **Action inbox**. When an application needs something only you know (notice period,
expected salary, work authorisation), it lands here. Answer it once and JobOrbit reuses
that answer on every application that asks it.

### 6. Review queue: approve before sending

Open **Review queue**. This is where you read and edit each prepared application before
it goes anywhere. Nothing is ever sent without passing through here.

### 7. Applications: track outcomes

Open **Applications** to see every application with its status (prepared, applied,
interview, offer, rejected), and record what happened.

### 8. Interview prep and company research

- **Company research** summarises what the listings say about a company.
- **Interview prep** generates likely questions for a prepared application, and lets you
  practise answers and log interview rounds.

### 9. Auto-apply: see what a run would do

Open **Auto-apply** and press **Build preflight**. It shows exactly which jobs a run would
apply to, which it would skip, and why. In the demo it stops at the preview; it never
submits anything.

### 10. Analytics

Open **Analytics** for response rates, which kinds of roles get replies, and how your
pipeline is moving.

### What the demo cannot do

These are switched off because the demo is shared and has no login. They all work when
you run JobOrbit on your own computer (Part 2).

| Disabled in the demo | Why |
|---|---|
| Uploading a resume | Without a login, the next visitor could read it |
| Importing jobs or running discovery | It would write to shared data or call other companies' job boards for every visitor |
| Bulk preparation runs and real auto-apply runs | Too heavy for a free shared server. The previews still work |
| Connecting Gmail for email tracking | It would expose a personal mailbox |
| The browser extension's job capture | Captured jobs would land in shared data |
| Fetching company websites | It spends the server's network on every request |

If you press one of these, the app tells you why instead of failing silently.

---

## Part 2: Use JobOrbit for your own job search

Run it on your own computer. Your resume, answers and applications stay on your machine.

### What you need

- **Python 3.11, 3.12 or 3.13** (not 3.14 yet). Check with `python3 --version`.
- **Node.js 20 or newer.** Check with `node --version`.
- **Git.**

### 1. Download and install (once)

```bash
git clone https://github.com/coderxtushar/JobOrbit.git
cd JobOrbit

python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head

cd frontend
npm install
cp .env.example .env.local
cd ..
```

On Windows, use `.venv\Scripts\` in place of `.venv/bin/`.

### 2. Start it (every time)

Open two terminals in the `JobOrbit` folder.

```bash
# Terminal 1: the API
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: the website
cd frontend && npm run dev
```

Then open **http://localhost:3000** in your browser.

### 3. First run, in order

1. **Resume and profile.** Upload your resume (PDF or DOCX). JobOrbit shows what it read.
   Tick the details that are right, press **Copy into the profile form**, check the form,
   then press **Save profile**. Nothing reaches your profile until you save it.
2. **Answers.** On the same page, fill in the common questions: work authorisation,
   notice period, expected salary, current location, current company. Anything you leave
   blank is asked later, never guessed.
3. **Sources.** Open **Sources** and switch on the job boards you want. Automatic discovery
   uses the public Greenhouse, Lever and Workable job-board APIs, which allow it. For
   LinkedIn, Naukri, Indeed and similar sites, import a CSV or use the browser extension to
   save a listing you are viewing.
4. **Job discovery.** Press **Discover jobs** to fetch listings, or import a file. Every
   job gets a score, and the best matches rise to the top.
5. **Prepare.** Prepare the jobs you like one at a time, or many at once from
   **Bulk preparation**.
6. **Action inbox.** Answer whatever JobOrbit could not fill in. Each answer is reused.
7. **Review queue.** Read each application, edit it, approve it, then submit it yourself on
   the company's page and record that you did.
8. **Applications.** Track replies, interviews and offers.

### Optional extras

- **Email tracking.** Connect Gmail read-only in **Email tracking**, and JobOrbit spots
  replies, interview invites and rejections and suggests status updates.
- **AI writing.** Set `JA_LLM_PROVIDER` and `JA_LLM_API_KEY` in `.env` (copy
  `.env.example` first) and JobOrbit polishes cover letters. It
  still only uses facts you have verified. Without a key, everything works using templates.
- **Auto-apply in the browser.** For employers whose application form is on Greenhouse,
  Lever or Ashby, JobOrbit can fill the form for you. Start with a **dry run**: it fills
  every field and takes a screenshot, but does not press Submit, so you can check it
  first. See [Auto-apply in the browser](../README.md#auto-apply-in-the-browser).

### What JobOrbit never does

- It never logs in to LinkedIn, Naukri, Indeed or Wellfound to apply for you. Those sites
  forbid automation, so JobOrbit prepares everything and opens the page for you to submit.
- It never makes up an answer. A question it cannot answer from your verified details
  goes to your Action inbox.
- It never gets past a CAPTCHA or a login check for you. It stops and hands the step back
  to you.

---

## Common questions

**The demo is stuck on loading.** The free server is waking up. Wait a minute and refresh.

**My changes in the demo disappeared.** Demo copies last 2 hours, then reset. Run it
locally to keep your work.

**Can I put my own resume on the live demo?** No. Uploading is disabled there on purpose,
because the demo has no login. Run JobOrbit locally (Part 2) for your real job search.

**Something broke.** Open an issue at
[github.com/coderxtushar/JobOrbit/issues](https://github.com/coderxtushar/JobOrbit/issues)
with what you clicked and what you saw.
