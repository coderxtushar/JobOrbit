"""Manual JSON/CSV import.

This is the only adapter that performs real data acquisition in this build, and it is the
one path that works with no credentials, no network access and no platform cooperation.

Accepted shapes:

* JSON: a list of objects, or an object with a ``jobs``/``records``/``data`` list.
* CSV/TSV: a header row plus data rows. Column names are matched case-insensitively
  against a synonym table, so exports from different boards work without hand-editing.

Every row is validated against :class:`RawJobRecord`. Invalid rows are counted and
reported with their row number; they are never silently dropped and never repaired by
guessing.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.db.models import SourceName
from app.schemas.job import RawJobRecord
from app.sources.base import AdapterCapabilities, DiscoveryResult, SourceAdapter

MAX_RECORDS_PER_IMPORT = 2000

_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "title": ("title", "job title", "job_title", "jobtitle", "position", "role", "designation"),
    "company": (
        "company",
        "company name",
        "company_name",
        "employer",
        "organisation",
        "organization",
    ),
    "location": ("location", "job location", "city", "place", "locations"),
    "url": ("url", "job url", "job_url", "link", "apply url", "apply_link", "joburl", "jd link"),
    "external_id": ("external_id", "id", "job id", "job_id", "jobid", "reference", "req id"),
    "description": (
        "description",
        "job description",
        "job_description",
        "jd",
        "details",
        "summary",
    ),
    "posted_at": (
        "posted_at",
        "posted",
        "posted date",
        "posted_date",
        "date posted",
        "date_posted",
        "published",
        "published_at",
        "posting date",
        "created_at",
    ),
    "salary_raw": ("salary", "salary_raw", "compensation", "ctc", "pay", "package"),
    "experience_raw": (
        "experience",
        "experience_raw",
        "exp",
        "years of experience",
        "experience required",
    ),
    "employment_type": ("employment_type", "job type", "job_type", "type", "employment"),
    "work_arrangement": (
        "work_arrangement",
        "workplace",
        "remote",
        "work mode",
        "work_mode",
        "workplace type",
    ),
    "required_skills": (
        "required_skills",
        "skills",
        "key skills",
        "key_skills",
        "must have skills",
        "tags",
    ),
    "preferred_skills": ("preferred_skills", "good to have", "nice to have", "optional skills"),
    "education_requirements": (
        "education",
        "education_requirements",
        "qualification",
        "qualifications",
    ),
    "source": ("source", "platform", "job board", "site"),
    "application_method": ("application_method", "apply method", "how to apply"),
}

_LIST_FIELDS = frozenset({"required_skills", "preferred_skills", "education_requirements"})


class ImportParseError(ValueError):
    """Raised when a payload cannot be interpreted as JSON or CSV at all."""


def _normalize_key(key: str) -> str:
    return " ".join(str(key or "").strip().lower().replace("_", " ").split())


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Map each input column to a canonical field name."""
    mapping: dict[str, str] = {}
    for column in fieldnames:
        normalized = _normalize_key(column)
        for canonical, synonyms in _COLUMN_SYNONYMS.items():
            if normalized in {_normalize_key(synonym) for synonym in synonyms}:
                mapping[column] = canonical
                break
    return mapping


def _split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    if not text.strip():
        return []
    for separator in ("|", ";", ","):
        if separator in text:
            return [part.strip() for part in text.split(separator) if part.strip()]
    return [text.strip()]


def _coerce_record(raw: dict[str, Any], default_source: SourceName) -> dict[str, Any]:
    """Rename and coerce one inbound row into ``RawJobRecord`` keyword arguments."""
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = None
        normalized_key = _normalize_key(key)
        for candidate, synonyms in _COLUMN_SYNONYMS.items():
            if normalized_key in {_normalize_key(synonym) for synonym in synonyms}:
                canonical = candidate
                break
        if canonical is None:
            # Unrecognized columns are kept as source metadata under a normalized key,
            # so consumers do not have to guess the original file's capitalisation.
            canonical = normalized_key or str(key)
        if canonical in _LIST_FIELDS:
            normalized[canonical] = _split_list(value)
        elif isinstance(value, str):
            normalized[canonical] = value.strip()
        else:
            normalized[canonical] = value

    source_value = normalized.get("source")
    if isinstance(source_value, str) and source_value.strip():
        try:
            normalized["source"] = SourceName(source_value.strip().lower())
        except ValueError:
            normalized["source"] = default_source
    else:
        normalized["source"] = default_source

    for numeric in ("salary_min", "salary_max", "experience_min_years", "experience_max_years"):
        if normalized.get(numeric) in ("", None):
            normalized.pop(numeric, None)

    known = set(RawJobRecord.model_fields)
    extras = {key: value for key, value in normalized.items() if key not in known}
    cleaned = {key: value for key, value in normalized.items() if key in known}
    if extras:
        metadata = cleaned.get("source_metadata")
        merged = dict(metadata) if isinstance(metadata, dict) else {}
        merged.update({key: value for key, value in extras.items() if value not in ("", None)})
        cleaned["source_metadata"] = merged
    return cleaned


def _rows_from_json(payload: bytes) -> list[dict[str, Any]]:
    document = json.loads(payload.decode("utf-8-sig"))
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict):
        for key in ("jobs", "records", "data", "results", "items"):
            if isinstance(document.get(key), list):
                rows = document[key]
                break
        else:
            rows = [document]
    else:
        raise ImportParseError("JSON must be a list of jobs or an object containing one")
    if not all(isinstance(row, dict) for row in rows):
        raise ImportParseError("every JSON entry must be an object")
    return rows


def _rows_from_csv(payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportParseError("the CSV file has no header row")
    return [{key: value for key, value in row.items() if key is not None} for row in reader]


def parse_payload(
    payload: bytes, *, filename: str = "", default_source: SourceName = SourceName.MANUAL
) -> DiscoveryResult:
    """Parse a JSON or CSV payload into validated records."""
    if not payload or not payload.strip():
        raise ImportParseError("the uploaded file is empty")

    # A NUL byte never occurs in CSV, TSV or JSON. Without this check a binary file is
    # decoded with errors="replace", parses as a header-only document with no data rows,
    # and is then reported as a SUCCESSFUL import of zero jobs.
    if b"\x00" in payload[:8192]:
        raise ImportParseError(
            "this looks like a binary file, not CSV, TSV or JSON. Export the jobs as text "
            "and try again."
        )

    lowered = filename.lower()
    stripped = payload.lstrip()
    looks_like_json = stripped[:1] in (b"[", b"{")

    if lowered.endswith((".csv", ".tsv")) and not looks_like_json:
        rows = _rows_from_csv(payload)
    elif looks_like_json or lowered.endswith(".json"):
        try:
            rows = _rows_from_json(payload)
        except json.JSONDecodeError as exc:
            raise ImportParseError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    else:
        rows = _rows_from_csv(payload)

    if not rows:
        raise ImportParseError(
            "no job rows were found in the file. A CSV needs a header row plus at least "
            "one data row; JSON needs a non-empty list of job objects."
        )

    if len(rows) > MAX_RECORDS_PER_IMPORT:
        raise ImportParseError(
            f"{len(rows)} rows exceeds the {MAX_RECORDS_PER_IMPORT}-row import limit; "
            "split the file and import it in parts"
        )

    records: list[RawJobRecord] = []
    errors: list[str] = []
    invalid = 0
    for index, row in enumerate(rows, start=1):
        try:
            records.append(RawJobRecord.model_validate(_coerce_record(row, default_source)))
        except Exception as exc:
            invalid += 1
            if len(errors) < 25:
                errors.append(f"row {index}: {_summarize_validation_error(exc)}")

    if invalid and not records:
        errors.append(
            "No row could be imported. Each row needs at least a title, a company, and "
            "either a url or an id."
        )
    return DiscoveryResult(
        records=records,
        errors=errors,
        invalid_count=invalid,
        metadata={"row_count": len(rows), "filename": filename},
    )


def _summarize_validation_error(exc: Exception) -> str:
    """Flatten a Pydantic error into one short line, without dumping the row contents."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)[:200]
    parts = []
    for detail in errors()[:4]:
        location = ".".join(str(item) for item in detail.get("loc", ())) or "record"
        parts.append(f"{location}: {detail.get('msg', 'invalid')}")
    return "; ".join(parts)[:300]


class ManualImportAdapter(SourceAdapter):
    """Generic import source for files the user supplies themselves."""

    source = SourceName.MANUAL
    display_name = "Manual import (JSON/CSV)"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=False,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "You provide the data yourself, so no platform term of service applies to the "
        "acquisition step."
    )
    limitations = (
        "Requires a file. There is no automated fetching, by design.",
        "Rows missing a title, company, or url/id are rejected and reported.",
    )

    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        from app.sources.base import CapabilityNotAvailable

        raise CapabilityNotAvailable(
            self.source,
            "authorized_discovery",
            "Manual import has nothing to discover on its own. Upload a JSON or CSV file "
            "on the Job discovery page.",
        )


class CsvImportAdapter(ManualImportAdapter):
    """Alias source used to tag rows that arrived through the CSV upload endpoint."""

    source = SourceName.CSV
    display_name = "CSV import"
