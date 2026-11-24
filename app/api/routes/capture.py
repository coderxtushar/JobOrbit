"""User-initiated job capture from the browser extension.

The extension posts one listing the user clicked "Send to JobOrbit" on. It enters the same
ingestion pipeline as ``POST /api/jobs/import`` (deduplicated, provenance recorded) and is
scored immediately so the popup can show the result. Nothing here fetches a page, and
there is no endpoint that applies to a job.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.api.deps import AppSettings, Authorized, DbSession, Profile, refuse_in_demo_mode
from app.api.errors import ApiError
from app.schemas.capture import CaptureRequest, CaptureResult, CaptureStatus
from app.services.capture import CaptureService

router = APIRouter(prefix="/api/capture", tags=["capture"], dependencies=[Authorized])


@router.get("/status", response_model=CaptureStatus, summary="Is JobOrbit reachable for capture")
def capture_status(settings: AppSettings) -> CaptureStatus:
    """Cheap reachability check. No database access, no personal data.

    Protected like every other route: when a token is configured, a request without it is
    answered 401, which is itself how the extension learns that a token is needed.
    """
    return CaptureStatus(
        version=__version__,
        token_required=bool(settings.api_token),
        demo_mode=settings.demo_mode,
        capture_enabled=not settings.demo_mode,
    )


@router.post(
    "/job",
    response_model=CaptureResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest and score one listing captured by the browser extension",
)
def capture_job(
    payload: CaptureRequest,
    response: Response,
    session: DbSession,
    profile: Profile,
    settings: AppSettings,
) -> CaptureResult:
    """201 when the listing is new, 200 when it matched a job JobOrbit already holds."""
    refuse_in_demo_mode(settings, "job_capture")
    try:
        result = CaptureService(session).capture(payload, profile)
    except ValueError as exc:
        raise ApiError(
            "capture_rejected", str(exc)[:500], status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result
