"""Immutable value objects and lifecycle states for translation jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class JobStatus(StrEnum):
    """Lifecycle states persisted for one translation job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class JobSourceKind(StrEnum):
    """How a translation job resolves its source text."""

    EXISTING = "existing"
    UPLOAD = "upload"
    EPISODE = "episode"


TERMINAL_JOB_STATUSES: Final[frozenset[JobStatus]] = frozenset(
    {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.INTERRUPTED,
        JobStatus.CANCELLED,
    }
)
"""Job states that never accept further transitions."""


ACTIVE_JOB_STATUSES: Final[frozenset[JobStatus]] = frozenset(
    {
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.CANCEL_REQUESTED,
    }
)
"""Job states that still change in the background."""


@dataclass(frozen=True, slots=True)
class TranslationJob:
    """One durable translation request with queue metadata."""

    job_id: str
    status: JobStatus
    novel: str
    chapter: int
    provider: str
    model: str
    segment_limit: int
    source_kind: JobSourceKind
    source_ref: str
    job_type: str = "translation"
    run_id: str | None = None
    volume: int | None = None
    source_text: str | None = None
    parent_job_id: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    attempt: int = 1
    created_at: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    completed_at: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
