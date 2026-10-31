"""Deduplication.

Three independent identities are checked, in decreasing order of reliability:

1. ``(source, external_id)`` — the platform's own identifier. Authoritative within a source.
2. ``canonical_url`` — the same posting shared with different tracking parameters.
3. ``fingerprint`` — a hash of normalized title, company, location and a description
   signature. This is what catches the same job posted on two different platforms.

The fingerprint deliberately excludes the source, the URL and the posting date, because
those are exactly the fields that differ between two platforms carrying the same role.
It includes a coarse description signature rather than the full text, so that a reposted
description with a changed sentence still collapses.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.services.text import (
    collapse_whitespace,
    normalize_company,
    normalize_location,
    normalize_text,
)

_DESCRIPTION_SIGNATURE_TOKENS = 40


class MatchKind(str, Enum):
    NEW = "new"
    SAME_SOURCE_ID = "same_source_id"
    SAME_URL = "same_url"
    SAME_FINGERPRINT = "same_fingerprint"


@dataclass(frozen=True, slots=True)
class DedupDecision:
    kind: MatchKind
    existing_job_id: int | None = None
    detail: str = ""

    @property
    def is_duplicate(self) -> bool:
        return self.kind is not MatchKind.NEW


def description_signature(description: str) -> str:
    """A stable, order-independent signature of the most distinctive description words.

    Sorting the longest tokens makes the signature insensitive to paragraph reordering and
    to boilerplate inserted at the top by a job board.
    """
    if not description:
        return ""
    words = [word for word in normalize_text(description).split() if len(word) > 4]
    distinctive = sorted(set(words), key=lambda word: (-len(word), word))[
        :_DESCRIPTION_SIGNATURE_TOKENS
    ]
    return " ".join(sorted(distinctive))


_TITLE_NOISE = frozenset(
    {
        "urgent",
        "immediate",
        "hiring",
        "opening",
        "openings",
        "job",
        "jobs",
        "vacancy",
        "apply",
        "now",
        "fresher",
        "freshers",
        "remote",
        "hybrid",
        "onsite",
        "wfh",
        "fulltime",
        "full",
        "time",
        "parttime",
        "part",
        "intern",
        "internship",
    }
)

#: A dash-separated prefix is only treated as the role when it carries at least this many
#: meaningful words. Measured on a live SmartRecruiters run: Bosch posts dozens of research
#: openings titled "PhD - <research topic>" and "Promotion - <topic>". Taking the prefix
#: unconditionally reduced every one of them to "phd" or "promotion", so unrelated openings
#: at one city merged into a single job and the rest of the listings were lost.
_MIN_PREFIX_WORDS = 2


def _meaningful_tokens(text: str) -> set[str]:
    return {token for token in text.split() if token not in _TITLE_NOISE and len(token) > 1}


def _core_title(title: str) -> str:
    """Reduce a title to its comparable core.

    Strips bracketed qualifiers, location suffixes and recruiter noise, which vary between
    platforms for the same role ("Software Engineer (Backend) - Bengaluru | Urgent").
    """
    text = normalize_text(re.sub(r"[\(\[].*?[\)\]]", " ", title))
    if re.search(r"\s[-|]\s", text):
        prefix = re.split(r"\s[-|]\s", text)[0]
        if len(_meaningful_tokens(prefix)) >= _MIN_PREFIX_WORDS:
            text = prefix
    core = " ".join(sorted(_meaningful_tokens(text)))
    return core or _non_latin_core(title)


def _non_latin_core(title: str) -> str:
    """Fallback core for a title whose script ``normalize_text`` discards entirely.

    ``normalize_text`` keeps only ``[a-z0-9+#.-]``, so a title written in Chinese, Japanese,
    Korean, Cyrillic, Arabic or Devanagari reduces to the empty string. Measured on a live
    SmartRecruiters run: every CJK posting at one company and city then produced an
    *identical* fingerprint, so unrelated roles were merged into one job and the distinct
    listings were lost. Keeping the script's own characters restores distinctness.

    This runs only when the Latin core is empty **and** the title carries a non-ASCII
    alphanumeric character, so every pure-ASCII fingerprint keeps its existing value and
    no already-stored fingerprint is invalidated.
    """
    if not any(ch.isalnum() and ord(ch) > 127 for ch in title):
        return ""
    kept = [ch for ch in title.casefold() if ch.isalnum() or ch.isspace()]
    return collapse_whitespace("".join(kept))


def compute_fingerprint(title: str, company: str, location: str, description: str = "") -> str:
    """Return the SHA-256 fingerprint used for cross-platform duplicate detection."""
    parts = [
        _core_title(title),
        normalize_company(company),
        # Only the first location token is used: "Bengaluru, Karnataka, India" and
        # "Bengaluru" are the same place, and platforms disagree on how much to include.
        normalize_location(location).split(",")[0].strip(),
        description_signature(description),
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


def fingerprint_for_values(values: dict[str, Any]) -> str:
    return compute_fingerprint(
        values.get("title", ""),
        values.get("company", ""),
        values.get("location", ""),
        values.get("description", ""),
    )
