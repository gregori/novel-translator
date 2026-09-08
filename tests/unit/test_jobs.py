"""Unit tests for the translation job queue use cases."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from novel_translator.application.jobs import (
    EnqueueTranslation,
    EnqueueTranslationInput,
    GetTranslationJob,
    GetTranslationJobInput,
    ListTranslationJobs,
    RequestJobCancellation,
    RequestJobCancellationInput,
    RetryTranslationJob,
    RetryTranslationJobInput,
    TranslationJobStore,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.domain.jobs import (
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.worker import recover_stale_jobs


class FakeTranslationJobStore(TranslationJobStore):
    """In-memory queue with the same transition rules as SQLite."""

    def __init__(self) -> None:
        self._jobs: dict[str, TranslationJob] = {}

    def create(self, job: TranslationJob) -> TranslationJob:
        """Persist one new queued job."""
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> TranslationJob | None:
        """Return one job by identifier, if present."""
        return self._jobs.get(job_id)

    def find_active(self, novel: str, chapter: int) -> TranslationJob | None:
        """Return the newest non-terminal job for one chapter, if any."""
        candidates = sorted(
            (
                job
                for job in self._jobs.values()
                if job.novel == novel
                and job.chapter == chapter
                and job.status
                in (
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.CANCEL_REQUESTED,
                )
            ),
            key=lambda job: job.created_at or "",
            reverse=True,
        )
        return candidates[0] if candidates else None

    def list_recent(self, limit: int = 50) -> list[TranslationJob]:
        """Return the newest jobs first, up to the given limit."""
        ordered = sorted(
            self._jobs.values(),
            key=lambda job: job.created_at or "",
            reverse=True,
        )
        return ordered[:limit]

    def claim_queued(self) -> TranslationJob | None:
        """Move the oldest queued job to running."""
        queued = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status == JobStatus.QUEUED
            ),
            key=lambda job: job.created_at or "",
        )
        if not queued:
            return None
        now = datetime.now(UTC).isoformat()
        claimed = replace(
            queued[0],
            status=JobStatus.RUNNING,
            started_at=now,
            heartbeat_at=now,
        )
        self._jobs[claimed.job_id] = claimed
        return claimed

    def heartbeat(self, job_id: str, at: str | None = None) -> None:
        """Refresh the heartbeat of a running job only."""
        job = self._jobs[job_id]
        if job.status == JobStatus.RUNNING:
            self._jobs[job_id] = replace(
                job, heartbeat_at=at or datetime.now(UTC).isoformat()
            )

    def update_progress(self, job_id: str, current: int, total: int) -> None:
        """Persist the latest segment progress counters."""
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job, progress_current=current, progress_total=total
        )

    def finish(self, job_id: str, run_id: str) -> TranslationJob:
        """Mark one job succeeded with its run identifier."""
        return self._replace(
            job_id,
            status=JobStatus.SUCCEEDED,
            run_id=run_id,
            completed_at=datetime.now(UTC).isoformat(),
        )

    def fail(
        self, job_id: str, error_type: str, error_message: str
    ) -> TranslationJob:
        """Mark one job failed with safe error metadata."""
        return self._replace(
            job_id,
            status=JobStatus.FAILED,
            error_type=error_type,
            error_message=error_message,
            completed_at=datetime.now(UTC).isoformat(),
        )

    def interrupt(self, job_id: str) -> TranslationJob:
        """Mark one job interrupted without recording an error."""
        return self._replace(
            job_id,
            status=JobStatus.INTERRUPTED,
            completed_at=datetime.now(UTC).isoformat(),
        )

    def mark_cancelled(self, job_id: str) -> TranslationJob:
        """Mark one job cancelled after a confirmed request."""
        return self._replace(
            job_id,
            status=JobStatus.CANCELLED,
            completed_at=datetime.now(UTC).isoformat(),
        )

    def request_cancel(self, job_id: str) -> TranslationJob:
        """Flag one active job for cooperative cancellation."""
        return self._replace(
            job_id,
            status=JobStatus.CANCEL_REQUESTED,
            cancel_requested=True,
        )

    def retry_source(self, job_id: str) -> TranslationJob:
        """Enqueue one queued child copying the given job."""
        source = self._jobs[job_id]
        child = TranslationJob(
            job_id=f"{source.job_id}-retry",
            status=JobStatus.QUEUED,
            novel=source.novel,
            chapter=source.chapter,
            provider=source.provider,
            model=source.model,
            segment_limit=source.segment_limit,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
            volume=source.volume,
            source_text=source.source_text,
            parent_job_id=source.job_id,
            created_at=datetime.now(UTC).isoformat(),
        )
        return self.create(child)

    def _replace(self, job_id: str, **values: object) -> TranslationJob:
        """Apply one field change to a stored job."""
        updated = replace(self._jobs[job_id], **values)
        self._jobs[job_id] = updated
        return updated


def enqueue(
    store: FakeTranslationJobStore,
    source_kind: JobSourceKind = JobSourceKind.EXISTING,
    source_ref: str = "chapter-001.txt",
    source_text: str | None = None,
    chapter: int = 1,
) -> TranslationJob:
    """Enqueue one valid job with overridable queue parameters."""
    return EnqueueTranslation(store).execute(
        EnqueueTranslationInput(
            novel="test-novel",
            chapter=chapter,
            provider="opencode-go",
            model="test-model",
            source_kind=source_kind,
            source_ref=source_ref,
            source_text=source_text,
        )
    )


def test_enqueue_creates_queued_job() -> None:
    """A valid request persists a queued job with a fresh ID."""
    store = FakeTranslationJobStore()

    job = enqueue(store)

    assert len(job.job_id) == 32
    assert int(job.job_id, 16) >= 0
    assert job.status == JobStatus.QUEUED
    assert job.job_type == "translation"
    assert job.created_at is not None
    assert store.get(job.job_id) == job


def test_enqueue_rejects_non_positive_chapter() -> None:
    """Chapters below one never reach the queue."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        enqueue(store, chapter=0)


def test_enqueue_rejects_oversized_source_text() -> None:
    """Uploads above the character limit never reach the queue."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        enqueue(
            store,
            source_kind=JobSourceKind.UPLOAD,
            source_text="x" * 1_000_001,
        )


def test_enqueue_requires_source_text_for_upload() -> None:
    """Uploads without inline text are rejected before enqueueing."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        enqueue(store, source_kind=JobSourceKind.UPLOAD)


def test_enqueue_requires_source_ref_for_existing() -> None:
    """Existing sources without a reference are rejected."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        enqueue(store, source_ref="  ")


def test_enqueue_requires_source_ref_for_episode() -> None:
    """Episodes without an identifier are rejected."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        enqueue(
            store,
            source_kind=JobSourceKind.EPISODE,
            source_ref="",
        )


def test_claim_returns_oldest_and_single_winner() -> None:
    """Two sequential claims win once each, then find nothing."""
    store = FakeTranslationJobStore()
    first = enqueue(store)
    second = enqueue(store, chapter=2)

    assert store.claim_queued() is not None
    claimed_first = store.get(first.job_id)
    assert claimed_first is not None
    assert claimed_first.status == JobStatus.RUNNING
    assert store.claim_queued() is not None
    assert store.get(second.job_id) is not None
    assert store.claim_queued() is None


def test_list_recent_orders_newest_first() -> None:
    """Recent listings return newest jobs first within the limit."""
    store = FakeTranslationJobStore()
    old = replace(enqueue(store), created_at="2026-01-01T00:00:00+00:00")
    store._jobs[old.job_id] = old
    new = enqueue(store, chapter=2)

    listed = ListTranslationJobs(store, limit=1).execute()

    assert [job.job_id for job in listed] == [new.job_id]


def test_get_missing_job_raises() -> None:
    """Reading an unknown job fails with a typed error."""
    store = FakeTranslationJobStore()

    with pytest.raises(ValidationError):
        GetTranslationJob(store).execute(GetTranslationJobInput("0" * 32))


def test_request_cancel_queued_marks_cancelled() -> None:
    """Queued jobs cancel immediately without a running flag."""
    store = FakeTranslationJobStore()
    job = enqueue(store)

    cancelled = RequestJobCancellation(store).execute(
        RequestJobCancellationInput(job.job_id)
    )

    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.completed_at is not None


def test_request_cancel_running_flags_request() -> None:
    """Running jobs keep running until the worker observes the flag."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.claim_queued()

    flagged = RequestJobCancellation(store).execute(
        RequestJobCancellationInput(job.job_id)
    )

    assert flagged.status == JobStatus.CANCEL_REQUESTED
    assert flagged.cancel_requested is True


def test_request_cancel_terminal_raises() -> None:
    """Terminal jobs reject cancellation with a typed error."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.finish(job.job_id, "1" * 32)

    with pytest.raises(ValidationError):
        RequestJobCancellation(store).execute(
            RequestJobCancellationInput(job.job_id)
        )


def test_retry_creates_child_with_parent_link() -> None:
    """A failed job seeds one queued child copying its parameters."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.fail(job.job_id, "ValidationError", "boom")

    child = RetryTranslationJob(store).execute(
        RetryTranslationJobInput(job.job_id)
    )

    assert child.status == JobStatus.QUEUED
    assert child.parent_job_id == job.job_id
    assert child.job_id != job.job_id
    assert child.novel == job.novel
    assert child.chapter == job.chapter
    assert child.source_ref == job.source_ref


def test_retry_rejects_active_job() -> None:
    """Running jobs cannot seed a retry child."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.claim_queued()

    with pytest.raises(ValidationError):
        RetryTranslationJob(store).execute(
            RetryTranslationJobInput(job.job_id)
        )


def test_recover_stale_interrupts_running_job() -> None:
    """A running job with an expired heartbeat becomes interrupted."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.claim_queued()
    store.heartbeat(job.job_id, at="2000-01-01T00:00:00+00:00")

    recovered = recover_stale_jobs(store, stale_seconds=60.0)

    assert recovered == 1
    updated = store.get(job.job_id)
    assert updated is not None
    assert updated.status == JobStatus.INTERRUPTED


def test_recover_stale_cancels_expired_request() -> None:
    """An expired cancel request settles as cancelled."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.claim_queued()
    store.heartbeat(job.job_id, at="2000-01-01T00:00:00+00:00")
    store.request_cancel(job.job_id)

    recovered = recover_stale_jobs(store, stale_seconds=60.0)

    assert recovered == 1
    updated = store.get(job.job_id)
    assert updated is not None
    assert updated.status == JobStatus.CANCELLED


def test_recover_stale_keeps_fresh_running_job() -> None:
    """A recently heartbeated job is left running."""
    store = FakeTranslationJobStore()
    job = enqueue(store)
    store.claim_queued()

    recovered = recover_stale_jobs(store, stale_seconds=3600.0)

    assert recovered == 0
    updated = store.get(job.job_id)
    assert updated is not None
    assert updated.status == JobStatus.RUNNING
