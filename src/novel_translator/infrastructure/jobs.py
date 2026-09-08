"""SQLite repository for durable translation jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Index, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError as SqlalchemyIntegrityError
from sqlalchemy.orm import Mapped, deferred, mapped_column, undefer

from novel_translator.application.jobs import TranslationJobStore
from novel_translator.domain.errors import IntegrityError
from novel_translator.domain.jobs import (
    ACTIVE_JOB_STATUSES,
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.working_copies import Base


class TranslationJobRow(Base):
    """One queued or terminal translation job row."""

    __tablename__ = "translation_jobs"
    __table_args__ = (Index("ix_translation_jobs_status", "status"),)

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str | None] = mapped_column(String(32))
    novel: Mapped[str] = mapped_column(String(128))
    chapter: Mapped[int] = mapped_column(Integer())
    volume: Mapped[int | None] = mapped_column(Integer())
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    segment_limit: Mapped[int] = mapped_column(Integer())
    source_kind: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(Text())
    source_text: Mapped[str | None] = deferred(mapped_column(Text()))
    parent_job_id: Mapped[str | None] = mapped_column(String(32))
    progress_current: Mapped[int] = mapped_column(Integer())
    progress_total: Mapped[int] = mapped_column(Integer())
    attempt: Mapped[int] = mapped_column(Integer())
    created_at: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[str | None] = mapped_column(String(64))
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text())
    cancel_requested: Mapped[bool] = mapped_column()


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


class SqlAlchemyTranslationJobRepository(TranslationJobStore):
    """Persist translation jobs with atomic queue claims.

    ``list_recent`` returns summaries with ``source_text`` unset so
    dashboards, job lists, and recovery scans never materialize
    megabyte upload payloads; ``get`` loads the complete job.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, job: TranslationJob) -> TranslationJob:
        """Persist one new queued job."""
        with self._database.session() as session:
            session.add(self._to_row(job))
            try:
                session.commit()
            except SqlalchemyIntegrityError as error:
                raise IntegrityError(
                    "A translation job already exists."
                ) from error
        created = self.get(job.job_id)
        if created is None:
            raise IntegrityError("Translation job disappeared after insert.")
        return created

    def get(self, job_id: str) -> TranslationJob | None:
        """Return one complete job by identifier, if present."""
        with self._database.session() as session:
            row = session.scalar(
                select(TranslationJobRow)
                .where(TranslationJobRow.job_id == job_id)
                .options(undefer(TranslationJobRow.source_text))
            )
            return None if row is None else self._to_job(row)

    def find_active(self, novel: str, chapter: int) -> TranslationJob | None:
        """Return the newest non-terminal job for one chapter, if any."""
        with self._database.session() as session:
            row = session.scalar(
                select(TranslationJobRow)
                .where(
                    TranslationJobRow.novel == novel,
                    TranslationJobRow.chapter == chapter,
                    TranslationJobRow.status.in_(
                        [status.value for status in ACTIVE_JOB_STATUSES]
                    ),
                )
                .order_by(TranslationJobRow.created_at.desc())
                .limit(1)
            )
            return None if row is None else self._to_summary(row)

    def list_recent(self, limit: int = 50) -> list[TranslationJob]:
        """Return the newest job summaries first, up to the limit."""
        with self._database.session() as session:
            rows = session.scalars(
                select(TranslationJobRow)
                .order_by(TranslationJobRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._to_summary(row) for row in rows]

    def claim_queued(self) -> TranslationJob | None:
        """Atomically move the oldest queued job to running."""
        claimed_at = _now_iso()
        skipped: list[str] = []
        with self._database.session() as session:
            while True:
                query = select(TranslationJobRow.job_id).where(
                    TranslationJobRow.status == JobStatus.QUEUED.value
                )
                if skipped:
                    query = query.where(
                        TranslationJobRow.job_id.notin_(skipped)
                    )
                candidate = session.scalar(
                    query.order_by(TranslationJobRow.created_at.asc()).limit(1)
                )
                if candidate is None:
                    return None
                statement = (
                    update(TranslationJobRow)
                    .where(
                        TranslationJobRow.job_id == candidate,
                        TranslationJobRow.status == JobStatus.QUEUED.value,
                    )
                    .values(
                        status=JobStatus.RUNNING.value,
                        started_at=claimed_at,
                        heartbeat_at=claimed_at,
                    )
                )
                result = cast(CursorResult[Any], session.execute(statement))
                if result.rowcount == 1:
                    session.commit()
                    row = session.get(TranslationJobRow, candidate)
                    if row is None:
                        raise IntegrityError(
                            "Claimed job disappeared after update."
                        )
                    return self._to_job(row)
                session.rollback()
                skipped.append(candidate)

    def heartbeat(self, job_id: str, at: str | None = None) -> None:
        """Refresh the heartbeat of a running job only."""
        statement = (
            update(TranslationJobRow)
            .where(
                TranslationJobRow.job_id == job_id,
                TranslationJobRow.status == JobStatus.RUNNING.value,
            )
            .values(heartbeat_at=at or _now_iso())
        )
        with self._database.session() as session:
            session.execute(statement)
            session.commit()

    def update_progress(self, job_id: str, current: int, total: int) -> None:
        """Persist segment counters while the job is still active."""
        statement = (
            update(TranslationJobRow)
            .where(
                TranslationJobRow.job_id == job_id,
                TranslationJobRow.status.in_(
                    [
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    ]
                ),
            )
            .values(progress_current=current, progress_total=total)
        )
        with self._database.session() as session:
            session.execute(statement)
            session.commit()

    def finish(self, job_id: str, run_id: str) -> TranslationJob:
        """Mark one running job succeeded with its run identifier."""
        return self._transition(
            job_id,
            {JobStatus.RUNNING},
            status=JobStatus.SUCCEEDED.value,
            run_id=run_id,
            completed_at=_now_iso(),
        )

    def fail(
        self, job_id: str, error_type: str, error_message: str
    ) -> TranslationJob:
        """Mark one active job failed with safe error metadata."""
        return self._transition(
            job_id,
            {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED},
            status=JobStatus.FAILED.value,
            error_type=error_type,
            error_message=error_message,
            completed_at=_now_iso(),
        )

    def interrupt(self, job_id: str) -> TranslationJob:
        """Mark one active job interrupted without recording an error."""
        return self._transition(
            job_id,
            {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED},
            status=JobStatus.INTERRUPTED.value,
            completed_at=_now_iso(),
        )

    def mark_cancelled(self, job_id: str) -> TranslationJob:
        """Mark one unsettled job cancelled after a confirmed request."""
        return self._transition(
            job_id,
            {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.CANCEL_REQUESTED,
            },
            status=JobStatus.CANCELLED.value,
            completed_at=_now_iso(),
        )

    def request_cancel(self, job_id: str) -> TranslationJob:
        """Flag one running job for cooperative cancellation."""
        return self._transition(
            job_id,
            {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED},
            status=JobStatus.CANCEL_REQUESTED.value,
            cancel_requested=True,
        )

    def retry_source(self, job_id: str) -> TranslationJob:
        """Enqueue one queued child copying the given job."""
        with self._database.session() as session:
            row = session.get(TranslationJobRow, job_id)
            if row is None:
                raise IntegrityError("Unknown translation job.")
            source = self._to_job(row)
        child = TranslationJob(
            job_id=uuid4().hex,
            status=JobStatus.QUEUED,
            novel=source.novel,
            chapter=source.chapter,
            provider=source.provider,
            model=source.model,
            segment_limit=source.segment_limit,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
            job_type=source.job_type,
            volume=source.volume,
            source_text=source.source_text,
            parent_job_id=source.job_id,
            attempt=source.attempt + 1,
            created_at=_now_iso(),
        )
        return self.create(child)

    def _transition(
        self,
        job_id: str,
        allowed: set[JobStatus],
        **values: object,
    ) -> TranslationJob:
        """Apply one status change only from an expected source status."""
        statement = (
            update(TranslationJobRow)
            .where(
                TranslationJobRow.job_id == job_id,
                TranslationJobRow.status.in_(
                    [status.value for status in allowed]
                ),
            )
            .values(**values)
        )
        with self._database.session() as session:
            result = cast(CursorResult[Any], session.execute(statement))
            if result.rowcount != 1:
                session.rollback()
                raise IntegrityError(
                    "Translation job changed state concurrently."
                )
            session.commit()
        updated = self.get(job_id)
        if updated is None:
            raise IntegrityError("Translation job disappeared after update.")
        return updated

    def _to_row(self, job: TranslationJob) -> TranslationJobRow:
        """Convert one domain job into its persistence row."""
        return TranslationJobRow(
            job_id=job.job_id,
            job_type=job.job_type,
            status=job.status.value,
            run_id=job.run_id,
            novel=job.novel,
            chapter=job.chapter,
            volume=job.volume,
            provider=job.provider,
            model=job.model,
            segment_limit=job.segment_limit,
            source_kind=job.source_kind.value,
            source_ref=job.source_ref,
            source_text=job.source_text,
            parent_job_id=job.parent_job_id,
            progress_current=job.progress_current,
            progress_total=job.progress_total,
            attempt=job.attempt,
            created_at=job.created_at,
            started_at=job.started_at,
            heartbeat_at=job.heartbeat_at,
            completed_at=job.completed_at,
            error_type=job.error_type,
            error_message=job.error_message,
            cancel_requested=job.cancel_requested,
        )

    def _to_job(self, row: TranslationJobRow) -> TranslationJob:
        """Convert one row into its typed domain value."""
        return self._assemble(row, row.source_text)

    def _to_summary(self, row: TranslationJobRow) -> TranslationJob:
        """Convert one row without materializing its source payload."""
        return self._assemble(row, None)

    def _assemble(
        self, row: TranslationJobRow, source_text: str | None
    ) -> TranslationJob:
        """Build one typed job from a row and an explicit payload."""
        try:
            status = JobStatus(row.status)
        except ValueError as error:
            raise IntegrityError(
                "Translation job status is invalid."
            ) from error
        try:
            source_kind = JobSourceKind(row.source_kind)
        except ValueError as error:
            raise IntegrityError(
                "Translation job source kind is invalid."
            ) from error
        return TranslationJob(
            job_id=row.job_id,
            status=status,
            novel=row.novel,
            chapter=row.chapter,
            provider=row.provider,
            model=row.model,
            segment_limit=row.segment_limit,
            source_kind=source_kind,
            source_ref=row.source_ref,
            job_type=row.job_type,
            run_id=row.run_id,
            volume=row.volume,
            source_text=source_text,
            parent_job_id=row.parent_job_id,
            progress_current=row.progress_current,
            progress_total=row.progress_total,
            attempt=row.attempt,
            created_at=row.created_at,
            started_at=row.started_at,
            heartbeat_at=row.heartbeat_at,
            completed_at=row.completed_at,
            error_type=row.error_type,
            error_message=row.error_message,
            cancel_requested=row.cancel_requested,
        )
