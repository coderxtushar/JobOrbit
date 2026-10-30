# Design System

Derived from reviewing job-board, applicant-dashboard and resume-matching design work on
Dribbble (searches: `job-board-dashboard`, `job-match-score`, `resume-skills-match-ui`,
reviewed 2026-10-28). What follows is a set of **patterns and tokens**, not copied assets:
no image, icon, logo or proprietary artwork from any shot is used.

## What the research actually showed

Seven job-board/ATS dashboards and several resume-matcher panels were examined. The
recurring conventions worth adopting:

| Pattern | Where it appeared | Adopted as |
|---|---|---|
| Dark full-height sidebar + light canvas | "Hirely" applicant dashboard (`#070B1C` rail, `#FAF9F6` canvas) | Dark sidebar, `#F7F8FC` canvas |
| Indigo/violet as the "AI matching" accent | AI Résumé Matcher (`#5146E5`), Matchr (`#6D65C8`), Top Job Matched pills (`#6555C7`) | Primary `#5146E5` |
| **Circular ring with the number inside** | AI Matcher overall match "82"; Career Rank "78/100"; Matchr "86/100" | The match-score ring on every job card |
| **Per-category horizontal bars with right-aligned numerals** | AI Matcher breakdown: Skills / Experience / Portfolio / Keywords / Confidence | The six-category score breakdown |
| Pale pill + word label for score band | "94% · Strong Match", "87% · Good Match" | high / worth a look / low band pills |
| Tinted KPI cards with large numerals | BERKARIR.ID metric cards, Hirely summary row | Overview and tracker metric cards |
| Company mark as a small coloured circle starting a row | Hirely and BERKARIR.ID listing rows | Monogram tile from the company initial |
| Cards: 10-14px radius, soft shadow, no heavy border, generous padding | Majority of light dashboards | `--radius-lg: 14px`, `--shadow-card` |
| Strong weight contrast: bold dark title, small pale-grey metadata | Every shot reviewed | `--text` vs `--text-muted` |
| Compact pale pills for filters/tags | "Find Matching Jobs" filter chips, résumé skill tags | Skill pills |

### Two deliberate deviations

**1. Missing skills are amber, never red.** Across the shots, missing skills were either
shown with the same styling as present ones or with checked indigo boxes — and none used an
error colour. This application must not either, for a stronger reason: a skill absent from
the user's profile is a gap *in the profile*, not evidence the user lacks the skill. Red
reads as "you failed". Amber reads as "worth your attention", which is what is true.

**2. No match score is invented where none can be computed.** Several shots show a score on
every card unconditionally. Here, an unscored job shows a hollow ring and the word
"Unscored", and a category that could not be assessed renders a hatched/empty track
labelled "not assessable" rather than a zero-width bar that reads as 0%.

## Tokens

```
--indigo-600  #5146E5   primary: score ring, active nav, primary buttons
--indigo-500  #6D65C8   secondary arcs, category bars
--indigo-100  #E8E3FA   pill fills, bar tracks
--indigo-050  #F2EFFC   hover surfaces

--green-600   #1F9D63   high band, matched skills text
--green-100   #DDF4E5   high band pill, matched skill pills
--amber-600   #9A6400   caution text, missing-skill text
--amber-100   #FDF0D5   missing-skill pills, "worth a look" band
--slate-600   #5A6475   low band text
--slate-100   #EEF0F4   neutral pills, tracks

--canvas      #F7F8FC   app background
--surface     #FFFFFF   cards
--sidebar     #0E1222   dark navigation rail
--border      #E6E9F0   hairlines only, never a heavy outline
--text        #141A2B   titles, numerals
--text-muted  #6B7486   metadata, captions

--radius-sm   8px     pills, buttons
--radius-lg   14px    cards
--shadow-card 0 1px 2px rgba(20,26,43,.04), 0 4px 16px rgba(20,26,43,.06)
--shadow-hover 0 2px 4px rgba(20,26,43,.06), 0 12px 28px rgba(20,26,43,.10)
```

Band → colour mapping, used consistently everywhere a score appears:

| Band | Score | Ring / pill |
|---|---|---|
| high | 80-100 | `--green-600` on `--green-100` |
| worth a look | 65-79 | `--amber-600` on `--amber-100` |
| low | < 65 | `--slate-600` on `--slate-100` |
| unscored | n/a | hollow ring, `--text-muted`, label "Unscored" |

## Component anatomy

### Score ring
Inline SVG, 56px, 5px stroke, rotated -90° so the arc starts at twelve o'clock. Track in
the band's pale tint, arc in the band's solid colour, numeral centred at 17px/700. Beneath
it, the band word at 11px uppercase with 0.04em tracking. An unscored job renders the full
track with no arc and an en-dash in place of the numeral.

### Job card
```
┌──────────────────────────────────────────────────────────────┐
│ ┌────┐  Backend Developer (Python)              ╭───────╮    │
│ │ AC │  Acme Technologies · Bengaluru           │  97   │    │
│ └────┘  [hybrid] [full-time]                    ╰───────╯    │
│         Posted 26 Oct (approx) · Discovered 28 Oct            │
│         Sources: linkedin, naukri · seen on 2 platforms       │
│                                                               │
│         You have      ● python ● fastapi ● postgresql         │
│         Not in profile  ○ llm                                 │
│                                                               │
│         [Shortlist] [Skip] [Details] [Prepare]  [Open ↗]      │
│         ▸ Why this score                                      │
└──────────────────────────────────────────────────────────────┘
```
Monogram tile is 44px, `--radius-sm`, background derived from a hash of the company name so
the same employer keeps the same colour across sessions. Hover raises the card to
`--shadow-hover` with a 120ms transition.

### Category breakdown
One row per scoring category: label at 12px muted, a 6px-high rounded track, and the score
right-aligned at 12px/600 tabular. Assessable categories fill the track proportionally in
`--indigo-500`; unassessable ones show an empty track with the note "not assessable" in
place of the numeral, so a missing posting date never looks like a score of zero.

### Metric card
Tinted surface, label at 11px uppercase muted, value at 28px/700, optional caption at 11px.
Counted facts use `--indigo-050`; estimates use `--amber-100` so the Overview page's
"Estimates" section stays visually distinct from counted facts.

### Provenance badge
Small pill, 11px. `profile_verified` green, `resume_extracted` indigo, `ai_draft` amber,
`user_entered` slate, `needs_user_input` amber with a 1px amber border for extra weight.

## Accessibility and honesty constraints

- All body text ≥ 12px; muted text only for genuinely secondary metadata.
- Every band is distinguished by its *word* as well as its colour, so the ring is never the
  only carrier of meaning.
- Colour never contradicts copy. The "not in your profile" wording stays exactly as written
  regardless of styling.
- The no-auto-submit notice, the provenance badges and the counted-vs-estimated split keep
  their existing text. Styling may change; wording may not.
