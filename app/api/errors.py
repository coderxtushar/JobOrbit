"""Error handling.

Every error leaves the API as the same JSON shape. Unhandled exceptions are logged with
their traceback server-side and returned as a generic message with a correlation id, so a
client never receives a stack trace, a SQL string, or resume content.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.repositories import DuplicateApplicationError
from app.logging_conf import get_logger
from app.schemas.common import ErrorDetail, ErrorResponse
from app.services.resume_parser import ResumeExtractionError
from app.services.storage import CorruptUpload, FileTooLarge, UnsupportedFileType
from app.services.tracking import AutomatedSubmissionBlocked, InvalidTransition
from app.sources.base import CapabilityNotAvailable, SourceUnavailable

logger = get_logger(__name__)


class ApiError(Exception):
    """Raised by routes for an expected, user-facing failure."""

    def __init__(
        self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _envelope(
    code: str, message: str, http_status: int, field_errors: dict | None = None
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, field_errors=field_errors or {})
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.code, exc.message, exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors: dict[str, list[str]] = {}
        for detail in exc.errors():
            location = ".".join(str(part) for part in detail.get("loc", ()) if part != "body")
            field_errors.setdefault(location or "body", []).append(
                str(detail.get("msg", "invalid value"))
            )
        return _envelope(
            "validation_error",
            "The request body or query parameters failed validation.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            field_errors,
        )

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return _envelope("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(DuplicateApplicationError)
    async def _duplicate_application(_: Request, exc: DuplicateApplicationError) -> JSONResponse:
        return _envelope("duplicate_application", str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(InvalidTransition)
    async def _invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
        return _envelope("invalid_transition", str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(AutomatedSubmissionBlocked)
    async def _submission_blocked(_: Request, exc: AutomatedSubmissionBlocked) -> JSONResponse:
        return _envelope("automated_submission_blocked", str(exc), status.HTTP_403_FORBIDDEN)

    @app.exception_handler(CapabilityNotAvailable)
    async def _capability(_: Request, exc: CapabilityNotAvailable) -> JSONResponse:
        return _envelope(
            "capability_not_available", exc.reason, status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    @app.exception_handler(SourceUnavailable)
    async def _source_unavailable(_: Request, exc: SourceUnavailable) -> JSONResponse:
        return _envelope("source_unavailable", exc.reason, status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(UnsupportedFileType)
    async def _unsupported_file(_: Request, exc: UnsupportedFileType) -> JSONResponse:
        return _envelope("unsupported_file_type", str(exc), status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    @app.exception_handler(FileTooLarge)
    async def _file_too_large(_: Request, exc: FileTooLarge) -> JSONResponse:
        return _envelope("file_too_large", str(exc), status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    @app.exception_handler(CorruptUpload)
    async def _corrupt_upload(_: Request, exc: CorruptUpload) -> JSONResponse:
        return _envelope("corrupt_upload", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(ResumeExtractionError)
    async def _resume_extraction(_: Request, exc: ResumeExtractionError) -> JSONResponse:
        return _envelope("resume_unreadable", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        reference = secrets.token_hex(4)
        logger.warning("database constraint violated", extra={"reference": reference})
        return _envelope(
            "constraint_violation",
            f"The change conflicts with an existing record. Reference {reference}.",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(SQLAlchemyError)
    async def _database(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        reference = secrets.token_hex(4)
        logger.exception("database error", extra={"reference": reference})
        return _envelope(
            "database_error",
            f"A database error occurred. Reference {reference}.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        reference = secrets.token_hex(4)
        logger.exception("unhandled error", extra={"reference": reference})
        return _envelope(
            "internal_error",
            f"An unexpected error occurred. Reference {reference} is in the application log.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
