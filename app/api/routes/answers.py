"""Answer bank and action inbox endpoints.

The action inbox is the mechanism that makes a hundred-job run tractable: one question
answered once is pushed onto every open application that was waiting for it. Nothing here
can set an answer the user did not supply — ``PUT`` records what the request body contains
and marks it ``user_entered``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import Authorized, DbSession, Profile
from app.api.errors import ApiError
from app.db.repositories import SavedAnswerRepository, UnbankableAnswerError
from app.schemas.batch import (
    InboxEntryRead,
    ResolveResponse,
    SavedAnswerRead,
    SavedAnswerWrite,
)
from app.services.answer_bank import AnswerBankService

router = APIRouter(prefix="/api/answers", tags=["answers"], dependencies=[Authorized])


@router.get("", response_model=list[SavedAnswerRead], summary="Every reusable saved answer")
def list_answers(session: DbSession, profile: Profile) -> list[SavedAnswerRead]:
    return [
        SavedAnswerRead.model_validate(entry) for entry in AnswerBankService(session).list(profile)
    ]


@router.get(
    "/inbox",
    response_model=list[InboxEntryRead],
    summary="Questions still waiting on you, grouped and counted",
)
def action_inbox(
    session: DbSession,
    profile: Profile,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[InboxEntryRead]:
    service = AnswerBankService(session)
    banked = set(SavedAnswerRepository(session).as_map(profile.id))
    return [
        InboxEntryRead(
            question_key=entry.question_key,
            question=entry.question,
            is_sensitive=entry.is_sensitive,
            occurrences=entry.occurrences,
            has_saved_answer=entry.question_key in banked,
            application_ids=entry.application_ids,
        )
        for entry in service.inbox(profile, limit=limit)
    ]


@router.put(
    "/{question_key}",
    response_model=ResolveResponse,
    summary="Answer a question once and apply it to every open application",
)
def save_answer(
    question_key: str,
    payload: SavedAnswerWrite,
    session: DbSession,
    profile: Profile,
) -> ResolveResponse:
    try:
        result = AnswerBankService(session).resolve_from_inbox(
            profile,
            question_key=question_key,
            answer=payload.answer,
            question=payload.question,
            apply_to_open_applications=payload.apply_to_open_applications,
        )
    except UnbankableAnswerError as exc:
        raise ApiError("unbankable_answer", str(exc), status.HTTP_400_BAD_REQUEST) from exc
    except ValueError as exc:
        raise ApiError("invalid_answer", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc

    return ResolveResponse(
        question_key=result.question_key,
        applications_updated=result.applications_updated,
        answer=SavedAnswerRead.model_validate(result.saved),
    )


@router.delete(
    "/{question_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Forget a saved answer",
)
def delete_answer(question_key: str, session: DbSession, profile: Profile) -> Response:
    if not AnswerBankService(session).delete(profile, question_key):
        raise ApiError(
            "not_found",
            f"No saved answer for '{question_key}'.",
            status.HTTP_404_NOT_FOUND,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
