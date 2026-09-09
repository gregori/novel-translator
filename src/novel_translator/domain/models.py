"""Shared immutable value objects and identity contracts."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, StrEnum

RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
"""Canonical run and revision identifier contract."""


class RunStatus(StrEnum):
    """Lifecycle states persisted for a translation run."""

    STARTED = "started"
    TRANSLATING = "translating"
    DRAFT_COMPLETED = "draft_completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ChapterState(StrEnum):
    """User-facing aggregate state for one registered chapter."""

    NO_SOURCE = "no_source"
    READY = "ready"
    TRANSLATING = "translating"
    DRAFT_AVAILABLE = "draft_available"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    EXPORTED = "exported"
    FAILED = "failed"


class RunPhase(StrEnum):
    """Bounded workflow phases used in safe failure metadata."""

    TRANSLATION = "translation"
    DRAFT_PERSISTENCE = "draft_persistence"
    FINALIZATION = "finalization"


class ArtifactKind(StrEnum):
    """Artifacts that can be approved and exported."""

    GENERATED_DRAFT = "generated_draft"
    REVISION = "revision"


class RevisionParentKind(StrEnum):
    """The immutable artifact from which a revision was derived."""

    GENERATED_DRAFT = "generated_draft"
    REVISION = "revision"
    UNAVAILABLE_GENERATED_DRAFT = "unavailable_generated_draft"


class RevisionKind(StrEnum):
    """How a human revision entered the editorial workflow."""

    MANUAL = "manual"
    LEGACY_PUBLISHED_SNAPSHOT = "legacy_published_snapshot"


class RunEntryError(Enum):
    """Reason one runs-directory entry cannot appear in a catalog listing."""

    FOREIGN = "foreign"
    INCOMPLETE = "incomplete"
    CORRUPT = "corrupt"
    ORPHAN = "orphan"
    EDITORIAL = "editorial"


type ArtifactKey = tuple[ArtifactKind, str | None, str]


@dataclass(frozen=True, slots=True)
class ChapterIdentity:
    """Canonical novel and chapter identity supplied by the CLI."""

    novel: str
    chapter: int

    def __post_init__(self) -> None:
        """Validate canonical identity values."""
        if not self.novel.strip() or self.chapter < 1:
            raise ValueError(
                "Novel must be non-empty and chapter must be positive."
            )


@dataclass(frozen=True, slots=True)
class PromptCall:
    """One gateway call associated with an exact rendered prompt hash."""

    attempt: int
    rendered_prompt_hash: str


@dataclass(frozen=True, slots=True)
class SegmentPromptManifest:
    """Hash-only provenance for one source segment, without sensitive text."""

    segment_index: int
    source_segment_hash: str
    continuity_context_hash: str
    rendered_prompt_hash: str
    gateway_calls: list[PromptCall]


@dataclass(frozen=True, slots=True)
class RunEntryIssue:
    """One skipped runs entry with a safe identifier and its error type."""

    entry: str
    error: RunEntryError


@dataclass(frozen=True, slots=True)
class RunCatalog:
    """Listable run identifiers plus typed issues for skipped entries."""

    run_ids: tuple[str, ...]
    issues: tuple[RunEntryIssue, ...]


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Serializable audit record for one immutable translation run."""

    run_id: str
    identity: ChapterIdentity
    source_hash: str
    provider: str
    model: str
    schema_version: int
    prompt_version: str
    prompt_hash: str
    prompt_template_version: str
    prompt_template_hash: str
    context_hash: str
    segment_manifest: list[SegmentPromptManifest]
    bible_hash: str
    timestamp: datetime
    status: RunStatus
    bible_version: str | None = None
    volume: int | None = None
    source_title: str | None = None


@dataclass(frozen=True, slots=True)
class RunCompletion:
    """Application-computed audit values for a completed translation run."""

    duration_seconds: float
    source_characters: int
    draft_characters: int
    source_tokens: int
    draft_tokens: int
    draft_title: str | None


@dataclass(frozen=True, slots=True)
class RevisionParent:
    """Hash-addressed parent reference stored with a revision."""

    kind: RevisionParentKind
    revision_id: str | None
    content_hash: str | None
    content_available: bool


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """Immutable metadata for one human editorial revision."""

    schema_version: int
    revision_id: str
    run_id: str
    content_hash: str
    parent: RevisionParent
    author_type: str
    revision_kind: RevisionKind
    created_at: str
    note: str | None


@dataclass(frozen=True, slots=True)
class EditorialApproval:
    """Schema-v2 append-only decision for one exact editorial artifact."""

    schema_version: int
    run_id: str
    artifact_kind: ArtifactKind
    artifact_id: str | None
    content_hash: str
    approved: bool
    timestamp: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExportEvent:
    """Append-only provenance for one successfully exported artifact."""

    schema_version: int
    run_id: str
    artifact_kind: ArtifactKind
    artifact_id: str | None
    content_hash: str
    destination: str
    exported_at: str
    git_commit: str | None = None
    pull_request_url: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalEvent:
    """Legacy append-only approval decision for an exact draft hash."""

    run_id: str
    draft_hash: str
    approved: bool
    timestamp: str


@dataclass(frozen=True, slots=True)
class EditorialArtifact:
    """Verified content and identity for one exportable editorial artifact."""

    kind: ArtifactKind
    artifact_id: str | None
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class WorkingCopy:
    """One mutable editing session over a verified base artifact."""

    id: str
    run_id: str
    base_artifact_kind: ArtifactKind
    base_artifact_id: str | None
    base_content_hash: str
    content: str
    version: int
    created_at: str
    updated_at: str
