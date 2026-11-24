# Email response tracking (opt-in, read-only)

JobOrbit can read replies to your applications in your own Gmail: confirmations,
rejections, interview and assessment invitations, offers, and recruiter messages. Each one
is classified, matched to the application it is about, and turned into a **suggested**
status change. Nothing changes an application until you press **Accept** on the Email
tracking page.

What it never does: send email, ask for your Google password, read your whole mailbox,
or apply a status change by itself.

You can also use it without connecting Gmail: paste an email's raw source (or upload a
`.eml` file) on the Email tracking page and it goes through the same pipeline.

## Setup

Google requires every app that reads Gmail to have its own OAuth client. JobOrbit is a
local app with no server of its own, so you create that client in **your own** Google
Cloud project. It takes about five minutes and costs nothing.

1. Open <https://console.cloud.google.com/> and create a project (any name, e.g.
   "JobOrbit local").
2. **APIs & Services → Library**: search for **Gmail API** and enable it.
3. **APIs & Services → OAuth consent screen** (called "Google Auth Platform" in newer
   consoles):
   - User type: **External**.
   - App name and support email: anything; your own address is fine.
   - **Scopes**: add `https://www.googleapis.com/auth/gmail.readonly` only.
   - **Test users**: add your own Gmail address. Leave the publishing status as
     **Testing**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app**.
   - Copy the client ID and client secret. (For a Desktop client the "secret" is not
     confidential by Google's own design; PKCE is what protects the exchange.)
5. Add to your `.env`:

   ```
   JA_EMAIL_TRACKING_ENABLED=true
   JA_GMAIL_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
   JA_GMAIL_CLIENT_SECRET=GOCSPX-...
   # optional
   JA_EMAIL_SYNC_DAYS=30          # how far back a sync looks (1-365)
   JA_EMAIL_MAX_MESSAGES=200      # most messages read per sync (1-2000)
   JA_SECRET_BACKEND=auto         # auto | keychain | file
   ```

6. Restart JobOrbit, open **Email tracking**, press **Connect Gmail**, then **Open Google
   sign-in**. Google will warn that the app is unverified: that is expected for an app in
   testing mode that only you use. Choose *Continue*, allow read-only access, and close the
   tab when it says "Gmail connected".

The redirect goes to `http://127.0.0.1:{JA_API_PORT}/api/email/gmail/callback` (8000 by
default). Desktop clients accept any loopback port, so nothing has to be registered.

## The scope, and why only that one

JobOrbit requests exactly `https://www.googleapis.com/auth/gmail.readonly`.

- It is the narrowest scope that can read message content. (`gmail.metadata` cannot read
  bodies, which is where "unfortunately" and interview dates are.)
- It cannot send, delete, archive, label or modify anything. Even a bug in JobOrbit could
  not touch your mailbox.
- If Google's token response ever grants a different set of scopes, JobOrbit refuses the
  connection and revokes the token.
- The only Gmail endpoints called are `users.getProfile` (to show which address is
  connected), `users.messages.list` and `users.messages.get`, all HTTP GET.

## What a sync reads

A sync does **not** read your whole mailbox. It runs one Gmail search:

- received within `JA_EMAIL_SYNC_DAYS` days (`newer_than:30d`),
- excluding the Promotions and Social tabs,
- matching job-related phrases ("your application", "thank you for applying", interview,
  assessment, "offer letter", unfortunately, recruiter...) **or** sent from a known
  applicant-tracking or assessment system (greenhouse.io, lever.co, ashbyhq.com,
  myworkday.com, hackerrank.com, codility.com and similar),

and reads at most `JA_EMAIL_MAX_MESSAGES` of the results. Each message is then classified
locally, and only those judged job-related are kept. Job-alert digests ("15 new jobs for
you") are not responses to an application and are not kept.

## What is stored, and what is not

Stored in the local database, per job-related email:

- subject (with email addresses and phone numbers redacted), sender address and domain,
  recipient, received time, Gmail message and thread ids,
- a snippet of at most 500 characters, with email addresses, phone numbers, tokens and
  your profile name redacted,
- the category, confidence and the phrases that decided it,
- extracted facts: employer, job title, application reference, deadline, interview
  date/time/timezone, meeting link, assessment link,
- which application it was matched to, and the candidates considered.

Not stored anywhere: the full message body, attachments, emails that are not job-related,
and your Google password (JobOrbit never sees it).

Meeting and assessment links are stored as written because you need them to join; they
can contain an invitation token. They stay in your local database and are never logged.

## Suggestions

| Email | Suggests |
|---|---|
| Application confirmation | status → `CONFIRMED` (with the email as confirmation evidence) |
| Rejection | outcome → `rejected` |
| Interview invitation | outcome → `interviewing` |
| Assessment invitation | outcome → `screening` |
| Offer | outcome → `offer` |
| Process update, recruiter message, other | nothing; shown for reference |

Accepting goes through the same transition rules as editing an application by hand.
`CONFIRMED` is reachable only from `SUBMITTED`, `SUBMISSION_UNKNOWN`, or `APPROVED` (which
is first recorded as submitted). From any other status the Accept is refused with the
reason, and the suggestion stays pending. Outcome changes that would move backwards (an
offer back to screening), or that touch an outcome you set to accepted, withdrawn or
rejected, are refused the same way.

If an auto-apply attempt for the application ended as **outcome unknown**, accepting a
confirmation email marks that attempt confirmed, with `confirmation_id = email-<hash>` and
the email as evidence. Until you accept, the attempt stays unknown.

### Matching

An email is linked automatically only when one application is clearly the best match
(employer, title, reference number, sender domain vs. the job's site or ATS board,
recipient, and timing all count) **and** clearly ahead of the next candidate. Otherwise it
appears under **Needs your pick** with the likely candidates and why each was proposed.

## Where the token lives

The refresh token is never written to the database or a log. It goes to:

1. the `keyring` package, if you have it installed;
2. otherwise on macOS, your login keychain (service **JobOrbit**, visible in Keychain
   Access);
3. otherwise a file in `var/secrets/` (directory mode 0700, file mode 0600).

`JA_SECRET_BACKEND=keychain` refuses to fall back to a file; `JA_SECRET_BACKEND=file`
always uses the file. Short-lived access tokens are kept in memory only.

## Disconnect and deletion

- **Disconnect** revokes the token at Google's revoke endpoint (best effort), deletes it
  from the secret store, and marks the account disconnected. Stored emails remain until
  you delete them.
- **Delete email data** disconnects, then deletes every stored email, every suggestion made
  from one, and the account record. Changes you already accepted stay on your
  applications: they are your decisions, not email data.
- You can also remove access at any time from <https://myaccount.google.com/permissions>.

## Limitations

- **Testing-mode tokens expire after 7 days.** Google expires refresh tokens for apps whose
  consent screen is in "Testing" status after seven days. For personal use the app stays
  in testing (publishing a Gmail-reading app requires Google's security review), so expect
  to press **Connect Gmail** again about once a week. A sync after expiry marks the account
  `reauth_required` and says so.
- Classification is rule-based and tuned for English ATS phrasing. Unusual wording may
  land as "other job-related" (no suggestion) rather than the right category; nothing is
  ever applied without your Accept either way.
- Dates written ambiguously (`04/05/2026`) are left unknown rather than guessed.
- Only Gmail is supported for automatic sync. Other providers can use the paste/upload path.
- Email tracking is disabled on a shared public demo, because a demo has no per-user login.
