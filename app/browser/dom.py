"""Read and fill a live application form in the browser.

Everything here runs against a Playwright ``Page`` and is deliberately provider-agnostic:
Greenhouse, Lever and Ashby forms are all read by the same discovery script, which was
written against their real markup:

* **Greenhouse** labels inputs with ``<label for>``, marks required ones with ``*`` and
  renders choice questions as React comboboxes (``role="combobox"``) whose options only
  exist in the DOM while the menu is open.
* **Lever** uses plain named inputs, ``✱`` for required, and ``cards[...]`` radio and
  checkbox groups whose question text sits in a sibling ``.application-label``.
* **Ashby** marks required questions with a ``_required`` class on the label rather than
  an asterisk, and renders yes/no questions as two ``aria-pressed`` buttons beside a
  hidden checkbox.

Every element the script reports is tagged with ``data-jo-field`` (and ``data-jo-option``
for the members of a choice group), so filling addresses exactly the element that was
read. Playwright's CSS engine pierces open shadow roots, so a field inside a shadow DOM is
addressed the same way.

Nothing here solves, dismisses or works around a CAPTCHA. :func:`visible_challenge`
reports one so the caller can hand the tab to the user.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from playwright.sync_api import Locator, Page


@dataclass(frozen=True, slots=True)
class DomField:
    """One question on a live form, as the discovery script found it."""

    index: int
    kind: str
    label: str
    required: bool = False
    options: tuple[str, ...] = ()
    name: str = ""
    accept: str = ""
    max_length: int = 0
    value: str = ""
    #: The question text as the employer wrote it, including any "(optional)" suffix.
    raw_label: str = ""

    @property
    def selector(self) -> str:
        return f'[data-jo-field="{self.index}"]'

    def option_selector(self, option_index: int) -> str:
        return f'[data-jo-field="{self.index}"][data-jo-option="{option_index}"]'


_DISCOVER_JS = r"""
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const stripReq = t => clean(String(t || '').replace(/[*✱]+/g, ' '));
  const isVisible = el => {
    if (!el || !el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const roots = [];
  (function collect(root) {
    roots.push(root);
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) collect(e.shadowRoot); });
  })(document);
  const byId = (root, id) => (root.getElementById ? root.getElementById(id) : null) || document.getElementById(id);
  const labelEl = el => {
    const root = el.getRootNode();
    for (const key of [el.id, el.name]) {
      if (!key) continue;
      const l = root.querySelector('label[for="' + CSS.escape(key) + '"]');
      if (l && clean(l.innerText)) return l;
    }
    return null;
  };
  const isRequiredLabel = l => !!l && (/[*✱]/.test(l.innerText) || /(^|[_\s-])required/i.test(l.className || ''));
  function ownLabel(el) {
    const l = labelEl(el);
    if (l) return l.innerText;
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(i => { const n = byId(el.getRootNode(), i); return n ? n.innerText : ''; }).join(' ');
      if (clean(t)) return t;
    }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const wrap = el.closest('label');
    if (wrap && clean(wrap.innerText)) return wrap.innerText;
    return '';
  }
  function optionText(el) {
    const own = ownLabel(el);
    if (clean(own)) return own;
    const sib = el.nextElementSibling;
    if (sib && clean(sib.innerText)) return sib.innerText;
    return '';
  }
  function containerText(members, optionTexts) {
    let anc = members[0].parentElement;
    while (anc && !members.every(m => anc.contains(m))) anc = anc.parentElement;
    for (let i = 0; anc && i < 4; i++, anc = anc.parentElement) {
      let t = ' ' + clean(anc.innerText) + ' ';
      for (const o of optionTexts) if (o) t = t.split(' ' + o + ' ').join(' ');
      t = clean(t);
      if (t) return t.slice(0, 400);
    }
    return '';
  }
  function groupLabel(members, optionTexts) {
    const first = members[0];
    const entry = first.closest('.ashby-application-form-field-entry, .application-question, .field, [data-field-path]');
    if (entry) {
      const l = entry.querySelector('label, legend, .application-label, [class*="question-title"]');
      if (l && clean(l.innerText) && !optionTexts.includes(clean(l.innerText))) return { text: l.innerText, required: isRequiredLabel(l) };
    }
    const fs = first.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg && clean(lg.innerText)) return { text: lg.innerText, required: isRequiredLabel(lg) }; }
    const g = first.closest('[role=radiogroup],[role=group]');
    if (g && g.getAttribute('aria-label')) return { text: g.getAttribute('aria-label'), required: g.getAttribute('aria-required') === 'true' };
    const l = labelEl(first);
    if (l && !optionTexts.includes(clean(l.innerText))) return { text: l.innerText, required: isRequiredLabel(l) };
    const t = containerText(members, optionTexts);
    return { text: t, required: /[*✱]/.test(t) };
  }

  const fields = [];
  let idx = 0;
  const tag = (el, i, opt) => {
    el.setAttribute('data-jo-field', String(i));
    if (opt !== undefined) el.setAttribute('data-jo-option', String(opt)); else el.removeAttribute('data-jo-option');
  };
  const groups = new Map();
  const handled = new Set();

  // Yes/no and other pressable-button groups (Ashby).
  for (const root of roots) {
    const containers = new Set();
    root.querySelectorAll('button[aria-pressed]').forEach(b => containers.add(b.parentElement));
    containers.forEach(c => {
      if (!c) return;
      const buttons = Array.from(c.querySelectorAll(':scope > button[aria-pressed]')).filter(isVisible);
      if (buttons.length < 2) return;
      const options = buttons.map(b => clean(b.innerText));
      if (options.some(o => !o || o.length > 60)) return;
      c.querySelectorAll('input').forEach(i => handled.add(i));
      const lab = groupLabel(buttons, options);
      const i = idx++;
      buttons.forEach((b, j) => tag(b, i, j));
      fields.push({ index: i, kind: 'buttons', label: stripReq(lab.text), raw_label: clean(lab.text), required: lab.required, options, name: '', accept: '', max_length: 0, value: '' });
    });
  }

  for (const root of roots) {
    root.querySelectorAll('input, select, textarea').forEach(el => {
      if (handled.has(el)) return;
      const type = (el.getAttribute('type') || (el.tagName === 'INPUT' ? 'text' : el.tagName)).toLowerCase();
      if (['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(type)) return;
      if (/^(g-recaptcha-response|h-captcha-response|cf-turnstile-response)/.test(el.name || el.id || '')) return;
      // A dropdown's hidden "required" helper (react-select renders one per required
      // select) and anything hidden from assistive technology is not a question.
      if (/requiredInput/i.test(String(el.className || '')) || el.getAttribute('aria-hidden') === 'true') return;
      if (type === 'radio' || type === 'checkbox') {
        const key = (el.name || el.id || ('anon' + idx)) + (root === document ? '' : '@shadow');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(el);
        return;
      }
      const visible = isVisible(el);
      if (!visible && type !== 'file') return;
      let labelText = ownLabel(el);
      let l = labelEl(el);
      if (!clean(labelText)) {
        // Lever's custom questions put the text in a sibling .application-label, and Ashby's
        // type-ahead inputs carry no id at all; both are labelled by their field entry.
        const entry = el.closest('.application-question, .ashby-application-form-field-entry, [data-field-path], fieldset');
        const heading = entry && entry.querySelector('.application-label, legend, [class*="question-title"], label');
        if (heading && !heading.contains(el) && clean(heading.innerText)) { labelText = heading.innerText; l = heading; }
      }
      // A placeholder is a label only when it says something: "Type here..." does not.
      const placeholder = el.getAttribute('placeholder') || '';
      const usefulPlaceholder = /^(type|start typing|select|search|enter|choose|e\.g|hello@|https?:)/i.test(placeholder.trim()) ? '' : placeholder;
      const raw = labelText || usefulPlaceholder;
      if (!clean(raw) && !el.id && !el.name) return; // a combobox widget's own inner input
      const required = el.required || el.getAttribute('aria-required') === 'true' || /[*✱]/.test(raw) || isRequiredLabel(l);
      let kind = el.tagName === 'SELECT' ? (el.multiple ? 'multiselect' : 'select') : (el.tagName === 'TEXTAREA' ? 'textarea' : type);
      if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') kind = 'combobox';
      let options = [];
      if (el.tagName === 'SELECT') {
        options = Array.from(el.options).map(o => clean(o.text)).filter(t => t && !/^(select|choose|please select|--|—)/i.test(t));
      }
      const i = idx++;
      tag(el, i);
      fields.push({ index: i, kind, label: stripReq(raw), raw_label: clean(raw), required, options, name: el.name || el.id || '', accept: el.getAttribute('accept') || '', max_length: el.maxLength > 0 ? el.maxLength : 0, value: el.value || '' });
    });
  }

  for (const [key, all] of groups) {
    const members = all.filter(m => isVisible(m) || isVisible(m.closest('label')) || isVisible(m.parentElement));
    if (!members.length) continue;
    const type = members[0].type;
    const optionTexts = members.map(m => clean(optionText(m)));
    const lab = groupLabel(members, optionTexts);
    const i = idx++;
    members.forEach((m, j) => tag(m, i, j));
    const single = members.length === 1 && type === 'checkbox';
    let label = stripReq(lab.text);
    if (single) {
      const own = stripReq(optionTexts[0]);
      label = own && label && own.length < 40 && own !== label ? label + ' — ' + own : (own || label);
    }
    const required = members.some(m => m.required || m.getAttribute('aria-required') === 'true') || lab.required || (single && /[*✱]/.test(optionTexts[0]));
    fields.push({ index: i, kind: type === 'radio' ? 'radio' : (single ? 'checkbox' : 'checkbox_group'), label, raw_label: clean(lab.text), required, options: single ? [] : optionTexts.map(stripReq), name: key, accept: '', max_length: 0, value: '' });
  }
  fields.sort((a, b) => a.index - b.index);
  return fields;
}
"""

#: Elements that appear only when a CAPTCHA wants a human. The reCAPTCHA *anchor* and the
#: invisible-badge iframes are present on every Greenhouse and Ashby form and are not a
#: challenge; only the challenge frames ("bframe", hCaptcha's challenge, Turnstile) count,
#: and only when they are actually displayed at a usable size.
_CHALLENGE_JS = r"""
() => {
  const frames = Array.from(document.querySelectorAll('iframe'));
  for (const f of frames) {
    const src = (f.src || '') + ' ' + (f.title || '');
    const isChallenge = /recaptcha\/(api2|enterprise)\/bframe|hcaptcha\.com\/captcha\/v1\/[^ ]*#frame=challenge|challenges\.cloudflare\.com|recaptcha challenge|hcaptcha challenge/i.test(src)
      || (/hcaptcha/i.test(src) && /challenge/i.test(f.title || ''));
    if (!isChallenge) continue;
    const r = f.getBoundingClientRect();
    const s = getComputedStyle(f);
    let parentHidden = false;
    for (let p = f.parentElement; p; p = p.parentElement) {
      const ps = getComputedStyle(p);
      if (ps.visibility === 'hidden' || ps.display === 'none' || ps.opacity === '0') { parentHidden = true; break; }
    }
    if (!parentHidden && s.visibility !== 'hidden' && r.width > 100 && r.height > 100) return 'captcha';
  }
  const text = (document.body ? document.body.innerText : '').toLowerCase();
  if (/verify you are (a )?human|are you a robot|unusual traffic|press and hold/.test(text)) return 'human check';
  return '';
}
"""

_ERRORS_JS = r"""
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const out = new Set();
  document.querySelectorAll('[aria-invalid="true"]').forEach(el => {
    const id = el.getAttribute('aria-describedby');
    const msg = id ? document.getElementById(id.split(/\s+/)[0]) : null;
    out.add(clean(msg ? msg.innerText : (el.name || el.id || 'a field') + ' is invalid'));
  });
  document.querySelectorAll('.error, .error-message, .field-error, [class*="errorMessage"], [class*="_error_"], [role=alert]').forEach(el => {
    const t = clean(el.innerText); if (t && t.length < 200) out.add(t);
  });
  return Array.from(out).filter(Boolean).slice(0, 8);
}
"""

#: Phrases an employer's confirmation page uses. A phrase counts only if it was *not* on
#: the page before Submit was pressed, so a job page that already says "thanks for your
#: interest" cannot be mistaken for a confirmation.
CONFIRMATION_PHRASES: tuple[str, ...] = (
    "thank you for applying",
    "thanks for applying",
    "application has been submitted",
    "application was submitted",
    "application submitted",
    "successfully submitted",
    "we have received your application",
    "we've received your application",
    "we received your application",
    "your application has been received",
    "thank you for your application",
    "thanks for your application",
    "application received",
)

_CONFIRMATION_URL = re.compile(
    r"/(thanks|thank-you|confirmation|confirmed|success|submitted)\b", re.I
)


@dataclass(slots=True)
class Pacing:
    """Randomised pauses between browser actions, so filling proceeds at a human pace."""

    min_ms: int = 350
    max_ms: int = 1100
    _rng: random.Random = field(default_factory=random.Random)

    def pause(self, scale: float = 1.0) -> None:
        if self.max_ms <= 0:
            return
        low = min(self.min_ms, self.max_ms)
        time.sleep(self._rng.uniform(low, self.max_ms) * scale / 1000.0)


def discover_fields(page: Page) -> list[DomField]:
    """Read every question on the current form."""
    raw: list[dict[str, Any]] = page.evaluate(_DISCOVER_JS)
    return [
        DomField(
            index=int(item["index"]),
            kind=str(item["kind"]),
            label=str(item.get("label") or ""),
            raw_label=str(item.get("raw_label") or ""),
            required=bool(item.get("required")),
            options=tuple(str(o) for o in item.get("options") or () if str(o).strip()),
            name=str(item.get("name") or ""),
            accept=str(item.get("accept") or ""),
            max_length=int(item.get("max_length") or 0),
            value=str(item.get("value") or ""),
        )
        for item in raw
    ]


def read_combobox_options(
    page: Page, dom_field: DomField, *, timeout_ms: int = 1500
) -> tuple[str, ...]:
    """Open a combobox, read the choices it offers, and close it again.

    A search-as-you-type box (a city lookup) offers nothing until typed into, which comes
    back empty here and is treated as free text by the caller.
    """
    locator = page.locator(dom_field.selector).first
    try:
        locator.click(timeout=timeout_ms)
        page.wait_for_timeout(350)
        options = _visible_options(page)
    except Exception:  # noqa: BLE001 - an unreadable menu just means "free text"
        options = ()
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
    return options


def _visible_options(page: Page) -> tuple[str, ...]:
    texts: list[str] = page.evaluate(
        r"""() => Array.from(document.querySelectorAll('[role=option], .select__option, .dropdown-results li'))
            .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
            .map(el => (el.innerText || '').replace(/\s+/g, ' ').trim())
            .filter(t => t && !/^no options|^loading/i.test(t))"""
    )
    seen: dict[str, None] = {}
    for text in texts:
        seen.setdefault(text, None)
    return tuple(seen)


def _best_option(wanted: str, options: tuple[str, ...]) -> int:
    lowered = wanted.casefold().strip()
    folded = [option.casefold().strip() for option in options]
    for check in (
        lambda o: o == lowered,
        lambda o: o.startswith(lowered),
        lambda o: lowered in o,
    ):
        for index, option in enumerate(folded):
            if check(option):
                return index
    return -1


def _place_option(wanted: str, options: tuple[str, ...]) -> int:
    """The option a multi-part answer ("Gurgaon, Haryana") refers to, or -1.

    Every part of the answer must appear in the option as a whole word. Matching only the
    first part would happily pick "Gurgaon, Bihar, India" for "Gurgaon, Haryana", and the
    employer would read the wrong state. A single-part answer uses the ordinary match.
    """
    index = _best_option(wanted, options)
    if index >= 0:
        return index
    parts = [part.strip().casefold() for part in wanted.split(",") if part.strip()]
    if len(parts) < 2:
        return -1
    for position, option in enumerate(options):
        text = option.casefold()
        if all(re.search(rf"(?<!\w){re.escape(part)}(?!\w)", text) for part in parts):
            return position
    return -1


class FillError(RuntimeError):
    """A value could not be set, or did not stay set. The form is not submitted."""


def fill_field(page: Page, dom_field: DomField, value: str, pacing: Pacing) -> None:
    """Set one field to ``value`` and confirm the page kept it."""
    kind = dom_field.kind
    locator = page.locator(dom_field.selector).first
    if kind in {"text", "email", "tel", "url", "number", "textarea", "date"}:
        to_type = _numeric(value) if kind == "number" else value
        locator.scroll_into_view_if_needed()
        locator.fill("")
        locator.type(to_type, delay=random.randint(15, 45))
        pacing.pause(0.6)
        _maybe_pick_suggestion(page, dom_field, to_type)
        current = locator.input_value()
        if current.strip() == "" and to_type.strip():
            raise FillError(f"{dom_field.label}: the form cleared the value after typing")
        return
    if kind == "select":
        locator.select_option(label=_match_or_raise(dom_field, value))
        return
    if kind == "multiselect":
        labels = [
            _match_or_raise(dom_field, part.strip()) for part in value.split(";") if part.strip()
        ]
        locator.select_option(label=labels)
        return
    if kind == "combobox":
        _fill_combobox(page, dom_field, value, pacing)
        return
    if kind in {"radio", "buttons"}:
        index = _best_option(value, dom_field.options)
        if index < 0:
            raise FillError(f"{dom_field.label}: {value!r} is not one of {dom_field.options}")
        _click_choice(page, dom_field, index)
        if not _choice_selected(page, dom_field, index):
            raise FillError(f"{dom_field.label}: the choice {value!r} did not stay selected")
        return
    if kind == "checkbox_group":
        for part in [p.strip() for p in value.split(";") if p.strip()]:
            index = _best_option(part, dom_field.options)
            if index < 0:
                raise FillError(f"{dom_field.label}: {part!r} is not one of {dom_field.options}")
            if not _choice_selected(page, dom_field, index):
                _click_choice(page, dom_field, index)
            pacing.pause(0.4)
        return
    raise FillError(f"{dom_field.label}: unsupported field type {kind}")


def set_checkbox(page: Page, dom_field: DomField, checked: bool) -> None:
    """Tick or untick a single checkbox, through its label if the input itself is hidden."""
    if _choice_selected(page, dom_field, 0) == checked:
        return
    _click_choice(page, dom_field, 0)
    if _choice_selected(page, dom_field, 0) != checked:
        raise FillError(f"{dom_field.label}: the tick box did not change")


def upload_file(page: Page, dom_field: DomField, path: str) -> None:
    """Attach a file and wait until the page shows it is attached."""
    locator = page.locator(dom_field.selector).first
    locator.set_input_files(path)
    name = path.rsplit("/", 1)[-1]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        # Many forms swap the file input for a "filename ✕" chip once a file is attached,
        # so the tagged input may be gone; the page text is then the evidence.
        if page.locator(dom_field.selector).count():
            attached = locator.evaluate(
                "(el, name) => { const files = el.files ? Array.from(el.files).map(f => f.name) : [];"
                " return files.includes(name) || (document.body.innerText || '').includes(name); }",
                name,
                timeout=3000,
            )
        else:
            attached = name in page_text(page)
        if attached:
            return
        page.wait_for_timeout(300)
    raise FillError(f"{dom_field.label}: the page never showed {name} as attached")


def _numeric(value: str) -> str:
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        raise FillError(f"{value!r} has no number in it for a numeric field")
    return match.group(0)


def _match_or_raise(dom_field: DomField, value: str) -> str:
    index = _best_option(value, dom_field.options)
    if index < 0:
        raise FillError(f"{dom_field.label}: {value!r} is not one of {dom_field.options}")
    return dom_field.options[index]


def _maybe_pick_suggestion(page: Page, dom_field: DomField, typed: str) -> None:
    """Choose the matching suggestion when a text box turns out to be a lookup (a city)."""
    if not re.search(r"\b(location|city|town)\b", dom_field.label, re.I):
        return
    page.wait_for_timeout(900)
    options = _visible_options(page)
    if not options:
        return
    index = _place_option(typed, options)
    if index < 0:
        if "," in typed:
            # The answer names a region the suggestions do not: refuse rather than send a
            # same-named place somewhere else.
            page.keyboard.press("Escape")
            raise FillError(
                f"{dom_field.label}: none of the suggestions matches {typed!r} "
                f"(offered: {'; '.join(options[:4])}). Save the place exactly as the site names it."
            )
        return
    _click_visible_option(page, options[index])


def _fill_combobox(page: Page, dom_field: DomField, value: str, pacing: Pacing) -> None:
    locator = page.locator(dom_field.selector).first
    locator.scroll_into_view_if_needed()
    locator.click()
    pacing.pause(0.5)
    options = _visible_options(page)
    if not options:
        locator.type(value.split(",")[0], delay=random.randint(20, 50))
        page.wait_for_timeout(1200)
        options = _visible_options(page)
    index = _place_option(value, options) if options else -1
    if index < 0:
        page.keyboard.press("Escape")
        offered = f" (offered: {'; '.join(options[:4])})" if options else ""
        raise FillError(
            f"{dom_field.label}: no choice matching {value!r} was offered{offered}. "
            "Save the answer exactly as the site names it."
        )
    _click_visible_option(page, options[index])
    pacing.pause(0.4)
    shown = locator.evaluate(
        "el => { const box = el.closest('[class*=container], .select, .field') || el.parentElement;"
        " let wide = el; for (let i = 0; i < 4 && wide.parentElement; i++) wide = wide.parentElement;"
        " return [el.value || '', box ? box.innerText : '', wide.innerText.slice(0, 400)].join(' '); }"
    )
    if not _choice_is_shown(options[index], str(shown)):
        raise FillError(f"{dom_field.label}: {options[index]!r} was chosen but is not shown")


def _choice_is_shown(option: str, shown: str) -> bool:
    """Whether the control now displays the chosen option.

    Some pickers show a shortened value: a phone-country picker chooses "India +91" and
    displays a flag and "+91". The full text, or a distinctive part of it (a code such as
    "+91", or a word of three or more letters) appearing as a whole word, confirms it. A
    different choice ("+44" for "+1") does not match, because the match is whole-word.
    """
    text = shown.casefold()
    wanted = option.casefold().strip()
    head = wanted[:20]
    # Whole-word at the start, and at the end too unless the option was cut at 20 chars.
    tail = "" if len(wanted) > 20 else r"(?!\w)"
    if head and re.search(rf"(?<!\w){re.escape(head)}{tail}", text):
        return True
    for token in re.findall(r"[+]?[\w]+", wanted):
        if not (token.startswith("+") or token.isdigit() or len(token) >= 3):
            continue
        if re.search(rf"(?<![\w+]){re.escape(token)}(?!\w)", text):
            return True
    return False


def _click_visible_option(page: Page, text: str) -> None:
    candidates: Locator = page.locator(
        "[role=option], .select__option, .dropdown-results li"
    ).filter(has_text=text)
    count = candidates.count()
    for i in range(count):
        item = candidates.nth(i)
        if item.is_visible() and (item.inner_text() or "").strip() == text:
            item.click()
            return
    if count:
        candidates.first.click()
        return
    raise FillError(f"the choice {text!r} disappeared before it could be clicked")


def _click_choice(page: Page, dom_field: DomField, option_index: int) -> None:
    selector = (
        dom_field.option_selector(option_index)
        if dom_field.kind in {"radio", "buttons", "checkbox_group"}
        else dom_field.selector
    )
    target = page.locator(selector).first
    if dom_field.kind != "buttons" and not target.is_visible():
        # A styled control hides the input; its label is what a person clicks.
        target.evaluate(
            "el => { const root = el.getRootNode(); const l = el.closest('label')"
            " || (el.id && root.querySelector('label[for=\"' + CSS.escape(el.id) + '\"]'));"
            " (l || el).click(); }"
        )
        return
    target.scroll_into_view_if_needed()
    target.click()


def _choice_selected(page: Page, dom_field: DomField, option_index: int) -> bool:
    selector = (
        dom_field.option_selector(option_index)
        if dom_field.kind in {"radio", "buttons", "checkbox_group"}
        else dom_field.selector
    )
    locator = page.locator(selector).first
    if locator.count() == 0:
        return False
    return bool(
        locator.evaluate(
            "el => { if (el.tagName === 'BUTTON') return el.getAttribute('aria-pressed') === 'true'"
            " || el.getAttribute('aria-checked') === 'true' || /selected|active|checked/i.test(el.className);"
            " return !!el.checked; }"
        )
    )


def visible_challenge(page: Page) -> str:
    """Return a description of a CAPTCHA or human check on screen, else an empty string."""
    try:
        return str(page.evaluate(_CHALLENGE_JS) or "")
    except Exception:  # noqa: BLE001 - a navigating page has no challenge to report
        return ""


_VERIFICATION_JS = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  for (const el of document.querySelectorAll('input[autocomplete="one-time-code"]')) {
    if (visible(el)) return 'a one-time-code field';
  }
  const text = (document.body ? document.body.innerText : '').toLowerCase().slice(0, 20000);
  const phrases = [
    'enter the verification code', 'enter the code we sent', 'enter the security code',
    'we sent a code to', 'we have sent a code', 'two-factor authentication',
    '2-step verification', 'two-step verification', 'verify it’s you', "verify it's you",
    'security code sent to your email',
  ];
  for (const phrase of phrases) {
    if (text.includes(phrase)) return phrase;
  }
  return '';
}
"""


def verification_prompt(page: Page) -> str:
    """Describe a visible MFA / verification-code prompt, else return an empty string.

    Such a prompt means the provider wants proof that a person is present (a code sent to
    the user's email or phone). JobOrbit never reads that code from anywhere; the attempt
    is handed to the user.
    """
    try:
        return str(page.evaluate(_VERIFICATION_JS) or "")
    except Exception:  # noqa: BLE001 - a navigating page shows no prompt
        return ""


def page_errors(page: Page) -> list[str]:
    try:
        return [str(item) for item in page.evaluate(_ERRORS_JS)]
    except Exception:  # noqa: BLE001
        return []


def page_text(page: Page) -> str:
    try:
        return str(page.evaluate("() => document.body ? document.body.innerText : ''") or "")
    except Exception:  # noqa: BLE001
        return ""


def present_phrases(text: str) -> set[str]:
    lowered = text.casefold()
    return {phrase for phrase in CONFIRMATION_PHRASES if phrase in lowered}


def looks_confirmed(before_url: str, before_phrases: set[str], page: Page) -> str:
    """Return the evidence that the employer acknowledged the application, else ''.

    Two independent signals qualify: a confirmation phrase that was not on the page before
    Submit, or a navigation to a confirmation URL. Either alone counts; neither means the
    application is *not* confirmed — which is reported as such, never assumed.
    """
    url = page.url
    new_phrases = present_phrases(page_text(page)) - before_phrases
    if new_phrases:
        return f"the page now reads {sorted(new_phrases)[0]!r}"
    if url != before_url and _CONFIRMATION_URL.search(url.split("?", 1)[0]):
        return f"the employer redirected to its confirmation page ({url})"
    return ""


def submit_button(page: Page) -> Locator | None:
    """The form's own submit control: visible, labelled submit or apply."""
    candidates = page.locator(
        "button[type=submit], input[type=submit], button:has-text('Submit'), button:has-text('Apply')"
    )
    best: Locator | None = None
    for i in range(candidates.count()):
        item = candidates.nth(i)
        try:
            if not item.is_visible():
                continue
            text = (item.inner_text() or item.get_attribute("value") or "").strip().casefold()
        except Exception:  # noqa: BLE001
            continue
        if re.search(r"\bsubmit\b", text) and "upload" not in text:
            return item
        if best is None and re.search(r"\bapply\b", text):
            best = item
    return best


_NORMALISE = re.compile(r"[^a-z0-9+#]+")


def _tokens(text: str) -> list[str]:
    return [token for token in _NORMALISE.split(text.casefold()) if token]


def identity_problem(page: Page, *, title: str, company: str) -> str:
    """Return why the open page is not the queued job, or '' when it is.

    The title check needs every significant word of the queued title on the page heading
    or document title. The company check accepts the company name in the page title,
    heading, or the board slug in the URL. Both must pass, because applying to the wrong
    job — whatever happened to be open — is exactly the failure this guards against.
    """
    heading = page.evaluate(
        "() => [document.title, ...Array.from(document.querySelectorAll('h1, h2')).slice(0, 4)"
        ".map(h => h.innerText)].join(' \\n ')"
    )
    haystack = set(_tokens(str(heading)))
    wanted = [token for token in _tokens(title) if len(token) > 1 or token in {"c", "r"}]
    missing = [token for token in wanted if token not in haystack]
    if wanted and len(missing) > max(0, len(wanted) // 5):
        return (
            f"the open page does not show the queued title {title!r} "
            f"(missing: {', '.join(missing[:4])})"
        )
    generic = {
        "inc",
        "ltd",
        "llc",
        "pvt",
        "private",
        "limited",
        "technologies",
        "the",
        "ai",
        "labs",
        "co",
        "corp",
        "group",
        "hq",
        "io",
    }
    company_tokens = [token for token in _tokens(company) if token not in generic] or _tokens(
        company
    )
    url_tokens = set(_tokens(page.url))
    principal = max(company_tokens, key=len) if company_tokens else ""
    if principal and not (
        principal in haystack
        or principal in url_tokens
        or "".join(company_tokens) in page.url.casefold().replace("-", "")
    ):
        return f"the open page does not name the queued company {company!r}"
    return ""


__all__ = [
    "CONFIRMATION_PHRASES",
    "DomField",
    "FillError",
    "Pacing",
    "discover_fields",
    "fill_field",
    "identity_problem",
    "looks_confirmed",
    "page_errors",
    "page_text",
    "present_phrases",
    "read_combobox_options",
    "set_checkbox",
    "submit_button",
    "upload_file",
    "visible_challenge",
]
