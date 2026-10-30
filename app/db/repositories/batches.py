"""Batch run persistence.

Every state change a batch makes is written here before the next item starts, so the rows
in ``batch_run_item`` are the run's checkpoints. A process killed mid-run leaves a
``RUNNING`` row whose items are partly terminal; :meth:`BatchRunRepository.mark_interrupted`
reconciles that on the next startup and the remaining ``QUEUED`` items can be resumed.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    BatchItemStatus,
    BatchRun,
    BatchRunItem,
    BatchStatus,
    utcnow,
)

#: Work that will not be repeated by a resume. ``CANCELLED`` is deliberately absent: a
#: cancelled item was never attempted, so resuming a cancelled run must pick it up again.
#: Treating it as terminal made the Resume action impossible on exactly the runs that need
#: it most.
TERMINAL_ITEM_STATUSES: frozenset[BatchItemStatus] = frozenset(
    {
        BatchItemStatus.PREPARED,
        BatchItemStatus.NEEDS_ACTION,
        BatchItemStatus.SKIPPED_DUPLICATE,
        BatchItemStatus.SKIPPED_INELIGIBLE,
    }
)

#: Alias used for return annotations inside the class below. The class defines a
#: method called ``list``, which shadows the builtin inside the class body and makes
#: a bare ``list[X]`` annotation resolve to that method instead of the generic type.
BatchRunList = list[BatchRun]
BatchItemList = list[BatchRunItem]
JobIdList = list[int]

TERMINAL_RUN_STATUSES: frozenset[BatchStatus] = frozenset(
    {
        BatchStatus.CANCELLED,
        BatchStatus.COMPLETED,
        BatchStatus.COMPLETED_WITH_ERRORS,
        BatchStatus.FAILED,
    }
)


class BatchRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, run: BatchRun) -> BatchRun:
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: int) -> BatchRun | None:
        return self._session.get(BatchRun, run_id)

    def list(self, *, limit: int = 20, offset: int = 0) -> BatchRunList:
        return list(
            self._session.scalars(
                select(BatchRun).order_by(BatchRun.started_at.desc()).limit(limit).offset(offset)
            ).unique()
        )

    def count(self) -> int:
        return int(self._session.scalar(select(func.count(BatchRun.id))) or 0)

    def active(self) -> BatchRun | None:
        return self._session.scalars(
            select(BatchRun)
            .where(BatchRun.status.in_([BatchStatus.RUNNING, BatchStatus.CANCELLING]))
            .order_by(BatchRun.started_at.desc())
        ).first()

    def add_items(self, run: BatchRun, job_ids: JobIdList) -> BatchItemList:
        """Queue jobs, ignoring any already recorded in this run."""
        known = {
            item.job_id
            for item in self._session.scalars(
                select(BatchRunItem).where(BatchRunItem.batch_run_id == run.id)
            )
        }
        created: list[BatchRunItem] = []
        for job_id in job_ids:
            if job_id in known:
                continue
            known.add(job_id)
            item = BatchRunItem(batch_run_id=run.id, job_id=job_id)
            self._session.add(item)
            created.append(item)
        self._session.flush()
        run.total_items = int(
            self._session.scalar(
                select(func.count(BatchRunItem.id)).where(BatchRunItem.batch_run_id == run.id)
            )
            or 0
        )
        self._session.flush()
        return created

    def pending_items(self, run_id: int) -> BatchItemList:
        return list(
            self._session.scalars(
                select(BatchRunItem)
                .where(
                    BatchRunItem.batch_run_id == run_id,
                    BatchRunItem.status.notin_(TERMINAL_ITEM_STATUSES),
                )
                .order_by(BatchRunItem.id)
            )
        )

    def items(self, run_id: int, *, limit: int = 500) -> BatchItemList:
        return list(
            self._session.scalars(
                select(BatchRunItem)
                .where(BatchRunItem.batch_run_id == run_id)
                .order_by(BatchRunItem.id)
                .limit(limit)
            )
        )

    def item_status_counts(self, run_id: int) -> dict[str, int]:
        rows = self._session.execute(
            select(BatchRunItem.status, func.count(BatchRunItem.id))
            .where(BatchRunItem.batch_run_id == run_id)
            .group_by(BatchRunItem.status)
        ).all()
        return {status.value: count for status, count in rows}

    def request_cancel(self, run: BatchRun) -> BatchRun:
        run.cancel_requested = True
        if run.status is BatchStatus.RUNNING:
            run.status = BatchStatus.CANCELLING
        self._session.flush()
        return run

    def clear_cancel(self, run: BatchRun) -> BatchRun:
        """Withdraw a cancel request. Only a resume does this, never a plain execute."""
        run.cancel_requested = False
        self._session.flush()
        return run

    def cancel_requested(self, run_id: int) -> bool:
        """Read the flag straight from the database.

        The worker must not trust an ORM copy here: the cancel request is written by the
        API thread in a different session, so a cached attribute would never show it.
        """
        return bool(
            self._session.scalar(select(BatchRun.cancel_requested).where(BatchRun.id == run_id))
        )

    def refresh_counts(self, run: BatchRun) -> BatchRun:
        counts = self.item_status_counts(run.id)
        run.prepared_count = counts.get(BatchItemStatus.PREPARED.value, 0)
        run.needs_action_count = counts.get(BatchItemStatus.NEEDS_ACTION.value, 0)
        run.skipped_count = counts.get(BatchItemStatus.SKIPPED_DUPLICATE.value, 0) + counts.get(
            BatchItemStatus.SKIPPED_INELIGIBLE.value, 0
        )
        run.failed_count = counts.get(BatchItemStatus.FAILED.value, 0)
        self._session.flush()
        return run

    def finish(self, run: BatchRun, status: BatchStatus, message: str = "") -> BatchRun:
        self.refresh_counts(run)
        run.status = status
        run.message = message
        run.finished_at = utcnow()
        self._session.flush()
        return run

    def mark_interrupted(self) -> int:
        """Reconcile runs left ``RUNNING`` by a killed process. Returns how many."""
        run_ids = list(
            self._session.scalars(
                select(BatchRun.id).where(
                    BatchRun.status.in_([BatchStatus.RUNNING, BatchStatus.CANCELLING])
                )
            )
        )
        if not run_ids:
            return 0
        self._session.execute(
            update(BatchRunItem)
            .where(
                BatchRunItem.batch_run_id.in_(run_ids),
                BatchRunItem.status == BatchItemStatus.IN_PROGRESS,
            )
            .values(status=BatchItemStatus.QUEUED, started_at=None)
        )
        self._session.execute(
            update(BatchRun)
            .where(BatchRun.id.in_(run_ids))
            .values(
                status=BatchStatus.INTERRUPTED,
                message="the process stopped while this run was active; it can be resumed",
            )
        )
        self._session.flush()
        return len(run_ids)
