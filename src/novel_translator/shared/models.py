"""Shared immutable value objects."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle states persisted for a translation run."""

    STARTED = "started"
    TRANSLATING = "translating"
    DRAFT_COMPLETED = "draft_completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ChapterIdentity:
    """Canonical novel and chapter identity supplied by the CLI."""

    novel: str
    chapter: int

    def __post_init__(self) -> None:
        """Validate canonical identity values."""
        if not self.novel.strip() or self.chapter < 1:
            raise ValueError("Novel must be non-empty and chapter must be positive.")


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Serializable audit record for one immutable translation run."""

    run_id: str
    identity: ChapterIdentity
    source_hash: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    bible_hash: str
    timestamp: datetime
    status: RunStatus
    bible_version: str | None = None
    volume: int | None = None
    source_title: str | None = None
