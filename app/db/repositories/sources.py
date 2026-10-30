"""Source configuration, import-run history and audit-log persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, ImportRun, ImportStatus, SourceConfiguration, SourceName


class SourceConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, source: SourceName) -> SourceConfiguration | None:
        return self._session.scalars(
            select(SourceConfiguration).where(SourceConfiguration.source == source)
        ).first()

    def list_all(self) -> list[SourceConfiguration]:
        return list(
            self._session.scalars(select(SourceConfiguration).order_by(SourceConfiguration.source))
        )

    def create(self, config: SourceConfiguration) -> SourceConfiguration:
        self._session.add(config)
        self._session.flush()
        return config

    def update(self, config: SourceConfiguration, changes: dict[str, Any]) -> SourceConfiguration:
        for field_name, value in changes.items():
            if not hasattr(config, field_name):
                raise AttributeError(f"unknown source configuration field: {field_name}")
            setattr(config, field_name, value)
        self._session.flush()
        return config


class ImportRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, run: ImportRun) -> ImportRun:
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: int) -> ImportRun | None:
        return self._session.get(ImportRun, run_id)

    def list_recent(self, limit: int = 50, source: SourceName | None = None) -> list[ImportRun]:
        statement = select(ImportRun).order_by(ImportRun.started_at.desc()).limit(limit)
        if source is not None:
            statement = statement.where(ImportRun.source == source)
        return list(self._session.scalars(statement))

    def totals(self) -> dict[str, int]:
        row = self._session.execute(
            select(
                func.coalesce(func.sum(ImportRun.records_received), 0),
                func.coalesce(func.sum(ImportRun.jobs_created), 0),
                func.coalesce(func.sum(ImportRun.duplicates_detected), 0),
                func.coalesce(func.sum(ImportRun.records_invalid), 0),
            )
        ).one()
        return {
            "records_received": int(row[0]),
            "jobs_created": int(row[1]),
            "duplicates_detected": int(row[2]),
            "records_invalid": int(row[3]),
        }

    def failure_count(self) -> int:
        return int(
            self._session.scalar(
                select(func.count(ImportRun.id)).where(ImportRun.status == ImportStatus.FAILED)
            )
            or 0
        )


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        action: str,
        *,
        entity_type: str = "",
        entity_id: int | None = None,
        actor: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            detail=detail or {},
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def list_recent(
        self, limit: int = 100, offset: int = 0, action: str | None = None
    ) -> list[AuditLog]:
        statement = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        if action:
            statement = statement.where(AuditLog.action == action)
        return list(self._session.scalars(statement.limit(limit).offset(offset)))

    def count(self, action: str | None = None) -> int:
        statement = select(func.count(AuditLog.id))
        if action:
            statement = statement.where(AuditLog.action == action)
        return int(self._session.scalar(statement) or 0)
