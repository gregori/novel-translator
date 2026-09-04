"""Editorial workflows for immutable human revisions."""

from __future__ import annotations

import difflib
import shutil
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from novel_translator.core import Workspace, extract_draft_title
from novel_translator.shared.errors import ApprovalRequired, CollisionRequired, IntegrityError, ValidationError
from novel_translator.shared.models import (
    ArtifactKind,
    EditorialApproval,
    EditorialArtifact,
    RevisionKind,
    RevisionParent,
    RevisionParentKind,
    RevisionRecord,
)
from novel_translator.shared.utils import sha256_text


def read_revision_input(path: Path) -> str:
    """Read non-empty UTF-8 revision content without altering its bytes."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError("Revision input must be valid UTF-8.") from error
    except OSError as error:
        raise ValidationError("Revision input could not be read.") from error
    if not content.strip():
        raise ValidationError("Revision input must not be empty.")
    return content


def create_revision(
    workspace: Workspace,
    run_id: str,
    content: str,
    parent_revision_id: str | None = None,
    note: str | None = None,
    revision_kind: RevisionKind = RevisionKind.MANUAL,
    parent: RevisionParent | None = None,
) -> RevisionRecord:
    """Create an immutable revision from a verified generated draft or revision parent."""
    if not content.strip():
        raise ValidationError("Revision content must not be empty.")
    if parent is None:
        if parent_revision_id is None:
            if workspace.revisions(run_id):
                raise ValidationError("Specify --parent when the run already has revisions.")
            generated = workspace.generated_draft(run_id)
            parent = RevisionParent(
                RevisionParentKind.GENERATED_DRAFT,
                None,
                generated.content_hash,
                True,
            )
        else:
            parent_record, parent_artifact = workspace.revision(run_id, parent_revision_id)
            parent = RevisionParent(
                RevisionParentKind.REVISION,
                parent_record.revision_id,
                parent_artifact.content_hash,
                True,
            )
    elif parent_revision_id is not None:
        raise ValidationError("Specify either a parent revision or an explicit parent reference, not both.")
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
    workspace.create_revision(record, content)
    return record


def approve_artifact(
    workspace: Workspace,
    run_id: str,
    revision_id: str | None = None,
    approved: bool = True,
) -> EditorialApproval:
    """Append a schema-v2 decision for a verified generated draft or revision."""
    artifact = resolve_artifact(workspace, run_id, revision_id)
    event = EditorialApproval(
        schema_version=2,
        run_id=run_id,
        artifact_kind=artifact.kind,
        artifact_id=artifact.artifact_id,
        content_hash=artifact.content_hash,
        approved=approved,
        timestamp=datetime.now(UTC).isoformat(),
    )
    workspace.append_editorial_approval(event)
    return event


def resolve_artifact(workspace: Workspace, run_id: str, revision_id: str | None = None) -> EditorialArtifact:
    """Resolve and verify the artifact selected by an editorial command."""
    if revision_id is None:
        return workspace.generated_draft(run_id)
    _, artifact = workspace.revision(run_id, revision_id)
    return artifact


def revision_diff(
    workspace: Workspace,
    run_id: str,
    revision_id: str,
    against_revision_id: str | None = None,
) -> str:
    """Render a derived unified diff against a declared or explicit parent."""
    record, artifact = workspace.revision(run_id, revision_id)
    if against_revision_id is not None:
        _, parent_artifact = workspace.revision(run_id, against_revision_id)
        parent_label = against_revision_id
    elif record.parent.kind is RevisionParentKind.REVISION and record.parent.revision_id is not None:
        _, parent_artifact = workspace.revision(run_id, record.parent.revision_id)
        parent_label = record.parent.revision_id
    elif record.parent.kind is RevisionParentKind.GENERATED_DRAFT:
        parent_artifact = workspace.generated_draft(run_id)
        parent_label = "generated_draft"
    else:
        raise IntegrityError("The generated draft is unavailable, so this historical diff cannot be calculated.")
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


def migrate_legacy_draft(
    workspace: Workspace,
    run_id: str,
    as_published: bool,
    note: str | None = None,
) -> RevisionRecord:
    """Create one idempotent immutable snapshot for a legacy published draft."""
    if not as_published:
        raise ValidationError("Pass --as-published to confirm the current legacy draft is published content.")
    content, original_hash = workspace.legacy_draft_snapshot(run_id)
    content_hash = sha256_text(content)
    existing = [
        record
        for record in workspace.revisions(run_id)
        if record.revision_kind is RevisionKind.LEGACY_PUBLISHED_SNAPSHOT
    ]
    if existing:
        if len(existing) != 1 or existing[0].content_hash != content_hash:
            raise IntegrityError("A different legacy published snapshot already exists for this run.")
        return existing[0]
    if original_hash == content_hash:
        parent = RevisionParent(RevisionParentKind.GENERATED_DRAFT, None, original_hash, True)
    else:
        parent = RevisionParent(RevisionParentKind.UNAVAILABLE_GENERATED_DRAFT, None, original_hash or None, False)
    record = create_revision(
        workspace,
        run_id,
        content,
        note=note,
        revision_kind=RevisionKind.LEGACY_PUBLISHED_SNAPSHOT,
        parent=parent,
    )
    legacy_approval = _latest_legacy_approval(workspace, run_id)
    if legacy_approval is not None and legacy_approval.get("draft_hash") == content_hash:
        event = EditorialApproval(
            schema_version=2,
            run_id=run_id,
            artifact_kind=ArtifactKind.REVISION,
            artifact_id=record.revision_id,
            content_hash=content_hash,
            approved=bool(legacy_approval.get("approved")),
            timestamp=datetime.now(UTC).isoformat(),
        )
        workspace.append_editorial_approval(event)
    return record


def _latest_legacy_approval(workspace: Workspace, run_id: str) -> dict[str, object] | None:
    """Return the last schema-v1 approval event for a run without rewriting it."""
    latest: dict[str, object] | None = None
    for event in workspace.approval_events(run_id):
        if "draft_hash" in event:
            latest = event
    return latest


def export_artifact(
    workspace: Workspace,
    run_id: str,
    destination: Path,
    revision_id: str | None = None,
    title: str | None = None,
    overwrite: bool = False,
    publish_date: str | None = None,
) -> Path:
    """Export only a verified, explicitly approved generated draft or revision."""
    artifact = resolve_artifact(workspace, run_id, revision_id)
    if not workspace.is_artifact_approved(artifact, run_id):
        raise ApprovalRequired("The selected artifact hash has not been approved.")
    resolved_title = title or _title_for_content(workspace, run_id, artifact.content)
    if resolved_title is None:
        raise ValidationError("No draft title found; pass --title to export this run.")
    if publish_date is None:
        rendered_publish_date = date.today().isoformat()
    else:
        try:
            rendered_publish_date = date.fromisoformat(publish_date).isoformat()
        except ValueError as error:
            raise ValidationError("publish_date must use the YYYY-MM-DD format.") from error
    front_matter = ["---", f'chapterTitle: "{resolved_title}"', f"publishDate: {rendered_publish_date}"]
    volume = workspace.volume(run_id)
    if volume is not None:
        front_matter.append(f"volume: {volume}")
    rendered = "\n".join([*front_matter, "---", "", artifact.content, ""])
    destination = destination.resolve()
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered and not overwrite:
        raise CollisionRequired("Destination differs; pass explicit overwrite confirmation.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_suffix(destination.suffix + ".bak")
    try:
        if destination.exists():
            shutil.copy2(destination, backup)
        destination.write_text(rendered, encoding="utf-8")
        return destination
    except OSError:
        if backup.exists():
            backup.replace(destination)
        raise
    finally:
        if backup.exists():
            backup.unlink()


def _title_for_content(workspace: Workspace, run_id: str, content: str) -> str | None:
    """Read run identity and derive an export title from the selected content."""
    return extract_draft_title(content, workspace.chapter(run_id))


def revision_summary(workspace: Workspace, run_id: str) -> list[dict[str, object]]:
    """Return content-free revision summaries including current approval state."""
    summaries: list[dict[str, object]] = []
    for record in workspace.revisions(run_id):
        _, artifact = workspace.revision(run_id, record.revision_id)
        item = asdict(record)
        item["approved"] = workspace.is_artifact_approved(artifact, run_id)
        summaries.append(item)
    return summaries
