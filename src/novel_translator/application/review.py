"""Editorial workflows for immutable human revisions."""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import (
    ArtifactKind,
    EditorialApproval,
    RevisionKind,
    RevisionParent,
    RevisionParentKind,
    RevisionRecord,
)
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text


def _create_revision(
    workspace: Workspace,
    run_id: str,
    content: str,
    parent_revision_id: str | None = None,
    note: str | None = None,
    revision_kind: RevisionKind = RevisionKind.MANUAL,
    parent: RevisionParent | None = None,
) -> RevisionRecord:
    """Create an immutable revision from a verified generated
    draft or revision parent."""
    if not content.strip():
        raise ValidationError("Revision content must not be empty.")
    if parent is None:
        if parent_revision_id is None:
            if workspace.revisions.revisions(run_id):
                raise ValidationError(
                    "Specify --parent when the run already has revisions."
                )
            generated = workspace.runs.generated_draft(run_id)
            parent = RevisionParent(
                RevisionParentKind.GENERATED_DRAFT,
                None,
                generated.content_hash,
                True,
            )
        else:
            parent_record, parent_artifact = workspace.revisions.revision(
                run_id, parent_revision_id
            )
            parent = RevisionParent(
                RevisionParentKind.REVISION,
                parent_record.revision_id,
                parent_artifact.content_hash,
                True,
            )
    elif parent_revision_id is not None:
        raise ValidationError(
            "Specify either a parent revision or an explicit parent "
            "reference, not both."
        )
    record = RevisionRecord(
        schema_version=1,
        revision_id=uuid.uuid4().hex,
        run_id=run_id,
        content_hash=sha256_text(content),
        parent=parent,
        author_type="human",
        revision_kind=revision_kind,
        created_at=datetime.now(UTC).isoformat(),
        note=note,
    )
    workspace.revisions.create_revision(record, content)
    return record


def _revision_diff(
    workspace: Workspace,
    run_id: str,
    revision_id: str,
    against_revision_id: str | None = None,
) -> str:
    """Render a derived unified diff against a declared or explicit parent."""
    record, artifact = workspace.revisions.revision(run_id, revision_id)
    if against_revision_id is not None:
        _, parent_artifact = workspace.revisions.revision(
            run_id, against_revision_id
        )
        parent_label = against_revision_id
    elif (
        record.parent.kind is RevisionParentKind.REVISION
        and record.parent.revision_id is not None
    ):
        _, parent_artifact = workspace.revisions.revision(
            run_id, record.parent.revision_id
        )
        parent_label = record.parent.revision_id
    elif record.parent.kind is RevisionParentKind.GENERATED_DRAFT:
        parent_artifact = workspace.runs.generated_draft(run_id)
        parent_label = "generated_draft"
    else:
        raise IntegrityError(
            "The generated draft is unavailable, so this historical "
            "diff cannot be calculated."
        )
    if (
        record.parent.kind is RevisionParentKind.REVISION
        and against_revision_id is None
        and parent_artifact.content_hash != record.parent.content_hash
    ):
        raise IntegrityError("Revision parent integrity check failed.")
    diff = difflib.unified_diff(
        parent_artifact.content.splitlines(keepends=True),
        artifact.content.splitlines(keepends=True),
        fromfile=parent_label,
        tofile=revision_id,
    )
    return "".join(diff)


def _migrate_legacy_draft(
    workspace: Workspace,
    run_id: str,
    as_published: bool,
    note: str | None = None,
) -> RevisionRecord:
    """Create one idempotent immutable snapshot for a legacy
    published draft."""
    if not as_published:
        raise ValidationError(
            "Explicitly confirm that the legacy draft is published content."
        )
    content, original_hash = workspace.runs.legacy_draft_snapshot(run_id)
    content_hash = sha256_text(content)
    existing = [
        record
        for record in workspace.revisions.revisions(run_id)
        if record.revision_kind is RevisionKind.LEGACY_PUBLISHED_SNAPSHOT
    ]
    if existing:
        if len(existing) != 1 or existing[0].content_hash != content_hash:
            raise IntegrityError(
                "A different legacy published snapshot already exists "
                "for this run."
            )
        return existing[0]
    if original_hash == content_hash:
        parent = RevisionParent(
            RevisionParentKind.GENERATED_DRAFT, None, original_hash, True
        )
    else:
        parent = RevisionParent(
            RevisionParentKind.UNAVAILABLE_GENERATED_DRAFT,
            None,
            original_hash or None,
            False,
        )
    record = _create_revision(
        workspace,
        run_id,
        content,
        note=note,
        revision_kind=RevisionKind.LEGACY_PUBLISHED_SNAPSHOT,
        parent=parent,
    )
    legacy_approval = _latest_legacy_approval(workspace, run_id)
    if (
        legacy_approval is not None
        and legacy_approval.get("draft_hash") == content_hash
    ):
        event = EditorialApproval(
            schema_version=2,
            run_id=run_id,
            artifact_kind=ArtifactKind.REVISION,
            artifact_id=record.revision_id,
            content_hash=content_hash,
            approved=bool(legacy_approval.get("approved")),
            timestamp=datetime.now(UTC).isoformat(),
        )
        workspace.approvals.append_editorial_approval(event)
    return record


def _latest_legacy_approval(
    workspace: Workspace, run_id: str
) -> dict[str, object] | None:
    """Return the last schema-v1 approval event for a run without
    rewriting it."""
    latest: dict[str, object] | None = None
    for event in workspace.approvals.approval_events(run_id):
        if "draft_hash" in event:
            latest = event
    return latest


@dataclass(frozen=True, slots=True)
class CreateRevisionInput:
    """Typed input for an immutable human revision."""

    run_id: str
    content: str
    parent_revision_id: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ListRevisionsInput:
    """Select one run's revision history."""

    run_id: str


@dataclass(frozen=True, slots=True)
class MigrateLegacyDraftInput:
    """Select and explicitly confirm one legacy published draft."""

    run_id: str
    as_published: bool
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    """Revision metadata plus its current approval state."""

    record: RevisionRecord
    approved: bool


@dataclass(frozen=True, slots=True)
class GetDiffInput:
    """Select a revision and optional explicit comparison parent."""

    run_id: str
    revision_id: str
    against_revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Rendered unified diff for one immutable revision."""

    content: str


class CreateRevision:
    """Create immutable revisions independently of delivery frameworks."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: CreateRevisionInput) -> RevisionRecord:
        """Create and persist the requested revision."""
        return _create_revision(
            self._workspace,
            request.run_id,
            request.content,
            request.parent_revision_id,
            request.note,
        )


class ListRevisions:
    """List immutable revision metadata and approval state."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(
        self, request: ListRevisionsInput
    ) -> tuple[RevisionSummary, ...]:
        """Return content-free revision summaries."""
        summaries: list[RevisionSummary] = []
        for record in self._workspace.revisions.revisions(request.run_id):
            _, artifact = self._workspace.revisions.revision(
                request.run_id, record.revision_id
            )
            summaries.append(
                RevisionSummary(
                    record,
                    self._workspace.approvals.is_artifact_approved(
                        artifact, request.run_id
                    ),
                )
            )
        return tuple(summaries)


class MigrateLegacyDraft:
    """Create an auditable immutable snapshot of a legacy draft."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: MigrateLegacyDraftInput) -> RevisionRecord:
        """Migrate one explicitly confirmed legacy published draft."""
        return _migrate_legacy_draft(
            self._workspace,
            request.run_id,
            request.as_published,
            request.note,
        )


class GetDiff:
    """Calculate a diff from explicitly selected immutable artifacts."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: GetDiffInput) -> DiffResult:
        """Return the derived unified diff."""
        return DiffResult(
            _revision_diff(
                self._workspace,
                request.run_id,
                request.revision_id,
                request.against_revision_id,
            )
        )
