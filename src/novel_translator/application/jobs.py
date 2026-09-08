"""Durable translation job queue use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import uuid4

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.jobs import (
    TERMINAL_JOB_STATUSES,
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.domain.translation import DEFAULT_SEGMENT_LIMIT

MAX_SOURCE_TEXT_CHARS: Final[int] = 1_000_000
"""Largest upload payload accepted into the job queue."""

RETRYABLE_JOB_STATUSES: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.CANCELLED}
)
"""Job states that may seed one retry child job."""


class TranslationJobStore(Protocol):
    """Persistence contract for durable translation jobs."""

    def create(self, job: TranslationJob) -> TranslationJob:
        """Persist one new queued job."""
        ...

    def get(self, job_id: str) -> TranslationJob | None:
        """Return one job by identifier, if present."""
        ...

    def find_active(self, novel: str, chapter: int) -> TranslationJob | None:
        """Return the newest non-terminal job for one chapter, if any."""
        ...

    def list_recent(self, limit: int = 50) -> list[TranslationJob]:
        """Return the newest jobs first, up to the given limit."""
        ...

    def claim_queued(self) -> TranslationJob | None:
        """Atomically move the oldest queued job to running."""
        ...

    def heartbeat(self, job_id: str, at: str | None = None) -> None:
        """Refresh the heartbeat of a running job."""
        ...

    def update_progress(self, job_id: str, current: int, total: int) -> None:
        """Persist the latest segment progress counters."""
        ...

    def finish(self, job_id: str, run_id: str) -> TranslationJob:
        """Mark one job succeeded with its persisted run identifier."""
        ...

    def fail(
        self, job_id: str, error_type: str, error_message: str
    ) -> TranslationJob:
        """Mark one job failed with safe, truncated error metadata."""
        ...

    def interrupt(self, job_id: str) -> TranslationJob:
        """Mark one job interrupted without recording an error."""
        ...

    def mark_cancelled(self, job_id: str) -> TranslationJob:
        """Mark one job cancelled after a confirmed cancel request."""
        ...

    def request_cancel(self, job_id: str) -> TranslationJob:
        """Flag one active job for cooperative cancellation."""
        ...

    def retry_source(self, job_id: str) -> TranslationJob:
        """Enqueue one queued child copying the given job parameters."""
        ...


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


def _existing(store: TranslationJobStore, job_id: str) -> TranslationJob:
    """Return one stored job or fail with a typed error."""
    job = store.get(job_id)
    if job is None:
        raise ValidationError("Unknown translation job.")
    return job


@dataclass(frozen=True, slots=True)
class EnqueueTranslationInput:
    """Parameters for one new queued translation job."""

    novel: str
    chapter: int
    provider: str
    model: str
    source_kind: JobSourceKind
    source_ref: str
    volume: int | None = None
    segment_limit: int = DEFAULT_SEGMENT_LIMIT
    source_text: str | None = None
    parent_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class GetTranslationJobInput:
    """Select one translation job by identifier."""

    job_id: str


@dataclass(frozen=True, slots=True)
class RequestJobCancellationInput:
    """Select one translation job to cancel."""

    job_id: str


@dataclass(frozen=True, slots=True)
class RetryTranslationJobInput:
    """Select one terminal translation job to retry."""

    job_id: str


class EnqueueTranslation:
    """Validate and persist one queued translation job."""

    def __init__(self, store: TranslationJobStore) -> None:
        self._store = store

    def execute(self, request: EnqueueTranslationInput) -> TranslationJob:
        """Create one queued job with a fresh identifier."""
        self._validate(request)
        novel = request.novel.strip()
        active = self._store.find_active(novel, request.chapter)
        if active is not None:
            raise ValidationError(
                f"Novel {novel} chapter {request.chapter} already has "
                f"an active translation job ({active.status.value})."
            )
        job = TranslationJob(
            job_id=uuid4().hex,
            status=JobStatus.QUEUED,
            novel=novel,
            chapter=request.chapter,
            provider=request.provider.strip(),
            model=request.model.strip(),
            segment_limit=request.segment_limit,
            source_kind=request.source_kind,
            source_ref=request.source_ref,
            volume=request.volume,
            source_text=request.source_text,
            parent_job_id=request.parent_job_id,
            created_at=_now_iso(),
        )
        return self._store.create(job)

    @staticmethod
    def _validate(request: EnqueueTranslationInput) -> None:
        """Reject unusable queue parameters with a typed error."""
        if request.chapter < 1:
            raise ValidationError("Chapter must be positive.")
        if not request.novel.strip():
            raise ValidationError("Novel must be non-empty.")
        if not request.provider.strip():
            raise ValidationError("Provider must be non-empty.")
        if not request.model.strip():
            raise ValidationError("Model must be non-empty.")
        if request.segment_limit < 1:
            raise ValidationError("Segment limit must be positive.")
        if (
            request.source_text is not None
            and len(request.source_text) > MAX_SOURCE_TEXT_CHARS
        ):
            raise ValidationError(
                "Source text exceeds the 1_000_000 character limit."
            )
        if request.source_kind == JobSourceKind.UPLOAD:
            if not request.source_text:
                raise ValidationError("Upload jobs require source text.")
        elif not request.source_ref.strip():
            raise ValidationError(
                f"{request.source_kind.value} jobs require a source reference."
            )


class GetTranslationJob:
    """Read one translation job by identifier."""

    def __init__(self, store: TranslationJobStore) -> None:
        self._store = store

    def execute(self, request: GetTranslationJobInput) -> TranslationJob:
        """Return one stored job or fail with a typed error."""
        return _existing(self._store, request.job_id)


class ListTranslationJobs:
    """List the newest translation jobs first."""

    def __init__(self, store: TranslationJobStore, limit: int = 50) -> None:
        self._store = store
        self._limit = limit

    def execute(self) -> list[TranslationJob]:
        """Return up to the configured number of recent jobs."""
        if self._limit < 1:
            raise ValidationError("Limit must be positive.")
        return self._store.list_recent(self._limit)


class RequestJobCancellation:
    """Cancel a queued job at once or flag a running job."""

    def __init__(self, store: TranslationJobStore) -> None:
        self._store = store

    def execute(self, request: RequestJobCancellationInput) -> TranslationJob:
        """Cancel queued jobs directly; flag running jobs instead."""
        job = _existing(self._store, request.job_id)
        if job.status == JobStatus.QUEUED:
            try:
                return self._store.mark_cancelled(job.job_id)
            except IntegrityError:
                # The worker claimed the job after our read; flag it.
                return self._store.request_cancel(job.job_id)
        if job.status in (
            JobStatus.RUNNING,
            JobStatus.CANCEL_REQUESTED,
        ):
            return self._store.request_cancel(job.job_id)
        raise ValidationError(
            f"Job {job.job_id} is already {job.status.value}."
        )


class RetryTranslationJob:
    """Enqueue one child job copying a terminal job."""

    def __init__(self, store: TranslationJobStore) -> None:
        self._store = store

    def execute(self, request: RetryTranslationJobInput) -> TranslationJob:
        """Copy one failed, interrupted, or cancelled job."""
        job = _existing(self._store, request.job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            if job.status not in RETRYABLE_JOB_STATUSES:
                raise ValidationError(
                    f"Job {job.job_id} is already "
                    f"{job.status.value} and cannot be retried."
                )
            return self._store.retry_source(job.job_id)
        raise ValidationError(f"Job {job.job_id} is still {job.status.value}.")
