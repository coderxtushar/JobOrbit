"""Archive listings older than the person's own age limit.

The matcher already rejects a listing posted before ``max_job_age_days``; archiving marks
it EXPIRED so it also leaves the job list, saved searches and bulk selection. It is a
status change, not a deletion: the listing, its score and its history stay, and the job
list shows it again under the Expired status.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import utcnow
from app.db.repositories import JobRepository, ProfileRepository
from app.logging_conf import get_logger

logger = get_logger(__name__)


def archive_stale_jobs(session: Session, now: datetime | None = None) -> int:
    """Expire dated listings past the age limit; return the count.

    Locally the limit is the one person's ``max_job_age_days``. In hosted mode jobs are
    shared, so one person's limit must not hide listings from everyone else: the
    installation-wide ``JA_ARCHIVE_AFTER_DAYS`` applies, and each person's own limit still
    filters their matches.
    """
    settings = get_settings()
    if settings.is_multi_user:
        max_age = settings.archive_after_days
    else:
        profile = ProfileRepository(session).get_default()
        if profile is None:
            return 0
        max_age = profile.max_job_age_days
    cutoff = (now or utcnow()) - timedelta(days=max_age)
    archived = JobRepository(session).mark_expired_before(cutoff)
    if archived:
        logger.info(
            "archived stale listings", extra={"archived": archived, "max_age_days": max_age}
        )
    return archived
