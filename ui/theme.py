"""Visual theme: design tokens, global CSS, and HTML component builders.

Implements the design system in ``docs/DESIGN.md``, derived from reviewing job-board and
resume-matcher UI work. Two rules from that document are enforced here in code rather than
left to call sites:

* A missing skill renders amber, never red. It marks a gap in the profile, not a judgement
  about the person.
* An absent score renders as a hollow ring labelled "Unscored", and an unassessable
  category renders as an empty track labelled "not assessable" — never a 0% arc or a
  zero-width bar, which would read as a real score of zero.

Every value interpolated into HTML here passes through :func:`esc`. Job titles, company
names and skills originate in imported files and are untrusted input.
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------------------

INDIGO_600 = "#5146E5"
INDIGO_500 = "#6D65C8"
INDIGO_100 = "#E8E3FA"
INDIGO_050 = "#F2EFFC"

GREEN_600 = "#1F9D63"
GREEN_100 = "#DDF4E5"
AMBER_600 = "#9A6400"
AMBER_100 = "#FDF0D5"
SLATE_600 = "#5A6475"
SLATE_100 = "#EEF0F4"

CANVAS = "#F7F8FC"
SURFACE = "#FFFFFF"
SIDEBAR = "#0E1222"
BORDER = "#E6E9F0"
TEXT = "#141A2B"
TEXT_MUTED = "#6B7486"

RADIUS_SM = "8px"
RADIUS_LG = "14px"

#: band -> (label, solid colour, pale fill). The label carries the meaning so colour is
#: never the only signal, which keeps the ring readable without colour vision.
BANDS: dict[str, tuple[str, str, str]] = {
    "high": ("High match", GREEN_600, GREEN_100),
    "review": ("Worth a look", AMBER_600, AMBER_100),
    "low": ("Low match", SLATE_600, SLATE_100),
}
UNSCORED = ("Unscored", TEXT_MUTED, SLATE_100)

#: confidence label -> tone. Low confidence is slate, not red: it means the listing did not
#: say enough to judge, which is a statement about the evidence rather than about the job or
#: the candidate. The word is always rendered beside the colour, so the colour never carries
#: the meaning alone.
CONFIDENCE_TONES: dict[str, str] = {"high": "green", "medium": "amber", "low": "slate"}

#: Monogram tile palette. A company always gets the same colour because the index is a
#: hash of its name, so the feed stays visually stable between runs.
MONOGRAM_COLOURS: tuple[tuple[str, str], ...] = (
    ("#E8E3FA", "#4A3FD0"),
    ("#DDF4E5", "#15794B"),
    ("#FDF0D5", "#8A5A00"),
    ("#D9EDFB", "#1A6397"),
    ("#FBE2EF", "#A22E6B"),
    ("#E2F4F1", "#13746B"),
    ("#EEF0F4", "#48515F"),
)

TONES: dict[str, tuple[str, str]] = {
    "indigo": (INDIGO_100, "#3C32B0"),
    "green": (GREEN_100, "#146A42"),
    "amber": (AMBER_100, "#7A4F00"),
    "slate": (SLATE_100, "#4A5260"),
    "outline": ("transparent", TEXT_MUTED),
}


def esc(value: Any) -> str:
    """HTML-escape any value before it is interpolated into markup."""
    return escape(str(value if value is not None else ""), quote=True)


_CSS = f"""
<style>
:root {{
  --indigo-600:{INDIGO_600}; --indigo-500:{INDIGO_500}; --indigo-100:{INDIGO_100};
  --indigo-050:{INDIGO_050}; --green-600:{GREEN_600}; --green-100:{GREEN_100};
  --amber-600:{AMBER_600}; --amber-100:{AMBER_100}; --slate-600:{SLATE_600};
  --slate-100:{SLATE_100}; --canvas:{CANVAS}; --surface:{SURFACE};
  --border:{BORDER}; --text:{TEXT}; --text-muted:{TEXT_MUTED};
  --radius-sm:{RADIUS_SM}; --radius-lg:{RADIUS_LG};
  --shadow-card:0 1px 2px rgba(20,26,43,.04), 0 4px 16px rgba(20,26,43,.06);
  --shadow-hover:0 2px 4px rgba(20,26,43,.06), 0 12px 28px rgba(20,26,43,.10);
}}

.stApp {{ background:var(--canvas); }}
.block-container {{ padding-top:2.1rem; max-width:1280px; }}

h1 {{ font-size:1.72rem !important; font-weight:700 !important; letter-spacing:-.02em;
      color:var(--text); margin-bottom:.15rem !important; }}
h2 {{ font-size:1.22rem !important; font-weight:650 !important; letter-spacing:-.01em; }}
h3 {{ font-size:1.05rem !important; font-weight:650 !important; }}
h4 {{ font-size:.97rem !important; font-weight:650 !important; letter-spacing:-.005em; }}

/* Dark navigation rail, per the Hirely pattern in docs/DESIGN.md. */
section[data-testid="stSidebar"] {{ background:{SIDEBAR}; width:267px !important; }}
section[data-testid="stSidebar"] * {{ color:#E8EAF2; }}
section[data-testid="stSidebar"] h1 {{ color:#FFF !important; font-size:1.1rem !important; }}
.ja-brand {{
  color:#FFF; font-size:1.12rem; font-weight:700; letter-spacing:-.015em;
  padding:.1rem 0 .1rem; line-height:1.3;
}}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color:#A6AEC2 !important; }}
section[data-testid="stSidebar"] code {{
  background:#1C2338; color:#C9D1E6; font-size:.74rem; padding:1px 6px;
  border-radius:5px;
}}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ font-size:.82rem; }}
section[data-testid="stSidebar"] hr {{ border-color:#222842; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap:1px; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
  padding:.44rem .6rem; border-radius:var(--radius-sm); transition:background 120ms ease;
}}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background:#1A2039; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background:var(--indigo-600);
}}
section[data-testid="stSidebar"] [role="radiogroup"] label p {{
  font-size:.87rem; font-weight:500;
}}
section[data-testid="stSidebar"] [role="radiogroup"] div[data-baseweb="radio"] div:first-child {{
  display:none;
}}
section[data-testid="stSidebar"] [data-testid="stAlert"] {{
  background:#171D33; border:1px solid #242B48;
}}
section[data-testid="stSidebar"] [data-testid="stAlert"] p {{ color:#B9C0D4 !important; font-size:.78rem; }}

/* Cards. The anchor is matched as a descendant, not a direct child: Streamlit wraps every
   element in two extra divs, so a `> div > div` path never matches and the shadow silently
   never applies. The anchor's own container is collapsed so it costs no vertical space. */
[data-testid="stElementContainer"]:has(.ja-card-anchor) {{ display:none !important; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ja-card-anchor) {{
  background:var(--surface); border:1px solid var(--border) !important;
  border-radius:var(--radius-lg) !important; box-shadow:var(--shadow-card);
  transition:box-shadow 130ms ease, transform 130ms ease, border-color 130ms ease;
}}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ja-card-anchor):hover {{
  box-shadow:var(--shadow-hover); transform:translateY(-1px); border-color:#D5D9E4 !important;
}}

.ja-row {{ display:flex; align-items:flex-start; gap:.8rem; }}
.ja-mono {{
  width:44px; height:44px; min-width:44px; border-radius:var(--radius-sm);
  display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:.95rem; letter-spacing:-.01em;
}}
.ja-title {{ font-size:1.01rem; font-weight:650; color:var(--text); line-height:1.3;
             letter-spacing:-.01em; margin:0; }}
.ja-sub {{ font-size:.84rem; color:var(--text-muted); margin:.14rem 0 .3rem; }}
.ja-meta {{ font-size:.795rem; color:#5F6878; line-height:1.6; margin:.3rem 0 0; }}
.ja-meta strong {{ color:var(--indigo-600); font-weight:650; }}

.ja-pill {{
  display:inline-block; padding:2px 9px; border-radius:999px;
  font-size:.715rem; font-weight:550; margin:0 4px 4px 0; line-height:1.5;
  white-space:nowrap;
}}
.ja-pill-outline {{ border:1px solid var(--border); }}
.ja-skillrow {{ display:flex; align-items:baseline; gap:.5rem; margin:.3rem 0 0; flex-wrap:wrap; }}
.ja-skilllabel {{
  font-size:.7rem; font-weight:600; text-transform:uppercase; letter-spacing:.045em;
  color:var(--text-muted); min-width:92px;
}}
.ja-none {{ font-size:.75rem; color:var(--text-muted); font-style:italic; }}

/* Score ring */
.ja-ring {{ display:flex; flex-direction:column; align-items:center; gap:.18rem; }}
.ja-ring-band {{
  font-size:.665rem; font-weight:650; text-transform:uppercase; letter-spacing:.045em;
  text-align:center; line-height:1.2;
}}

/* Category bars. The track and fill are <span> elements, so they MUST be made block-level:
   an inline element ignores width percentages and height, which renders the fill as an
   invisible zero-height sliver and silently destroys the score breakdown. */
.ja-cat {{ display:grid; grid-template-columns:118px 1fr 84px; align-items:center;
           gap:.65rem; margin:.34rem 0; }}
.ja-cat-label {{ font-size:.8rem; color:var(--text); font-weight:550;
                 text-transform:capitalize; }}
.ja-cat-track {{ display:block; width:100%; height:8px; border-radius:999px;
                 background:#E4E7EE; overflow:hidden; }}
.ja-cat-fill {{ display:block; height:8px; border-radius:999px;
                background:linear-gradient(90deg,var(--indigo-500),var(--indigo-600)); }}
.ja-cat-val {{ font-size:.775rem; font-weight:650; text-align:right;
               font-variant-numeric:tabular-nums; color:var(--text); }}
.ja-cat-na {{ font-size:.73rem; color:var(--amber-600); text-align:right;
              font-style:italic; font-weight:550; }}
.ja-cat-track-na {{
  display:block; width:100%; height:8px; border-radius:999px;
  background:repeating-linear-gradient(135deg,#E4E7EE 0 5px,#F4F6F9 5px 10px);
}}
.ja-cat-detail {{ grid-column:1 / -1; font-size:.745rem; color:#5F6878;
                  margin:-.1rem 0 .34rem; line-height:1.5; }}

/* Evidence / confidence block */
.ja-ev {{ margin:.35rem 0 .1rem; }}
.ja-ev-head {{
  font-size:.7rem; font-weight:600; text-transform:uppercase; letter-spacing:.045em;
  color:var(--text-muted); margin:.45rem 0 .18rem;
}}
.ja-ev-list {{ margin:0; padding-left:1.05rem; }}
.ja-ev-list li {{ font-size:.785rem; color:#5F6878; line-height:1.55; margin:.06rem 0; }}
.ja-ev-bar {{
  display:block; width:100%; height:6px; border-radius:999px; background:#E4E7EE;
  overflow:hidden; margin:.2rem 0 .1rem;
}}
.ja-ev-bar-fill {{ display:block; height:6px; border-radius:999px; }}

/* Metric cards */
.ja-metric {{
  background:var(--indigo-050); border:1px solid var(--border);
  border-radius:var(--radius-lg); padding:.72rem .85rem; height:100%;
}}
.ja-metric-est {{ background:var(--amber-100); border-color:#F2E2BE; }}
.ja-metric-label {{
  font-size:.665rem; font-weight:650; text-transform:uppercase; letter-spacing:.05em;
  color:var(--text-muted);
}}
.ja-metric-value {{ font-size:1.72rem; font-weight:700; color:var(--text);
                    line-height:1.18; letter-spacing:-.02em;
                    font-variant-numeric:tabular-nums; }}
.ja-metric-cap {{ font-size:.69rem; color:var(--text-muted); line-height:1.4; }}

/* Section headers */
.ja-sect {{ margin:.2rem 0 .6rem; }}
.ja-sect-title {{ font-size:1.07rem; font-weight:650; color:var(--text);
                  letter-spacing:-.01em; }}
.ja-sect-sub {{ font-size:.8rem; color:var(--text-muted); margin-top:.08rem; }}

/* Controls */
.stButton > button, .stLinkButton > a, .stDownloadButton > button {{
  border-radius:var(--radius-sm); font-size:.825rem; font-weight:550;
  border:1px solid var(--border); transition:all 110ms ease; min-height:2.3rem;
}}
.stButton > button:hover, .stLinkButton > a:hover {{
  border-color:var(--indigo-600); color:var(--indigo-600); background:var(--indigo-050);
}}
.stButton > button[kind="primary"] {{
  background:var(--indigo-600); border-color:var(--indigo-600); color:#FFF;
}}
.stButton > button[kind="primary"]:hover {{
  background:#4238C9; border-color:#4238C9; color:#FFF;
}}

[data-testid="stExpander"] {{ border:none !important; }}
[data-testid="stExpander"] details {{
  border:1px solid var(--border); border-radius:var(--radius-sm);
  background:#FCFCFE;
}}
[data-testid="stExpander"] summary {{ font-size:.82rem; font-weight:550; }}

[data-testid="stAlert"] {{ border-radius:var(--radius-sm); font-size:.845rem; }}
[data-testid="stTabs"] button {{ font-size:.86rem; font-weight:550; }}
[data-testid="stDataFrame"] {{ border-radius:var(--radius-sm); overflow:hidden;
                               border:1px solid var(--border); }}
[data-testid="stForm"] {{ border:1px solid var(--border); border-radius:var(--radius-lg);
                          background:var(--surface); padding:1rem 1.1rem; }}
hr {{ margin:1.05rem 0; border-color:var(--border); }}
#MainMenu, footer {{ visibility:hidden; }}
</style>
"""


def inject_css() -> None:
    """Install the global stylesheet. Call once per page render."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------------------


def band_parts(band: str, score: float | None) -> tuple[str, str, str]:
    """Return (label, solid, pale) for a band, falling back to the unscored treatment."""
    if score is None:
        return UNSCORED
    return BANDS.get(band, UNSCORED)


def score_ring(score: float | None, band: str = "", size: int = 56) -> str:
    """An SVG progress ring with the score inside.

    ``score=None`` draws the full track with no arc and an en-dash, so an unscored job is
    visibly different from a job that genuinely scored zero.
    """
    label, solid, pale = band_parts(band, score)
    radius = (size - 5) / 2
    circumference = 2 * 3.141592653589793 * radius
    fraction = 0.0 if score is None else max(0.0, min(float(score), 100.0)) / 100.0
    centre = size / 2

    arc = ""
    if fraction > 0:
        arc = (
            f'<circle cx="{centre}" cy="{centre}" r="{radius:.2f}" fill="none" '
            f'stroke="{solid}" stroke-width="5" stroke-linecap="round" '
            f'stroke-dasharray="{circumference:.2f}" '
            f'stroke-dashoffset="{circumference * (1 - fraction):.2f}" '
            f'transform="rotate(-90 {centre} {centre})"/>'
        )

    numeral = "–" if score is None else f"{round(float(score)):g}"
    return (
        f'<div class="ja-ring">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="match score {esc(numeral)} out of 100, {esc(label)}">'
        f'<circle cx="{centre}" cy="{centre}" r="{radius:.2f}" fill="none" '
        f'stroke="{pale}" stroke-width="5"/>{arc}'
        f'<text x="{centre}" y="{centre}" text-anchor="middle" dominant-baseline="central" '
        f'font-size="17" font-weight="700" fill="{solid}">{esc(numeral)}</text></svg>'
        f'<div class="ja-ring-band" style="color:{solid}">{esc(label)}</div>'
        f"</div>"
    )


def monogram(company: str) -> str:
    """A coloured initial tile standing in for a company logo."""
    name = (company or "?").strip()
    initials = "".join(part[0] for part in name.split()[:2] if part).upper() or "?"
    digest = hashlib.sha256(name.lower().encode("utf-8")).digest()[0]
    background, foreground = MONOGRAM_COLOURS[digest % len(MONOGRAM_COLOURS)]
    return (
        f'<div class="ja-mono" style="background:{background};color:{foreground}" '
        f'title="{esc(name)}">{esc(initials)}</div>'
    )


def pill(text: str, tone: str = "slate") -> str:
    background, colour = TONES.get(tone, TONES["slate"])
    extra = " ja-pill-outline" if tone == "outline" else ""
    return (
        f'<span class="ja-pill{extra}" style="background:{background};color:{colour}">'
        f"{esc(text)}</span>"
    )


def pills(items: list[str], tone: str = "slate", limit: int = 14) -> str:
    if not items:
        return '<span class="ja-none">none</span>'
    return "".join(pill(item, tone) for item in items[:limit])


def skill_row(label: str, items: list[str], tone: str) -> str:
    return (
        f'<div class="ja-skillrow"><span class="ja-skilllabel">{esc(label)}</span>'
        f"<span>{pills(items, tone)}</span></div>"
    )


def category_bars(category_scores: dict[str, Any], show_detail: bool = True) -> str:
    """Per-category breakdown: label, proportional bar, right-aligned value.

    An unassessable category gets a hatched empty track and the words "not assessable"
    instead of a numeral, because a zero-width bar would read as a score of zero.
    """
    if not category_scores:
        return '<div class="ja-none">No category scores are available.</div>'

    rows: list[str] = []
    for name, data in category_scores.items():
        if not isinstance(data, dict):
            continue
        assessable = bool(data.get("assessable", True))
        label = esc(str(name).replace("_", " "))
        detail = esc(data.get("detail", "")) if show_detail else ""

        if assessable:
            value = float(data.get("score") or 0.0)
            weight = float(data.get("weight") or 0.0) * 100
            width = max(0.0, min(value, 100.0))
            rows.append(
                f'<div class="ja-cat"><span class="ja-cat-label">{label}</span>'
                f'<span class="ja-cat-track"><span class="ja-cat-fill" '
                f'style="width:{width:.1f}%"></span></span>'
                f'<span class="ja-cat-val">{value:g} · {weight:.0f}%</span>'
            )
        else:
            rows.append(
                f'<div class="ja-cat"><span class="ja-cat-label">{label}</span>'
                f'<span class="ja-cat-track-na"></span>'
                f'<span class="ja-cat-na">not assessable</span>'
            )
        if detail:
            rows.append(f'<span class="ja-cat-detail">{detail}</span>')
        rows.append("</div>")
    return "".join(rows)


def confidence_badge(confidence: str, coverage: float | None = None) -> str:
    """A pill naming the confidence level, with the share of weight that was assessable."""
    key = str(confidence or "").strip().lower()
    tone = CONFIDENCE_TONES.get(key, "slate")
    text = f"{key.title() or 'Unknown'} confidence"
    if coverage is not None:
        text += f" · {float(coverage) * 100:.0f}% evidence"
    return pill(text, tone)


def coverage_bar(coverage: float | None, confidence: str = "") -> str:
    """A thin bar showing how much of the scoring weight the listing supported."""
    if coverage is None:
        return ""
    tone = CONFIDENCE_TONES.get(str(confidence or "").strip().lower(), "slate")
    _background, colour = TONES.get(tone, TONES["slate"])
    width = max(0.0, min(float(coverage) * 100, 100.0))
    return (
        f'<span class="ja-ev-bar"><span class="ja-ev-bar-fill" '
        f'style="width:{width:.1f}%;background:{colour}"></span></span>'
    )


def unassessable_fields(category_scores: dict[str, Any]) -> list[str]:
    """Name the categories the listing left unjudgeable, with the stated reason."""
    missing: list[str] = []
    for name, data in (category_scores or {}).items():
        if not isinstance(data, dict) or data.get("assessable", True):
            continue
        label = str(name).replace("_", " ")
        detail = str(data.get("detail") or "").strip()
        missing.append(f"{label} — {detail}" if detail else label)
    return missing


def evidence_block(match: dict[str, Any]) -> str:
    """Why the confidence label is what it is, and what the listing did not say.

    Rendered separately from the score so the two are never read as one number: the score
    answers "how relevant", this answers "how much was there to go on".
    """
    if not match:
        return ""
    coverage = match.get("evidence_coverage")
    parts = [
        '<div class="ja-ev">',
        confidence_badge(match.get("confidence", ""), coverage),
        coverage_bar(coverage, match.get("confidence", "")),
    ]

    reasons = [str(reason) for reason in (match.get("confidence_reasons") or [])]
    if reasons:
        parts.append(
            '<div class="ja-ev-head">Why this confidence level</div><ul class="ja-ev-list">'
        )
        parts.extend(f"<li>{esc(reason)}</li>" for reason in reasons)
        parts.append("</ul>")
    else:
        parts.append(
            '<div class="ja-ev-list"><li>Every scoring category could be assessed from '
            "this listing.</li></div>"
        )

    missing = unassessable_fields(match.get("category_scores") or {})
    if missing:
        parts.append(
            '<div class="ja-ev-head">Information this listing did not provide</div>'
            '<ul class="ja-ev-list">'
        )
        parts.extend(f"<li>{esc(item)}</li>" for item in missing)
        parts.append("</ul>")

    uncertain = [str(item) for item in (match.get("uncertain_requirements") or [])]
    if uncertain:
        parts.append(
            '<div class="ja-ev-head">Uncertain fields</div><ul class="ja-ev-list">'
            f"<li>These skills were inferred from the description, not stated by the "
            f"employer: {esc(', '.join(uncertain))}.</li></ul>"
        )

    parts.append("</div>")
    return "".join(parts)


def metric_card(label: str, value: Any, caption: str = "", kind: str = "counted") -> str:
    """A tinted KPI card. ``kind='estimated'`` tints amber to separate it from counts."""
    css_class = "ja-metric ja-metric-est" if kind == "estimated" else "ja-metric"
    caption_html = f'<div class="ja-metric-cap">{esc(caption)}</div>' if caption else ""
    return (
        f'<div class="{css_class}"><div class="ja-metric-label">{esc(label)}</div>'
        f'<div class="ja-metric-value">{esc(value)}</div>{caption_html}</div>'
    )


def section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = f'<div class="ja-sect-sub">{esc(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="ja-sect"><div class="ja-sect-title">{esc(title)}</div>{subtitle_html}</div>',
        unsafe_allow_html=True,
    )


def card_anchor() -> None:
    """Marker element the card CSS selector hooks onto.

    Streamlit gives containers no stable class, so the stylesheet targets a bordered
    wrapper that contains this anchor. Without it, every container on the page would pick
    up card styling.
    """
    st.markdown('<span class="ja-card-anchor"></span>', unsafe_allow_html=True)
