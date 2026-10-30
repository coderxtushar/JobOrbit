"""Optional scheduled discovery.

Off unless ``JA_SCHEDULER_ENABLED=true``. Three properties the requirements call for are
enforced here rather than left to chance:

* **No hidden activity.** When disabled, no scheduler object is constructed at all. When
  enabled, every run writes an ``ImportRun`` row, so the Diagnostics page always accounts
  for background work.
* **Bounded retries.** ``MAX_ATTEMPTS`` caps retries and the delay grows exponentially; a
  source that has failed ``FAILURE_CIRCUIT_LIMIT`` times in a row is skipped until its
  error is cleared, so a broken source cannot retry forever.
* **Per-source rate limits.** A source is skipped if its last run was more recent than its
  configured hourly rate allows.
"""

from __future__ import annotations

import time
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings, get_settings
from app.db.base import session_scope
from app.db.models import ImportRun, ImportStatus, utcnow
from app.db.repositories import ImportRunRepository, ProfileRepository, SourceConfigRepository
from app.logging_conf import get_logger
from app.services.ingest import JobIngestService
from app.services.scoring import ScoringService
from app.sources import DISCOVERY_SOURCES, get_adapter
from app.sources.base import CapabilityNotAvailable, SourceUnavailable

logger = get_logger(__name__)

MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 2.0
FAILURE_CIRCUIT_LIMIT = 5

_scheduler: BackgroundScheduler | None = None


def _rate_limit_blocks(config, now) -> bool:
    if config.last_run_at is None:
        return False
    minimum_gap = timedelta(hours=1) / max(config.rate_limit_per_hour, 1)
    return (now - config.last_run_at) < minimum_gap


def run_discovery_once(
    settings: Settings | None = None, trigger: str = "scheduler"
) -> dict[str, str]:
    """Run discovery for every source that permits it. Returns a per-source outcome."""
    settings = settings or get_settings()
    outcomes: dict[str, str] = {}

    for source in DISCOVERY_SOURCES:
        with session_scope() as session:
            configs = SourceConfigRepository(session)
            config = configs.get(source)
            now = utcnow()

            if config is not None and not config.enabled:
                outcomes[source.value] = "skipped: disabled"
                continue
            if config is not None and config.consecutive_failures >= FAILURE_CIRCUIT_LIMIT:
                outcomes[source.value] = (
                    f"skipped: {config.consecutive_failures} consecutive failures; "
                    "clear the error on the Settings page to resume"
                )
                continue
            if config is not None and _rate_limit_blocks(config, now):
                outcomes[source.value] = "skipped: rate limit"
                continue

            adapter = get_adapter(source, settings)
            runs = ImportRunRepository(session)
            run = runs.create(
                ImportRun(source=source, trigger=trigger, status=ImportStatus.RUNNING)
            )

            result = None
            last_error = ""
            for attempt in range(1, MAX_ATTEMPTS + 1):
                run.attempts = attempt
                try:
                    result = adapter.discover()
                    break
                except CapabilityNotAvailable as exc:
                    run.status = ImportStatus.SKIPPED_UNSUPPORTED
                    run.finished_at = utcnow()
                    run.message = exc.reason
                    run.errors = [exc.reason]
                    outcomes[source.value] = f"skipped: {exc.reason[:120]}"
                    last_error = exc.reason
                    break
                except SourceUnavailable as exc:
                    last_error = exc.reason
                    if not exc.retryable or attempt == MAX_ATTEMPTS:
                        break
                    delay = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "discovery attempt failed; backing off",
                        extra={"source": source.value, "attempt": attempt, "delay": delay},
                    )
                    time.sleep(delay)

            if result is None:
                if run.status is ImportStatus.RUNNING:
                    run.status = ImportStatus.FAILED
                    run.finished_at = utcnow()
                    run.message = last_error or "discovery failed"
                    run.errors = [last_error or "discovery failed"]
                    outcomes.setdefault(source.value, f"failed: {last_error[:120]}")
                if config is not None:
                    config.last_run_at = now
                    config.last_error = last_error[:1000]
                    config.consecutive_failures += 1
                continue

            report = JobIngestService(session).ingest(
                result.records,
                source=source,
                trigger=trigger,
                invalid_count=result.invalid_count,
                adapter_errors=result.errors,
                import_run=run,
                run_metadata=dict(result.metadata),
            )
            if config is not None:
                config.last_run_at = now
                config.last_error = ""
                config.consecutive_failures = 0
            outcomes[source.value] = report.message

            if report.jobs_created:
                profile = ProfileRepository(session).get_default()
                if profile is not None:
                    ScoringService(session).score_many(profile, job_ids=report.created_job_ids)

    logger.info("scheduled discovery finished", extra={"outcomes": outcomes})
    return outcomes


def start(settings: Settings | None = None) -> BackgroundScheduler | None:
    """Start the scheduler if enabled. Returns ``None`` when disabled."""
    global _scheduler
    settings = settings or get_settings()
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled; no background discovery will run")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_discovery_once,
        trigger="interval",
        minutes=settings.discovery_interval_minutes,
        id="discovery",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "scheduler started",
        extra={
            "interval_minutes": settings.discovery_interval_minutes,
            "sources": [source.value for source in DISCOVERY_SOURCES],
        },
    )
    return scheduler


def shutdown() -> None:
    """Stop the scheduler, waiting for a running job to finish."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("scheduler stopped")
