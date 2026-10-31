"""Saved-search endpoints and the on-demand new-match digest.

The digest is pull-only by design. Streamlit Community Cloud offers no guarantee that a
background worker keeps running, and a scheduler that silently stops is worse than no
scheduler: the user would believe they were being alerted while nothing ran. Running a
search is therefore an explicit request, and ``POST /{id}/run`` is the only thing that
advances the "last looked" watermark.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import Authorized, DbSession, Profile
from app.api.errors import ApiError
from app.api.routes.jobs import to_job_read
from app.db.models import SavedSearch
from app.db.repositories import SavedSearchRepository, UnknownCriterionError
from app.schemas.search import (
    SavedSearchCreate,
    SavedSearchDigest,
    SavedSearchRead,
    SavedSearchUpdate,
)

router = APIRouter(prefix="/api/searches", tags=["searches"], dependencies=[Authorized])

SavedSearchReadList = list[SavedSearchRead]


def _load(session: DbSession, profile: Profile, search_id: int) -> SavedSearch:
    search = SavedSearchRepository(session).get(search_id, profile.id)
    if search is None:
        raise ApiError(
            "not_found", f"No saved search with id {search_id}.", status.HTTP_404_NOT_FOUND
        )
    return search


@router.get("", response_model=SavedSearchReadList, summary="Every saved search")
def list_searches(session: DbSession, profile: Profile) -> SavedSearchReadList:
    return [
        SavedSearchRead.model_validate(entry)
        for entry in SavedSearchRepository(session).list(profile.id)
    ]


@router.post(
    "",
    response_model=SavedSearchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save a named set of feed criteria",
)
def create_search(
    payload: SavedSearchCreate, session: DbSession, profile: Profile
) -> SavedSearchRead:
    repository = SavedSearchRepository(session)
    if repository.get_by_name(payload.name, profile.id) is not None:
        raise ApiError(
            "duplicate_search",
            f"A saved search named '{payload.name}' already exists.",
            status.HTTP_409_CONFLICT,
        )
    try:
        created = repository.create(profile.id, payload.name, payload.criteria.to_storage())
    except UnknownCriterionError as exc:
        raise ApiError("invalid_criteria", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    return SavedSearchRead.model_validate(created)


@router.patch(
    "/{search_id}", response_model=SavedSearchRead, summary="Rename or re-filter a saved search"
)
def update_search(
    search_id: int, payload: SavedSearchUpdate, session: DbSession, profile: Profile
) -> SavedSearchRead:
    search = _load(session, profile, search_id)
    try:
        updated = SavedSearchRepository(session).update(
            search,
            name=payload.name,
            criteria=payload.criteria.to_storage() if payload.criteria is not None else None,
        )
    except UnknownCriterionError as exc:
        raise ApiError("invalid_criteria", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    return SavedSearchRead.model_validate(updated)


@router.delete(
    "/{search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a saved search",
)
def delete_search(search_id: int, session: DbSession, profile: Profile) -> Response:
    SavedSearchRepository(session).delete(_load(session, profile, search_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{search_id}/preview",
    response_model=SavedSearchDigest,
    summary="See what a saved search would return without consuming the watermark",
)
def preview_search(
    search_id: int,
    session: DbSession,
    profile: Profile,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SavedSearchDigest:
    return _digest(session, profile, search_id, limit=limit, mark_seen=False)


@router.post(
    "/{search_id}/run",
    response_model=SavedSearchDigest,
    summary="Run a saved search and mark its results as seen",
)
def run_search(
    search_id: int,
    session: DbSession,
    profile: Profile,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SavedSearchDigest:
    return _digest(session, profile, search_id, limit=limit, mark_seen=True)


def _digest(
    session: DbSession, profile: Profile, search_id: int, *, limit: int, mark_seen: bool
) -> SavedSearchDigest:
    search = _load(session, profile, search_id)
    try:
        result = SavedSearchRepository(session).run(
            search, profile.id, limit=limit, mark_seen=mark_seen
        )
    except (UnknownCriterionError, ValueError) as exc:
        raise ApiError("invalid_criteria", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    return SavedSearchDigest(
        search_id=result.search_id,
        name=result.name,
        total_matching=result.total_matching,
        new_since_last_run=result.new_since_last_run,
        previous_run_at=result.previous_run_at,
        jobs=[to_job_read(job, session, profile.id) for job in result.jobs],
    )
