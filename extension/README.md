# JobOrbit Capture (browser extension)

A small Chrome extension that sends the job listing you are looking at to your own,
locally running JobOrbit. Use it for sites JobOrbit has no discovery integration for:
LinkedIn, Naukri, Indeed, Wellfound, or a company's careers page.

It runs **only when you click its toolbar button**. Nothing runs in the background, nothing
is injected into pages you visit, and it never applies to a job.

## Install (load unpacked)

1. Start JobOrbit's API (from the repository root, see the main README):
   `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. Open `chrome://extensions` in Chrome, Edge or Brave.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and choose this `extension/` folder.
5. Optional: pin "JobOrbit Capture" from the puzzle-piece menu so the button is visible.
6. Optional: open the extension's **Options** to change the API address (default
   `http://127.0.0.1:8000`), add an API token, or change the dashboard address (default
   `http://localhost:8501`). **Test connection** checks that JobOrbit answers.

## Use

1. Open a job listing.
2. Click the JobOrbit button. The popup reads the listing and shows what it found:
   title, company, location, URL, posted date, employment type and description. Fields it
   could not find are listed; required ones (title, company, URL) are highlighted.
3. Correct anything that looks wrong, then click **Send to JobOrbit**.
4. The popup shows whether the job was added or was already in JobOrbit (the same posting
   is never stored twice), its match score and band, the top lines of the explanation, and
   a link to the job in the dashboard.

If the popup says it can't reach JobOrbit, the API isn't running or is on another port
(fix the address in Options). If it says a token is needed, JobOrbit was started with
`JA_API_TOKEN`; paste the same value into Options.

## What it can and cannot access

| | |
|---|---|
| **Permissions** | `activeTab`, `scripting`, `storage`. Host access only to `http://127.0.0.1/*` and `http://localhost/*` (your local JobOrbit). No `tabs`, `cookies`, `history`, `webRequest` or `<all_urls>`, no content scripts, no background service worker. |
| **Reads** | The one tab you clicked on, and only after the click (`activeTab`): its schema.org `JobPosting` data, the listing's visible text, `<link rel="canonical">`, and `<meta>` tags. |
| **Never reads** | Cookies, passwords, form fields (including anything you typed into the page), browser storage, history, bookmarks, or any other tab. The extractor skips `input`, `textarea`, `select`, `form` and hidden elements by construction. |
| **Sends** | The fields shown in the popup, after you press Send, to the API address in Options, which must be on this computer. Tracking parameters (`utm_*`, `trk`, `refId`, ...) are stripped from the URL first. |
| **Stores** | The API address, optional token and dashboard address, in the extension's own `chrome.storage.local`. |
| **Never does** | Crawl, follow links, open pages, run on its own, or submit an application. |

The extractor is `extractor.js`. It tries, in order: schema.org JSON-LD (including `@graph`
and arrays), then visible-page heuristics for LinkedIn, Naukri, Indeed and Wellfound job
views, then the page heading and `og:`/meta tags. Each heuristic is defensive: when a
site's markup changes and a selector stops matching, that field comes back empty for you to
fill in rather than guessed. Site markup changes often; expect to correct fields
occasionally.

## Tests

`tests/test_capture.py` runs `extractor.js` in headless Chrome against synthetic pages in
`tests/fixtures/capture/` that imitate each site's structure. They are not the real sites.
It also loads this unpacked extension into Playwright's Chromium (branded Chrome no longer
accepts `--load-extension`) and sends a capture through the popup to a live local API.
