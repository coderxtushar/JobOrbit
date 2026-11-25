"""Loopback copies of Greenhouse, Lever and Ashby application forms, for browser tests.

Each page reproduces the markup the real provider served when it was inspected
(November 2026), because that markup is what the browser adapter has to read:

* ``/greenhouse/<company>/jobs/<id>`` — ``label[for]`` inputs with ``*`` for required,
  a city lookup and choice questions rendered as ``role="combobox"`` menus whose options
  exist only while open, and a resume input labelled only "Attach".
* ``/lever/<company>/<id>/apply`` — named inputs, ``✱`` for required, a ``cards[...]``
  radio question whose text sits in ``.application-label``, a checkbox group, and a
  ``/thanks`` redirect on success.
* ``/ashby/<company>/<id>/application`` — required marked by a ``_required`` class on the
  label, an unlabelled "autofill" file input before the real resume input, and yes/no
  questions as ``aria-pressed`` buttons beside a hidden checkbox; success replaces the form
  in place without navigating.

Query flags change behaviour per test: ``captcha=1`` shows a challenge frame on Submit,
``mfa=1`` asks for an emailed verification code on Submit, ``mfa_on_load=1`` on arrival,
``rerender=1`` rebuilds the form 1.5 s after load (dropping JobOrbit's field tags),
``upload_rerender=1`` swaps the file input for a filename chip and drops the tags on upload,
``reject=1`` makes the server refuse the submission with a field error, ``silent=1``
swallows the submission with no response, ``preexisting=1`` puts a confirmation phrase on
the page before anything is submitted, ``essay=1`` adds a required free-text question and
``consent=1`` a required declaration checkbox.

Submissions are recorded in :attr:`FormServer.received`, including the uploaded file's
name and size as the browser reported them.
"""

from __future__ import annotations

import html
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

_SUBMIT_JS = """
<script>
function joCollect(form) {
  const data = {};
  form.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.type === 'file') { if (el.files.length) data['file:' + (el.name || el.id || 'file')] = el.files[0].name + '|' + el.files[0].size; return; }
    if ((el.type === 'radio' || el.type === 'checkbox')) { if (el.checked) data[el.name] = (data[el.name] ? data[el.name] + ';' : '') + el.value; return; }
    if (el.name || el.id) data[el.name || el.id] = el.value;
  });
  document.querySelectorAll('[aria-pressed=true]').forEach(b => { data['pressed:' + b.closest('[data-q]').dataset.q] = b.innerText; });
  document.querySelectorAll('[data-combo-value]').forEach(c => { data['combo:' + c.dataset.comboValue] = c.innerText; });
  return data;
}
async function joSubmit(provider, id, flags, onDone) {
  const form = document.querySelector('form');
  let bad = false;
  form.querySelectorAll('[data-required]').forEach(el => {
    const empty = el.type === 'file' ? !(el.files.length || el.dataset.uploaded) : (el.type === 'checkbox' ? !el.checked : !el.value);
    if (empty) { el.setAttribute('aria-invalid', 'true'); bad = true; }
  });
  document.querySelectorAll('[data-q][data-req]').forEach(g => { if (!g.querySelector('[aria-pressed=true]')) bad = true; });
  if (bad) { document.getElementById('errors').innerText = 'Please complete all required fields.'; return; }
  if (flags.mfa) {
    // A provider asking for a code it emailed the candidate: nothing is sent until then.
    const box = document.createElement('div');
    box.innerHTML = '<p>Enter the verification code we sent to your email.</p>' +
      '<input autocomplete="one-time-code" name="security_code">';
    document.body.appendChild(box);
    return;
  }
  if (flags.captcha) {
    const f = document.createElement('iframe');
    f.src = 'about:blank#recaptcha/api2/bframe';
    f.style.width = '400px'; f.style.height = '580px';
    document.body.appendChild(f);
    return;
  }
  const res = await fetch('/submit/' + provider + '/' + id + location.search, { method: 'POST', body: JSON.stringify(joCollect(form)) });
  if (flags.silent) return;
  const body = await res.json();
  if (!body.ok) { document.getElementById('errors').innerText = body.error; const el = form.querySelector('[name=email],[id=email],#_systemfield_email'); if (el) el.setAttribute('aria-invalid', 'true'); return; }
  onDone();
}
</script>
"""


def _page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>.vh{position:absolute;width:1px;height:1px;opacity:0;overflow:hidden}"
        ".menu{border:1px solid #999;margin:0;padding:0}.menu div,.menu li{padding:4px;cursor:pointer;list-style:none}"
        "</style></head><body>" + body + _SUBMIT_JS + "</body></html>"
    ).encode("utf-8")


def _flags(query: dict[str, list[str]]) -> dict[str, bool]:
    return {
        key: query.get(key, ["0"])[0] == "1"
        for key in (
            "captcha",
            "reject",
            "silent",
            "preexisting",
            "essay",
            "consent",
            "mfa",
            "mfa_on_load",
            "rerender",
            "upload_rerender",
        )
    }


def greenhouse_page(company: str, job_id: str, title: str, flags: dict[str, bool]) -> bytes:
    pre = (
        "<p>Thank you for applying to roles at our company in the past.</p>"
        if flags["preexisting"]
        else ""
    )
    if flags["mfa_on_load"]:
        pre += "<p>Verify it's you: enter the code we sent to your phone.</p>"
    if flags["upload_rerender"]:
        # Like Greenhouse's current form: attaching a file swaps the input for a filename
        # chip and re-renders the rest of the form, so every JobOrbit tag is dropped.
        pre += (
            "<script>document.addEventListener('change', (ev) => { const el = ev.target;"
            " if (el.type !== 'file' || !el.files.length) return; const name = el.files[0].name;"
            " const chip = document.createElement('span'); chip.textContent = name + ' ✕';"
            " const stub = document.createElement('input'); stub.type = 'file'; stub.id = el.id;"
            " stub.className = 'vh'; stub.dataset.required = ''; stub.dataset.uploaded = '1';"
            " el.replaceWith(stub, chip); const f = document.querySelector('form');"
            " f.querySelectorAll('[data-jo-field]').forEach(e => { e.removeAttribute('data-jo-field');"
            " e.removeAttribute('data-jo-option'); }); }, true);</script>"
        )
    if flags["rerender"]:
        # A single-page form rebuilding its DOM after load: new nodes, no JobOrbit tags.
        pre += (
            "<script>setTimeout(() => { const f = document.querySelector('form');"
            " f.querySelectorAll('[data-jo-field]').forEach(e => { e.removeAttribute('data-jo-field');"
            " e.removeAttribute('data-jo-option'); }); f.replaceWith(f.cloneNode(true)); }, 1500);</script>"
        )
    consent = (
        "<div><input type='checkbox' id='question_bgv' data-required>"
        "<label for='question_bgv'>I consent to a background verification check*</label></div>"
        if flags["consent"]
        else ""
    )
    body = f"""
    <div class="job__header"><h1>{html.escape(title)}</h1><p>{html.escape(company)} · Gurugram</p></div>{pre}
    <h2>Apply for this job</h2>
    <form onsubmit="return false">
      <label for="first_name">First Name*</label><input id="first_name" type="text" aria-required="true" data-required>
      <label for="last_name">Last Name*</label><input id="last_name" type="text" aria-required="true" data-required>
      <label for="email">Email*</label><input id="email" type="text" aria-required="true" data-required>
      <label for="phone">Phone*</label><input id="phone" type="tel" aria-required="true" data-required>
      <div class="select">
        <label for="candidate-location">Location (City)*</label>
        <input id="candidate-location" type="text" role="combobox" aria-required="true" aria-autocomplete="list" data-required
               oninput="joCity(this)">
        <div id="city-menu" class="menu" role="listbox"></div>
      </div>
      <div class="file-upload"><div class="label">Resume/CV*</div>
        <label for="resume">Attach</label><input id="resume" type="file" class="vh" data-required></div>
      <label for="question_li">LinkedIn Profile</label><input id="question_li" type="text">
      <div class="select" id="relative-box">
        <label for="question_rel">Do you have a relative working at {html.escape(company)}?*</label>
        <input id="question_rel" type="text" role="combobox" aria-required="true" readonly data-required
               onclick="joOpen('question_rel', ['Yes','No'])">
        <div class="select__single-value" data-combo-value="relative"></div>
        <input class="css-1a0ro4n-requiredInput" tabindex="-1" aria-label="" required
               style="opacity:0;position:absolute;width:1px;height:1px">
      </div>
      {consent}
      <div id="errors" role="alert"></div>
      <button type="submit" onclick="joSubmit('greenhouse', '{job_id}', {html.escape(json.dumps(flags))}, () => {{ window.location.href = window.location.pathname + '/confirmation'; }})">Submit application</button>
    </form>
    <script>
      function joCity(el) {{
        const menu = document.getElementById('city-menu'); menu.innerHTML = '';
        ['Gurugram, Haryana, India', 'Bengaluru, Karnataka, India', 'Gurgaon, Haryana, India'].filter(c => c.toLowerCase().startsWith(el.value.toLowerCase().slice(0, 3))).forEach(c => {{
          const d = document.createElement('div'); d.setAttribute('role', 'option'); d.innerText = c;
          d.onclick = () => {{ el.value = c; menu.innerHTML = ''; }}; menu.appendChild(d);
        }});
      }}
      function joOpen(id, options) {{
        const input = document.getElementById(id); let menu = document.getElementById(id + '-menu');
        if (menu) menu.remove();
        menu = document.createElement('div'); menu.id = id + '-menu'; menu.className = 'menu'; menu.setAttribute('role', 'listbox');
        options.forEach(o => {{ const d = document.createElement('div'); d.setAttribute('role', 'option'); d.innerText = o;
          d.onclick = () => {{ input.value = o; input.parentElement.querySelector('[data-combo-value]').innerText = o; menu.remove(); }}; menu.appendChild(d); }});
        input.parentElement.appendChild(menu);
        document.addEventListener('keydown', e => {{ if (e.key === 'Escape' && menu.isConnected) menu.remove(); }}, {{ once: true }});
      }}
    </script>"""
    return _page(f"Job Application for {title} at {company}", body)


def lever_page(company: str, job_id: str, title: str, flags: dict[str, bool]) -> bytes:
    essay = (
        "<li class='application-question'><div class='application-label'>Why do you want to join us?<span class='required'>✱</span></div>"
        "<div class='application-field'><textarea name='cards[c1][field1]' data-required></textarea></div></li>"
        if flags["essay"]
        else ""
    )
    body = f"""
    <div class="posting-headline"><h2>{html.escape(title)}</h2></div>
    <form onsubmit="return false">
      <ul>
        <li class="application-question"><label>Resume/CV ✱<input type="file" name="resume" id="resume-upload-input" class="vh" data-required></label><span class="filename"></span></li>
        <li class="application-question"><label>Full name ✱<input type="text" name="name" required data-required></label></li>
        <li class="application-question"><label>Email ✱<input type="email" name="email" required data-required></label></li>
        <li class="application-question"><label>Phone ✱<input type="text" name="phone" required data-required></label></li>
        <li class="application-question"><label>Current location<input type="text" name="location" id="location-input"></label></li>
        <li class="application-question"><label>Current company<input type="text" name="org"></label></li>
        <li class="application-question"><label>LinkedIn URL<input type="text" name="urls[LinkedIn]"></label></li>
        <li class="application-question"><label>GitHub URL<input type="text" name="urls[GitHub]"></label></li>
        <li class="application-question"><div class="application-label">Are you willing to work from the office five days a week?<span class="required">✱</span></div>
          <div class="application-field"><ul>
            <li><label><input type="radio" class="vh" name="cards[c0][field0]" value="Yes" required><span class="application-answer-alternative">Yes</span></label></li>
            <li><label><input type="radio" class="vh" name="cards[c0][field0]" value="No"><span class="application-answer-alternative">No</span></label></li>
          </ul></div></li>
        <li class="application-question"><div class="application-label">Which of these have you used?</div>
          <div class="application-field"><ul>
            <li><label><input type="checkbox" name="cards[c0][field2]" value="Python"><span>Python</span></label></li>
            <li><label><input type="checkbox" name="cards[c0][field2]" value="Go"><span>Go</span></label></li>
          </ul></div></li>
        {essay}
      </ul>
      <div id="errors" class="error"></div>
      <button type="button" id="btn-submit" onclick="joSubmit('lever', '{job_id}', {html.escape(json.dumps(flags))}, () => {{ window.location.href = window.location.pathname.replace(/\\/apply$/, '') + '/thanks'; }})">SUBMIT APPLICATION</button>
    </form>
    <script>document.querySelector('[name=resume]').addEventListener('change', e => {{ document.querySelector('.filename').innerText = e.target.files[0].name; }});</script>"""
    return _page(f"{company} - {title}", body)


def ashby_page(company: str, job_id: str, title: str, flags: dict[str, bool]) -> bytes:
    essay_req = "_required_f7cvd_91" if flags["essay"] else ""
    body = f"""
    <h1>{html.escape(title)}</h1>
    <form onsubmit="return false" id="form">
      <div class="ashby-application-form-autofill-pane"><input type="file" class="vh"><button type="button">Upload file</button></div>
      <div class="ashby-application-form-field-entry"><label class="_heading _required_f7cvd_91" for="_systemfield_name">Name</label>
        <input name="_systemfield_name" id="_systemfield_name" type="text" required data-required></div>
      <div class="ashby-application-form-field-entry"><label class="_heading _required_f7cvd_91" for="_systemfield_email">Email</label>
        <input name="_systemfield_email" id="_systemfield_email" type="email" required data-required></div>
      <div class="ashby-application-form-field-entry"><label class="_heading _required_f7cvd_91" for="phone-uuid">Phone number</label>
        <input name="phone-uuid" id="phone-uuid" type="tel" required data-required></div>
      <div class="ashby-application-form-field-entry"><label class="_heading _required_f7cvd_91" for="_systemfield_resume">Resume</label>
        <input id="_systemfield_resume" type="file" class="vh" required data-required><button type="button">Upload File</button></div>
      <div class="ashby-application-form-field-entry" data-q="eligible" data-req="1">
        <label class="_heading _required_f7cvd_91" for="elig-uuid">Are you currently eligible to work in the country to which you are applying?</label>
        <div class="ashby-application-form-input-yesno">
          <button type="button" aria-pressed="false" onclick="joPress(this)">Yes</button><button type="button" aria-pressed="false" onclick="joPress(this)">No</button>
          <input type="checkbox" class="vh" tabindex="-1" name="elig-uuid"></div></div>
      <div class="ashby-application-form-field-entry" data-q="sponsor" data-req="1">
        <label class="_heading _required_f7cvd_91" for="spon-uuid">Do you now or in the future require visa sponsorship?</label>
        <div class="ashby-application-form-input-yesno">
          <button type="button" aria-pressed="false" onclick="joPress(this)">Yes</button><button type="button" aria-pressed="false" onclick="joPress(this)">No</button>
          <input type="checkbox" class="vh" tabindex="-1" name="spon-uuid"></div></div>
      <div class="ashby-application-form-field-entry"><label class="_heading {essay_req}" for="why-uuid">Why do you want to work at {html.escape(company)}?</label>
        <textarea name="why-uuid" id="why-uuid" {"required data-required" if flags["essay"] else ""}></textarea></div>
      <div id="errors" role="alert"></div>
      <button type="submit" onclick="joSubmit('ashby', '{job_id}', {html.escape(json.dumps(flags))}, () => {{ document.getElementById('form').outerHTML = '<h2>Thank you for applying!</h2><p>Your application was successfully submitted.</p>'; }})">Submit Application</button>
    </form>
    <script>function joPress(b) {{ b.parentElement.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); }}</script>"""
    return _page(f"{title} @ {company}", body)


@dataclass
class FormServer:
    """Serves the three forms on loopback and records what is submitted to them."""

    titles: dict[str, str] = field(default_factory=dict)
    received: list[dict[str, Any]] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, provider: str, company: str, job_id: str, title: str, **flags: int) -> str:
        self.titles[job_id] = title
        query = "&".join(f"{key}={value}" for key, value in flags.items())
        path = {
            "greenhouse": f"/greenhouse/{company}/jobs/{job_id}",
            "lever": f"/lever/{company}/{job_id}",
            "ashby": f"/ashby/{company}/{job_id}",
        }[provider]
        return f"{self.base_url}{path}" + (f"?{query}" if query else "")

    def __enter__(self) -> FormServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # silence test output
                return

            def _send(self, status: int, body: bytes, content_type: str = "text/html") -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                parts = urlsplit(self.path)
                flags = _flags(parse_qs(parts.query))
                segments = [s for s in parts.path.split("/") if s]
                if segments[:1] == ["greenhouse"] and len(segments) == 4:
                    company, job_id = segments[1], segments[3]
                    self._send(
                        200,
                        greenhouse_page(
                            company, job_id, owner.titles.get(job_id, "Backend Developer"), flags
                        ),
                    )
                    return
                if segments[:1] == ["greenhouse"] and segments[-1] == "confirmation":
                    self._send(200, _page("Confirmation", "<h1>Thank you for applying.</h1>"))
                    return
                if segments[:1] == ["lever"] and segments[-1] == "apply":
                    company, job_id = segments[1], segments[2]
                    self._send(
                        200,
                        lever_page(
                            company, job_id, owner.titles.get(job_id, "Backend Developer"), flags
                        ),
                    )
                    return
                if segments[:1] == ["lever"] and segments[-1] == "thanks":
                    self._send(
                        200, _page("Application submitted", "<h3>Application submitted!</h3>")
                    )
                    return
                if segments[:1] == ["ashby"] and segments[-1] == "application":
                    company, job_id = segments[1], segments[2]
                    self._send(
                        200,
                        ashby_page(
                            company, job_id, owner.titles.get(job_id, "Backend Developer"), flags
                        ),
                    )
                    return
                self._send(404, _page("Not found", "<h1>Job not found</h1>"))

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                parts = urlsplit(self.path)
                flags = _flags(parse_qs(parts.query))
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                segments = [s for s in parts.path.split("/") if s]
                if flags["reject"]:
                    self._send(
                        200,
                        json.dumps({"ok": False, "error": "Email address is invalid"}).encode(),
                        "application/json",
                    )
                    return
                owner.received.append(
                    {"provider": segments[1], "job_id": segments[2], "fields": payload}
                )
                if flags["silent"]:
                    return  # the request is accepted and nothing ever comes back
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


__all__ = ["FormServer"]
