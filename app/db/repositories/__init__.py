"""Repository layer.

Every database query in the application is defined in this package. Services and API
routes depend on these classes, not on SQLAlchemy, which is what allows the storage
backend to change without touching business logic.
"""

from app.db.repositories.answers import (
    InboxEntry,
    SavedAnswerRepository,
    UnbankableAnswerError,
)
from app.db.repositories.applications import (
    ApplicationQuery,
    ApplicationRepository,
    DuplicateApplicationError,
)
from app.db.repositories.batches import BatchRunRepository
from app.db.repositories.jobs import JobQuery, JobRepository
from app.db.repositories.matches import MatchRepository
from app.db.repositories.profile import ProfileRepository
from app.db.repositories.resumes import ResumeRepository, ResumeVariantRepository
from app.db.repositories.sources import (
    AuditRepository,
    ImportRunRepository,
    SourceConfigRepository,
)

__all__ = [
    "ApplicationQuery",
    "ApplicationRepository",
    "AuditRepository",
    "BatchRunRepository",
    "DuplicateApplicationError",
    "ImportRunRepository",
    "InboxEntry",
    "JobQuery",
    "JobRepository",
    "MatchRepository",
    "ProfileRepository",
    "ResumeRepository",
    "ResumeVariantRepository",
    "SavedAnswerRepository",
    "SourceConfigRepository",
    "UnbankableAnswerError",
]
