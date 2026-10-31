"""Saved searches and the "new since you last looked" digest.

A saved search is a named :class:`~app.db.repositories.jobs.JobQuery`. It deliberately
stores *criteria*, not a snapshot of results, so running it again reflects the current feed
and the current ranking rather than a frozen list that silently goes stale.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, JobStatus, SavedSearch, SourceName, utcnow
from app.db.repositories.jobs import JobQuery, JobRepository

#: Criteria a saved search may carry. Restricted to this set rather than accepting an
#: arbitrary dict, because the stored JSON is replayed into a database query: an unknown
#: key must be rejected at write time, not silently ignored at read time or passed through.
ALLOWED_CRITERIA = frozenset(
    {
        "search",
        "statuses",
        "sources",
        "company",
        "min_score",
        "max_age_days",
        "bands",
        "include_duplicates",
        "sort_by",
        "descending",
    }
)

SavedSearchList = list[SavedSearch]
JobHitList = list[Job]


class UnknownCriterionError(ValueError):
    """Raised when a saved search names a filter the job query does not support."""


@dataclass(slots=True)
class DigestResult:
    """What a saved search found, split by whether the user has seen it before."""

    search_id: int
    name: str
    total_matching: int
    new_since_last_run: int
    previous_run_at: datetime | None
    jobs: JobHitList


def validate_criteria(criteria: dict[str, object]) -> dict[str, object]:
    unknown = set(criteria) - ALLOWED_CRITERIA
    if unknown:
        raise UnknownCriterionError(
            "unsupported search criteria: " + ", ".join(sorted(str(key) for key in unknown))
        )
    return criteria


class SavedSearchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, profile_id: int) -> SavedSearchList:
        statement = (
            select(SavedSearch)
            .where(SavedSearch.profile_id == profile_id)
            .order_by(SavedSearch.name)
        )
        return list(self._session.execute(statement).scalars())

    def get(self, search_id: int, profile_id: int) -> SavedSearch | None:
        statement = select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.profile_id == profile_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_name(self, name: str, profile_id: int) -> SavedSearch | None:
        statement = select(SavedSearch).where(
            SavedSearch.name == name, SavedSearch.profile_id == profile_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def create(self, profile_id: int, name: str, criteria: dict[str, object]) -> SavedSearch:
        search = SavedSearch(profile_id=profile_id, name=name, criteria=validate_criteria(criteria))
        self._session.add(search)
        self._session.flush()
        return search

    def update(
        self,
        search: SavedSearch,
        name: str | None = None,
        criteria: dict[str, object] | None = None,
    ) -> SavedSearch:
        if name is not None:
            search.name = name
        if criteria is not None:
            search.criteria = validate_criteria(criteria)
        self._session.flush()
        return search

    def delete(self, search: SavedSearch) -> None:
        self._session.delete(search)
        self._session.flush()

    # -- running ------------------------------------------------------------------------

    def to_query(
        self, search: SavedSearch, profile_id: int, *, since: datetime | None, limit: int
    ) -> JobQuery:
        raw = dict(search.criteria or {})
        validate_criteria(raw)
        query = JobQuery(profile_id=profile_id, limit=limit)
        for key, value in raw.items():
            if key == "statuses":
                query.statuses = [JobStatus(item) for item in _as_str_list(value)]
            elif key == "sources":
                query.sources = [SourceName(item) for item in _as_str_list(value)]
            else:
                setattr(query, key, value)
        query.discovered_after = since
        return query

    def run(
        self,
        search: SavedSearch,
        profile_id: int,
        *,
        limit: int = 50,
        mark_seen: bool = True,
    ) -> DigestResult:
        """Run a saved search and report how much of it is new.

        ``mark_seen`` is a parameter rather than always-on so the page can preview a digest
        without consuming the watermark: moving it on a mere page render would make the
        next visit report zero new matches and lose the only record of what was unseen.
        """
        jobs = JobRepository(self._session)
        previous = search.last_run_at

        total = jobs.count(self.to_query(search, profile_id, since=None, limit=limit))
        # With no previous run every match is new, and the watermark query is the same
        # query, so one code path covers both cases.
        since_query = self.to_query(search, profile_id, since=previous, limit=limit)
        hits = jobs.list(since_query)
        new_count = jobs.count(since_query)

        if mark_seen:
            search.last_run_at = utcnow()
            self._session.flush()

        return DigestResult(
            search_id=search.id,
            name=search.name,
            total_matching=total,
            new_since_last_run=new_count,
            previous_run_at=previous,
            jobs=hits,
        )


def _as_str_list(value: object) -> list[str]:
    """Coerce a stored JSON value into a list of strings.

    The criteria blob comes back from the database as plain JSON, so its types are only
    whatever was written. Coercing here keeps the enum constructors below total instead of
    raising a ``TypeError`` from deep inside a list comprehension.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def criteria_from_query(query: JobQuery) -> dict[str, object]:
    """Project a live job query down to the subset a saved search may store."""
    projected: dict[str, object] = {}
    for key, value in asdict(query).items():
        if key not in ALLOWED_CRITERIA or value in (None, [], ""):
            continue
        if isinstance(value, list):
            projected[key] = [
                item.value if isinstance(item, JobStatus | SourceName) else item for item in value
            ]
        else:
            projected[key] = value
    return projected
