"""Compensation normalisation.

A listing says "12-18 LPA", "₹80k/month" or "USD 120k-150k"; a screening question asks for
"Expected CTC (in LPA)" or "monthly salary expectation in INR". Comparing or answering
across those requires arithmetic, and arithmetic on salary text is where invented facts
creep in: a bare "15" read as fifteen rupees, a monthly figure compared with an annual
one, a dollar amount silently priced at some exchange rate nobody configured.

So every step here is recorded. :class:`Compensation` keeps the verbatim text next to the
parsed values, and ``assumptions`` spells out each conversion that produced a number
("monthly × 12", "USD→INR at configured rate 83.2"). Nothing is filled in that the text
does not state: "Not disclosed" and "competitive" come back ``disclosed=False`` with no
numbers, and a USD figure is never shown in INR unless ``usd_inr_rate`` is configured.

:func:`format_for_unit` turns a parsed figure into the unit a form asks for. Its result is
a *proposal*: ``exact`` is ``False`` whenever any conversion happened, and the form filler
must get the user's approval before typing a converted value.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

#: The units :func:`detect_question_unit` can recognise and :func:`format_for_unit` emits.
QuestionUnit = Literal["lpa", "inr_annual", "inr_monthly", "usd_annual"]
QUESTION_UNITS: tuple[str, ...] = ("lpa", "inr_annual", "inr_monthly", "usd_annual")

Period = Literal["annual", "monthly", "hourly"]
SalaryKind = Literal["current", "expected"]
Pick = Literal["minimum", "maximum", "midpoint"]

LAKH = 100_000
CRORE = 10_000_000
#: 40 hours a week for 52 weeks. Stated in every hourly conversion's assumption, because
#: it is a convention rather than a fact about the job.
HOURS_PER_YEAR = 2_080

_NOT_DISCLOSED_CUES = (
    "not disclosed",
    "undisclosed",
    "not mentioned",
    "not specified",
    "competitive",
    "best in industry",
    "best in the industry",
    "as per industry",
    "as per company",
    "negotiable",
    "market standard",
    "attractive",
    "doe",
    "depending on experience",
)

_SCALE_PATTERN = (
    r"(?P<unit>lpa|lakhs?|lacs?|lakh|l(?![a-z])|crores?|cr(?![a-z])|k(?![a-z])|thousand|"
    r"mn(?![a-z])|million)?"
)
_NUMBER = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*" + _SCALE_PATTERN, re.IGNORECASE)
_RANGE_JOINER = re.compile(r"^\s*(?:-|–|—|to|and)\s*$", re.IGNORECASE)
_CURRENCY_PREFIX = r"(?:\s*(?:₹|rs\.?|inr|usd|us\s?\$|\$|€|£|eur|gbp))?\s*$"
_UPPER_ONLY = re.compile(
    r"\b(?:up\s*to|upto|max(?:imum)?|not more than|below|under)" + _CURRENCY_PREFIX
)
_LOWER_ONLY = re.compile(
    r"\b(?:from|starting(?:\s+at)?|min(?:imum)?|at least|above|over)" + _CURRENCY_PREFIX
)
#: Numbers that describe something other than pay ("2-4 years", "20% bonus"). The second
#: alternative catches the low end of an experience range, whose own suffix is a dash.
_NOT_PAY_SUFFIX = re.compile(
    r"^\s*(?:\+\s*)?(?:years?|yrs?|months? of|%|percent|days?)\b"
    r"|^\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*\+?\s*(?:years?|yrs?)\b"
)
#: The one reading of the text that is an inference about scale rather than a conversion.
BARE_LAKH_ASSUMPTION = "bare number < 100 read as lakh"

_MONTHLY_CUES = re.compile(
    r"(?:per\s*month|/\s*month|/\s*mo\b|/\s*m\b|\bp\.?\s?m\.?(?![a-z])|\bmonthly\b|"
    r"\ba\s+month\b|\bmonth\b|\bpcm\b)",
    re.IGNORECASE,
)
_HOURLY_CUES = re.compile(
    r"(?:per\s*hour|/\s*hr\b|/\s*hour|/\s*h\b|\bhourly\b|\ban\s+hour\b|\bper\s*hr\b)",
    re.IGNORECASE,
)
_ANNUAL_CUES = re.compile(
    r"(?:per\s*annum|\bp\.?\s?a\.?(?![a-z])|\blpa\b|\bannual(?:ly)?\b|per\s*year|/\s*yr\b|"
    r"/\s*year|\ba\s+year\b|\byearly\b|\bctc\b|\bpa\b)",
    re.IGNORECASE,
)

_CURRENCY_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("INR", re.compile(r"(?:₹|\binr\b|\brs\.?(?![a-z])|\brupees?\b)", re.IGNORECASE)),
    ("USD", re.compile(r"(?:\busd\b|us\s?\$|\$|\bdollars?\b)", re.IGNORECASE)),
    ("EUR", re.compile(r"(?:€|\beur\b|\beuros?\b)", re.IGNORECASE)),
    ("GBP", re.compile(r"(?:£|\bgbp\b|\bpounds?\b)", re.IGNORECASE)),
)
#: Units that only exist in Indian salaries, so they imply INR when no currency is written.
_INDIAN_SCALES = frozenset({"lakh", "crore"})


@dataclass(slots=True)
class Compensation:
    """A salary as stated, plus what it means once converted, and how it was converted.

    ``minimum``/``maximum`` are in the stated period and currency. ``annual_*`` are the
    same currency converted to a year. ``inr_annual_*`` exist only when the currency is INR
    or a USD→INR rate is configured. ``assumptions`` lists every step that was not a
    literal reading of the text.
    """

    original: str
    currency: str | None = None
    period: Period | None = None
    minimum: float | None = None
    maximum: float | None = None
    annual_minimum: float | None = None
    annual_maximum: float | None = None
    inr_annual_minimum: float | None = None
    inr_annual_maximum: float | None = None
    is_range: bool = False
    disclosed: bool = False
    assumptions: list[str] = field(default_factory=list)
    #: Whether the currency and period were written in the text (rather than defaulted).
    currency_stated: bool = False
    period_stated: bool = False
    #: The notation the figures were written in: ``unit``, ``thousand``, ``lakh``,
    #: ``crore`` or ``million``. Used to decide whether a reformatted value is exact.
    scale: str = "unit"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Conversion:
    """A value proposed for a form field, with whether it is the text's own figure."""

    value: str
    exact: bool
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _FromSettings:
    """Sentinel: read ``usd_inr_rate`` from the application settings."""


FROM_SETTINGS = _FromSettings()


def _configured_rate() -> float | None:
    from app.config import get_settings

    return get_settings().usd_inr_rate


def _round(value: float) -> float:
    return round(value, 2)


def _fmt(value: float) -> str:
    """Human-readable figure for assumptions: 1500000 -> '1,500,000', 12.5 -> '12.5'."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _scale_of(unit: str) -> tuple[str, float]:
    unit = unit.lower()
    if unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
        return "lakh", LAKH
    if unit in ("crore", "crores", "cr"):
        return "crore", CRORE
    if unit in ("k", "thousand"):
        return "thousand", 1_000
    if unit in ("mn", "million"):
        return "million", 1_000_000
    return "unit", 1


def _detect_currency(text: str) -> str | None:
    for code, pattern in _CURRENCY_CUES:
        if pattern.search(text):
            return code
    return None


def _detect_period(text: str) -> Period | None:
    if _HOURLY_CUES.search(text):
        return "hourly"
    if _MONTHLY_CUES.search(text):
        return "monthly"
    if _ANNUAL_CUES.search(text):
        return "annual"
    return None


@dataclass(slots=True)
class _Figure:
    value: float
    unit: str
    start: int
    end: int


def _figures(text: str) -> list[_Figure]:
    found: list[_Figure] = []
    for match in _NUMBER.finditer(text):
        if _NOT_PAY_SUFFIX.match(text[match.end() :]):
            continue
        raw = match.group("num").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        found.append(
            _Figure(value, (match.group("unit") or "").lower(), match.start(), match.end())
        )
    return found


def parse_compensation(
    text: str | None,
    *,
    default_currency: str = "INR",
    usd_inr_rate: float | None | _FromSettings = FROM_SETTINGS,
) -> Compensation:
    """Parse salary text into figures, converting only where every step can be stated.

    ``usd_inr_rate`` defaults to the configured setting; pass ``None`` to disable USD→INR
    conversion or a number to use a specific rate (tests do). A missing rate is reported
    as an assumption, never replaced by a guessed one.
    """
    original = text or ""
    comp = Compensation(original=original)
    stripped = original.strip()
    if not stripped:
        comp.assumptions.append("No compensation text was provided; nothing was inferred.")
        return comp

    lowered = stripped.lower()
    figures = _figures(lowered)
    if not figures:
        cue = next((cue for cue in _NOT_DISCLOSED_CUES if cue in lowered), None)
        reason = f"the text says '{cue}'" if cue else "the text contains no figure"
        comp.assumptions.append(f"Not disclosed: {reason}; no amount was inferred.")
        return comp

    rate = _configured_rate() if isinstance(usd_inr_rate, _FromSettings) else usd_inr_rate

    # ---- Which figures form the salary: a range "A - B" or a single figure. ----
    low_fig: _Figure | None = figures[0]
    high_fig: _Figure | None = None
    if len(figures) >= 2 and _RANGE_JOINER.match(lowered[figures[0].end : figures[1].start]):
        high_fig = figures[1]
    upper_only = high_fig is None and bool(_UPPER_ONLY.search(lowered[: figures[0].start]))
    lower_only = high_fig is None and bool(_LOWER_ONLY.search(lowered[: figures[0].start]))

    # A unit written once applies to both ends: "12-18 LPA" is 12 lakh to 18 lakh.
    unit = (high_fig.unit if high_fig else "") or (low_fig.unit if low_fig else "")
    if low_fig and not low_fig.unit and unit:
        low_fig.unit = unit
    if high_fig and not high_fig.unit and low_fig and low_fig.unit:
        high_fig.unit = low_fig.unit
    scale_name, _ = _scale_of(unit)

    # ---- Currency ----
    currency = _detect_currency(lowered)
    if currency is not None:
        comp.currency_stated = True
    elif scale_name in _INDIAN_SCALES:
        currency = "INR"
        comp.currency_stated = True
        comp.assumptions.append(f"Currency not written; '{unit}' is an Indian unit, so INR.")
    else:
        currency = default_currency.upper()
        comp.assumptions.append(f"No currency was stated; read as {currency} (the default).")
    comp.currency = currency

    # ---- Period ----
    period = _detect_period(lowered)
    comp.period_stated = period is not None

    # ---- Scale each figure ----
    def scaled(figure: _Figure) -> float:
        name, multiplier = _scale_of(figure.unit)
        value = figure.value
        if name == "unit" and value < 100 and currency == "INR" and period in (None, "annual"):
            # Indian listings write "8-12" in a CTC field meaning lakh.
            if BARE_LAKH_ASSUMPTION not in comp.assumptions:
                comp.assumptions.append(BARE_LAKH_ASSUMPTION)
            name, multiplier = "lakh", LAKH
        return value * multiplier

    unit_note = {
        "lakh": ("LPA = lakh per annum = ×100,000" if unit == "lpa" else "lakh = ×100,000"),
        "crore": "Cr = crore = ×10,000,000",
        "thousand": "k = ×1,000",
        "million": "million = ×1,000,000",
    }.get(scale_name)
    if unit_note:
        comp.assumptions.append(unit_note)
    comp.scale = scale_name

    low_value = scaled(low_fig) if low_fig else None
    high_value = scaled(high_fig) if high_fig else None
    if BARE_LAKH_ASSUMPTION in comp.assumptions:
        comp.scale = "lakh"
        if period is None:
            period = "annual"
            comp.assumptions.append("A lakh figure is an annual CTC by Indian convention.")
    elif period is None and scale_name in ("lakh", "crore"):
        period = "annual"
        comp.assumptions.append("A lakh/crore figure is an annual CTC by Indian convention.")

    if low_value is not None and high_value is not None and low_value > high_value:
        low_value, high_value = high_value, low_value

    if upper_only:
        comp.minimum, comp.maximum = None, low_value
        comp.assumptions.append("Only an upper bound was stated; no minimum was inferred.")
    elif lower_only:
        comp.minimum, comp.maximum = low_value, None
        comp.assumptions.append("Only a lower bound was stated; no maximum was inferred.")
    else:
        comp.minimum = low_value
        comp.maximum = high_value if high_value is not None else low_value
    comp.is_range = high_value is not None and high_value != low_value
    comp.disclosed = comp.minimum is not None or comp.maximum is not None

    # ---- Period default, with a plausibility floor so "₹80k" is not called annual ----
    if period is None:
        largest = max(v for v in (comp.minimum, comp.maximum) if v is not None)
        floor = LAKH if currency == "INR" else 10_000
        if largest >= floor:
            period = "annual"
            comp.assumptions.append(
                "No pay period was stated; read as annual (the usual convention for a "
                f"figure of {_fmt(largest)} {currency})."
            )
        else:
            comp.assumptions.append(
                "No pay period was stated and the figure is too small to assume annual; "
                "it was not converted to a yearly amount."
            )
    comp.period = period

    # ---- Annualise in the same currency ----
    factor: float | None = {"annual": 1, "monthly": 12, "hourly": HOURS_PER_YEAR}.get(
        period or "", None
    )
    if period == "monthly":
        comp.assumptions.append("monthly × 12")
    elif period == "hourly":
        comp.assumptions.append(f"hourly × {HOURS_PER_YEAR:,} (40 h/week × 52 weeks)")
    if factor is not None:
        comp.annual_minimum = _round(comp.minimum * factor) if comp.minimum is not None else None
        comp.annual_maximum = _round(comp.maximum * factor) if comp.maximum is not None else None
    if comp.minimum is not None:
        comp.minimum = _round(comp.minimum)
    if comp.maximum is not None:
        comp.maximum = _round(comp.maximum)

    # ---- INR view ----
    if comp.annual_minimum is None and comp.annual_maximum is None:
        return comp
    if currency == "INR":
        comp.inr_annual_minimum, comp.inr_annual_maximum = comp.annual_minimum, comp.annual_maximum
    elif currency == "USD" and rate:
        comp.assumptions.append(f"USD→INR at configured rate {rate:g}")
        comp.inr_annual_minimum = (
            _round(comp.annual_minimum * rate) if comp.annual_minimum is not None else None
        )
        comp.inr_annual_maximum = (
            _round(comp.annual_maximum * rate) if comp.annual_maximum is not None else None
        )
    elif currency == "USD":
        comp.assumptions.append(
            "No USD→INR rate is configured (JA_USD_INR_RATE), so no INR value is shown."
        )
    else:
        comp.assumptions.append(f"No {currency}→INR rate is configured, so no INR value is shown.")
    return comp


def compensation_from_amounts(
    minimum: float | None,
    maximum: float | None,
    currency: str | None,
    *,
    period: Period = "annual",
    note: str,
    usd_inr_rate: float | None | _FromSettings = FROM_SETTINGS,
) -> Compensation:
    """Build a :class:`Compensation` from structured fields instead of text.

    ``note`` records where the numbers came from and why the period is what it is, since
    structured columns carry no unit of their own.
    """
    shown = [_fmt(v) for v in (minimum, maximum) if v is not None]
    original = f"{currency or ''} {' - '.join(dict.fromkeys(shown))} ({period})" if shown else ""
    comp = Compensation(original=original.strip())
    if minimum is None and maximum is None:
        comp.assumptions.append("No figure is recorded; nothing was inferred.")
        return comp
    rate = _configured_rate() if isinstance(usd_inr_rate, _FromSettings) else usd_inr_rate
    comp.currency = (currency or "INR").upper()
    comp.currency_stated = bool(currency)
    if not currency:
        comp.assumptions.append("No currency is recorded; read as INR (the default).")
    comp.period, comp.period_stated = period, True
    comp.assumptions.append(note)
    comp.minimum = float(minimum) if minimum is not None else None
    comp.maximum = float(maximum) if maximum is not None else comp.minimum
    comp.is_range = comp.minimum is not None and comp.maximum not in (None, comp.minimum)
    comp.disclosed = True
    factor = {"annual": 1, "monthly": 12, "hourly": HOURS_PER_YEAR}[period]
    if period == "monthly":
        comp.assumptions.append("monthly × 12")
    elif period == "hourly":
        comp.assumptions.append(f"hourly × {HOURS_PER_YEAR:,} (40 h/week × 52 weeks)")
    comp.annual_minimum = _round(comp.minimum * factor) if comp.minimum is not None else None
    comp.annual_maximum = _round(comp.maximum * factor) if comp.maximum is not None else None
    if comp.currency == "INR":
        comp.inr_annual_minimum, comp.inr_annual_maximum = comp.annual_minimum, comp.annual_maximum
    elif comp.currency == "USD" and rate:
        comp.assumptions.append(f"USD→INR at configured rate {rate:g}")
        comp.inr_annual_minimum = (
            _round(comp.annual_minimum * rate) if comp.annual_minimum is not None else None
        )
        comp.inr_annual_maximum = (
            _round(comp.annual_maximum * rate) if comp.annual_maximum is not None else None
        )
    elif comp.currency == "USD":
        comp.assumptions.append(
            "No USD→INR rate is configured (JA_USD_INR_RATE), so no INR value is shown."
        )
    else:
        comp.assumptions.append(
            f"No {comp.currency}→INR rate is configured, so no INR value is shown."
        )
    return comp


# --------------------------------------------------------------------------------------
# Screening questions
# --------------------------------------------------------------------------------------

_SALARY_TERMS = re.compile(
    r"\b(?:salary|salaries|ctc|cctc|ectc|compensation|pay|package|remuneration|stipend|wages?|"
    r"lpa|income|earnings?|take[- ]home|in[- ]hand|gross|fixed)\b",
    re.IGNORECASE,
)
_CURRENT_TERMS = re.compile(
    r"\b(?:current(?:ly)?|present|last[- ]drawn|drawn|existing|previous|prior|cctc|"
    r"last salary|most recent|today)\b",
    re.IGNORECASE,
)
_EXPECTED_TERMS = re.compile(
    r"\b(?:expect(?:ed|ing|ation|ations)?|ectc|desired|target|asking|anticipated|"
    r"looking for|preferred|requirement|requirements|require|hoping|minimum acceptable|"
    r"would you accept|what salary would)\b",
    re.IGNORECASE,
)


def salary_kind(label: str | None) -> SalaryKind | None:
    """Whether a screening question asks for current or expected pay, or ``None``.

    Returns ``None`` when the label is not about pay at all, or when it mentions both
    (e.g. "expected hike over current CTC"): answering the wrong one is worse than asking
    the user, because current and expected CTC differ by exactly the amount that matters.
    """
    text = (label or "").strip()
    if not text or not _SALARY_TERMS.search(text):
        return None
    current = bool(_CURRENT_TERMS.search(text))
    expected = bool(_EXPECTED_TERMS.search(text))
    if current and expected:
        return None
    if current:
        return "current"
    if expected:
        return "expected"
    return None


_LAKH_UNIT = re.compile(r"\b(?:lpa|lakhs?|lacs?|lakh)\b|\bin\s+l\b|\(l\)", re.IGNORECASE)
_INR_TERMS = re.compile(r"(?:₹|\binr\b|\brs\.?(?![a-z])|\brupees?\b)", re.IGNORECASE)
_USD_TERMS = re.compile(r"(?:\busd\b|us\s?\$|\$|\bdollars?\b)", re.IGNORECASE)
_INDIAN_PAY_TERMS = re.compile(r"\b(?:ctc|cctc|ectc|in[- ]hand)\b", re.IGNORECASE)
_LABEL_MONTHLY = re.compile(r"\b(?:monthly|per\s*month|a\s+month|/\s*month|pm|p\.m\.)\b", re.I)
_LABEL_ANNUAL = re.compile(
    r"\b(?:annual(?:ly)?|per\s*annum|p\.?a\.?|yearly|per\s*year|a\s+year|ctc|cctc|ectc)\b",
    re.IGNORECASE,
)
_LABEL_HOURLY = re.compile(r"\b(?:hourly|per\s*hour|an\s+hour)\b", re.IGNORECASE)


def detect_question_unit(question_label: str | None) -> QuestionUnit | None:
    """The unit a salary question expects its answer in, or ``None`` if unclear.

    ``None`` is the honest answer for "Expected salary" with no unit: the form filler
    should then ask the user rather than pick one.
    """
    text = (question_label or "").strip()
    if not text:
        return None
    monthly = bool(_LABEL_MONTHLY.search(text))
    hourly = bool(_LABEL_HOURLY.search(text))
    annual = bool(_LABEL_ANNUAL.search(text))

    if _LAKH_UNIT.search(text):
        return None if (monthly or hourly) else "lpa"
    if _USD_TERMS.search(text):
        return "usd_annual" if not (monthly or hourly) else None
    if hourly:
        return None
    inr = bool(_INR_TERMS.search(text)) or bool(_INDIAN_PAY_TERMS.search(text))
    if not inr:
        return None
    if monthly and not re.search(r"\b(?:ctc|annual|per annum|yearly)\b", text, re.I):
        return "inr_monthly"
    if monthly and annual:
        return None
    return "inr_annual"


# --------------------------------------------------------------------------------------
# Proposing an answer in a form's unit
# --------------------------------------------------------------------------------------


def _number_text(value: float, decimals: int = 0) -> str:
    if decimals == 0:
        return str(int(round(value)))
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text or "0"


def _choose(low: float | None, high: float | None, pick: Pick) -> tuple[float | None, list[str]]:
    """One figure from a range, saying which one was taken when it was a real choice."""
    if low is None or high is None:
        return (low if low is not None else high), []
    if low == high:
        return low, []
    if pick == "maximum":
        return high, ["The range's upper bound is proposed."]
    if pick == "midpoint":
        return (low + high) / 2, ["The midpoint of the range is proposed."]
    return low, ["The range's lower bound is proposed."]


def format_for_unit(
    comp: Compensation,
    unit: str,
    *,
    pick: Pick = "minimum",
    usd_inr_rate: float | None | _FromSettings = FROM_SETTINGS,
) -> Conversion:
    """Propose ``comp`` as a value in ``unit``. A suggestion, never a typed answer.

    ``exact`` is ``True`` only when the proposed number is the text's own figure in the
    text's own notation (e.g. "12 LPA" proposed as LPA "12", "₹ 12,00,000 per annum" as
    INR annual "1200000"). Any change of notation, period or currency, any defaulted
    currency or period, the bare-number-as-lakh reading, and any pick from a range make it
    ``False``, so the caller asks the user before using it. ``assumptions`` carries the
    parse's own assumptions followed by those of this conversion.
    """
    if unit not in QUESTION_UNITS:
        return Conversion("", False, [f"Unknown unit '{unit}'; nothing was proposed."])
    if not comp.disclosed:
        return Conversion("", False, ["No figure is available, so nothing was proposed."])

    assumptions = list(comp.assumptions)
    rate = _configured_rate() if isinstance(usd_inr_rate, _FromSettings) else usd_inr_rate
    literal = (
        comp.currency_stated and comp.period_stated and BARE_LAKH_ASSUMPTION not in comp.assumptions
    )

    if unit in ("lpa", "inr_annual", "inr_monthly"):
        low, high = comp.inr_annual_minimum, comp.inr_annual_maximum
        if low is None and high is None:
            reason = (
                "the figure has no known pay period, so it cannot be annualised"
                if comp.currency == "INR"
                else f"no INR value is available for {comp.currency} (no exchange rate)"
            )
            return Conversion("", False, [*assumptions, f"Not proposed: {reason}."])
        annual, notes = _choose(low, high, pick)
        assert annual is not None
        assumptions.extend(notes)
        literal = literal and comp.currency == "INR" and not notes
        if unit == "lpa":
            exact = literal and comp.period == "annual" and comp.scale == "lakh"
            if comp.scale != "lakh" or comp.period != "annual":
                assumptions.append("annual INR ÷ 100,000 = LPA")
            return Conversion(_number_text(annual / LAKH, 2), exact, assumptions)
        if unit == "inr_annual":
            exact = literal and comp.period == "annual" and comp.scale == "unit"
            if comp.scale != "unit" and not notes:
                assumptions.append(f"written in {comp.scale}; expanded to rupees")
            return Conversion(_number_text(annual), exact, assumptions)
        exact = literal and comp.period == "monthly" and comp.scale == "unit"
        if comp.period != "monthly":
            assumptions.append("annual ÷ 12 = monthly")
        return Conversion(_number_text(annual / 12), exact, assumptions)

    # usd_annual
    if comp.currency == "USD":
        annual, notes = _choose(comp.annual_minimum, comp.annual_maximum, pick)
        if annual is None:
            return Conversion(
                "", False, [*assumptions, "Not proposed: the figure has no known pay period."]
            )
        assumptions.extend(notes)
        exact = literal and not notes and comp.period == "annual" and comp.scale == "unit"
        return Conversion(_number_text(annual), exact, assumptions)
    if comp.currency == "INR" and rate:
        annual, notes = _choose(comp.inr_annual_minimum, comp.inr_annual_maximum, pick)
        if annual is None:
            return Conversion(
                "", False, [*assumptions, "Not proposed: the figure has no known pay period."]
            )
        assumptions.extend(notes)
        assumptions.append(f"INR→USD at configured rate {rate:g} (÷ {rate:g})")
        return Conversion(_number_text(annual / rate), False, assumptions)
    return Conversion(
        "",
        False,
        [
            *assumptions,
            f"Not proposed: converting {comp.currency} to USD needs a configured "
            "USD→INR rate (JA_USD_INR_RATE).",
        ],
    )


__all__ = [
    "BARE_LAKH_ASSUMPTION",
    "HOURS_PER_YEAR",
    "QUESTION_UNITS",
    "Compensation",
    "Conversion",
    "compensation_from_amounts",
    "detect_question_unit",
    "format_for_unit",
    "parse_compensation",
    "salary_kind",
]
