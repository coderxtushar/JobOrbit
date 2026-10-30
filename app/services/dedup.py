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

from app.services.text import normalize_company, normalize_location, normalize_text

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


def _core_title(title: str) -> str:
    """Reduce a title to its comparable core.

    Strips bracketed qualifiers, location suffixes and recruiter noise, which vary between
    platforms for the same role ("Software Engineer (Backend) - Bengaluru | Urgent").
    """
    text = normalize_text(re.sub(r"[\(\[].*?[\)\]]", " ", title))
    text = re.split(r"\s[-|]\s", text)[0] if re.search(r"\s[-|]\s", text) else text
    noise = {
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
    return " ".join(
        sorted({token for token in text.split() if token not in noise and len(token) > 1})
    )


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
