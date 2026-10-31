"""Text normalization shared by the parser, the normalizer and the matcher.

Skill comparison is the core of matching, so it cannot be naive string equality:
"NodeJS", "node.js" and "Node JS" are the same skill, and "golang" is "go". The alias
table below is intentionally small and explicit rather than a fuzzy-similarity function,
because a false skill match silently inflates a score the user is trusting.
"""

from __future__ import annotations

import html
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9+#.\- ]+")
_COMPANY_SUFFIXES = (
    "private limited",
    "pvt ltd",
    "pvt. ltd.",
    "pvt limited",
    "limited",
    "ltd",
    "pvt",
    "pte",
    "plc",
    "llc",
    "llp",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "gmbh",
    "ag",
    "bv",
    "nv",
    "sa",
    "technologies",
    "technology",
    "tech",
    "solutions",
    "services",
    "labs",
    "systems",
    "software",
    "consulting",
    "global",
    "group",
    "india",
)

SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "node": "node.js",
    "nodejs": "node.js",
    "node js": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "react js": "react",
    "vuejs": "vue",
    "vue.js": "vue",
    "nextjs": "next.js",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "golang": "go",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "k8s": "kubernetes",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "amazon web services": "aws",
    "ms azure": "azure",
    "microsoft azure": "azure",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "restful api": "rest api",
    "restful apis": "rest api",
    "rest apis": "rest api",
    "restapi": "rest api",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "genai": "generative ai",
    "gen ai": "generative ai",
    "llms": "llm",
    "large language model": "llm",
    "large language models": "llm",
    "rag": "retrieval augmented generation",
    "langchain.js": "langchain",
    "tf": "tensorflow",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "html5": "html",
    "css3": "css",
    "tailwindcss": "tailwind",
    "tailwind css": "tailwind",
    "dsa": "data structures and algorithms",
    "oops": "object oriented programming",
    "oop": "object oriented programming",
    "unit testing": "testing",
    "git hub": "github",
    "fast api": "fastapi",
    "dot net": ".net",
    "c sharp": "c#",
    "c plus plus": "c++",
}


def collapse_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def strip_html(value: str) -> str:
    """Turn an HTML job description into readable plain text.

    Entities are unescaped *before* tags are removed, because Greenhouse returns its
    ``content`` field as escaped HTML (``&lt;p&gt;``). Stripping first would leave the
    escaped markup in the text, and a later unescape anywhere downstream would turn it
    back into live tags. Unescaping first means no tag survives in the output at all.
    """
    if not value:
        return ""
    unescaped = html.unescape(value)
    without_blocks = re.sub(
        r"(?i)</?(?:p|div|br|li|ul|ol|tr|h[1-6]|table|section)[^>]*>", "\n", unescaped
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_blocks)
    # An inline tag becomes a space, so "<strong>Python</strong>." would read "Python .".
    tidied = re.sub(r"\s+([,.;:!?)])", r"\1", without_tags)
    lines = [collapse_whitespace(line) for line in tidied.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_text(value: str) -> str:
    """Lowercase, strip accents, drop punctuation that never distinguishes meaning."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = ascii_only.lower().replace("_", " ").replace("/", " ")
    return collapse_whitespace(_NON_ALNUM.sub(" ", lowered))


def canonical_skill(value: str) -> str:
    """Map a skill string onto its canonical form, or '' if it is not a skill token."""
    base = normalize_text(value).strip(" .-")
    if not base or len(base) > 60:
        return ""
    return SKILL_ALIASES.get(base, base)


def canonical_skills(values: list[str]) -> list[str]:
    """Canonicalize and de-duplicate while preserving first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        canonical = canonical_skill(value)
        if canonical:
            seen.setdefault(canonical, None)
    return list(seen)


def normalize_company(value: str) -> str:
    """Strip legal suffixes so 'Acme Technologies Pvt Ltd' and 'Acme' collide."""
    base = normalize_text(value)
    if not base:
        return ""
    changed = True
    while changed:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            if base.endswith(" " + suffix):
                base = base[: -(len(suffix) + 1)].strip()
                changed = True
    return base or normalize_text(value)


def normalize_location(value: str) -> str:
    """Normalize a location string and fold common Indian city aliases.

    The split on separators happens before :func:`normalize_text`, because that function
    strips punctuation; normalizing first would merge "Bengaluru, Karnataka, India" into a
    single token and break comparison against "Bengaluru".
    """
    if not value or not value.strip():
        return ""
    aliases = {
        "bangalore": "bengaluru",
        "bombay": "mumbai",
        "calcutta": "kolkata",
        "madras": "chennai",
        "gurgaon": "gurugram",
        "new delhi": "delhi",
        "delhi ncr": "delhi",
        "ncr": "delhi",
        "trivandrum": "thiruvananthapuram",
        "pondicherry": "puducherry",
        "work from home": "remote",
        "anywhere": "remote",
        "wfh": "remote",
    }
    parts: list[str] = []
    for chunk in re.split(r"[,;|/]|\s+-\s+", value):
        normalized = normalize_text(chunk).strip(" .")
        if normalized:
            parts.append(aliases.get(normalized, normalized))
    return ", ".join(dict.fromkeys(parts))


def tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) > 1}


_TITLE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "of",
        "in",
        "at",
        "to",
        "with",
        "job",
        "jobs",
        "role",
        "opening",
        "openings",
        "position",
        "hiring",
        "urgent",
        "immediate",
        "opportunity",
        "fresher",
        "freshers",
        "remote",
        "hybrid",
        "onsite",
        "fulltime",
        "parttime",
        "intern",
        "internship",
        "contract",
        "yrs",
        "years",
        "exp",
        "experience",
        "i",
        "ii",
        "iii",
        "iv",
    }
)

_SENIORITY_MARKERS: dict[str, int] = {
    "intern": 0,
    "trainee": 0,
    "graduate": 0,
    "fresher": 0,
    "entry": 0,
    "junior": 1,
    "jr": 1,
    "associate": 1,
    "mid": 2,
    "intermediate": 2,
    "senior": 3,
    "sr": 3,
    "lead": 4,
    "staff": 4,
    "principal": 5,
    "architect": 5,
    "head": 5,
    "manager": 5,
    "director": 6,
    "vp": 6,
    "chief": 6,
}


def title_tokens(value: str) -> set[str]:
    """Meaningful tokens from a job title, with filler and seniority noise removed."""
    return {token for token in tokens(value) if token not in _TITLE_STOPWORDS}


def seniority_level(value: str) -> int | None:
    """Infer a seniority rank from a title, or ``None`` when the title says nothing.

    Returning ``None`` matters: a title like "Software Engineer" carries no seniority
    signal, and guessing one would let the filter reject a role that is actually open to
    freshers.

    Trailing ``+`` and ``.`` are stripped before the lookup. :func:`normalize_text` keeps
    both so that "c++" and "node.js" survive as skills, which left "Staff+ Software
    Engineer" and "Sr. Controls Software Engineer" as the tokens ``staff+`` and ``sr.`` —
    neither matched a marker, so both senior roles escaped the seniority filter and reached
    the review band on real data.
    """
    found = [
        _SENIORITY_MARKERS[candidate]
        for token in tokens(value)
        if (candidate := token.rstrip("+.")) in _SENIORITY_MARKERS
    ]
    return max(found) if found else None


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
