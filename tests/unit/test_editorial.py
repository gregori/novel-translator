"""Unit tests for immutable editorial revisions."""

import json
from pathlib import Path

import pytest

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
)
from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
    GetDiff,
    GetDiffInput,
    MigrateLegacyDraft,
    MigrateLegacyDraftInput,
)
from novel_translator.domain.errors import (
    ApprovalRequired,
    IntegrityError,
    ValidationError,
)
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text

RUN_ID = "1" * 32


def workspace_with_draft(
    tmp_path: Path, content: str = "Episode 1: Test\n\nDraft"
) -> Workspace:
    """Create a minimal run with an integrity-protected generated draft."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        '{"identity": {"chapter": 1}}', encoding="utf-8"
    )
    workspace.runs.save_draft(RUN_ID, content)
    return workspace


def create_revision(workspace: Workspace, content: str) -> str:
    """Create a revision and return its identifier."""
    return (
        CreateRevision(workspace)
        .execute(CreateRevisionInput(RUN_ID, content))
        .revision_id
    )


def migrate_legacy(workspace: Workspace, note: str | None = None) -> str:
    """Migrate a confirmed legacy draft and return its revision ID."""
    return (
        MigrateLegacyDraft(workspace)
        .execute(MigrateLegacyDraftInput(RUN_ID, True, note))
        .revision_id
    )


def test_create_revision_requires_explicit_parent_after_first_revision(
    tmp_path: Path,
) -> None:
    """A second revision cannot silently select the most recent revision."""
    workspace = workspace_with_draft(tmp_path)
    revision_id = create_revision(workspace, "Episode 1: Test\n\nEdited")
    record, _ = workspace.revisions.revision(RUN_ID, revision_id)

    assert record.parent.kind == "generated_draft"
    with pytest.raises(ValidationError, match="Specify --parent"):
        create_revision(workspace, "Episode 1: Test\n\nEdited twice")


def test_revision_detects_manual_content_corruption(tmp_path: Path) -> None:
    """Changed revision content cannot be approved."""
    workspace = workspace_with_draft(tmp_path)
    revision_id = create_revision(workspace, "Episode 1: Test\n\nEdited")
    path = (
        tmp_path / "runs" / RUN_ID / "revisions" / revision_id / "content.md"
    )
    path.write_text("Corrupted", encoding="utf-8")

    with pytest.raises(IntegrityError, match="Revision content integrity"):
        ApproveArtifact(workspace).execute(
            ArtifactApprovalInput(RUN_ID, revision_id)
        )


def test_revision_approval_and_export_use_exact_hash(tmp_path: Path) -> None:
    """Only the explicitly approved immutable revision is exportable."""
    workspace = workspace_with_draft(tmp_path)
    revision_id = create_revision(workspace, "Episode 1: Test\n\nEdited")
    request = ExportArtifactInput(RUN_ID, tmp_path / "out.md", revision_id)
    use_case = ExportArtifact(workspace, FilesystemArtifactWriter())

    with pytest.raises(ApprovalRequired):
        use_case.execute(request)
    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(RUN_ID, revision_id)
    )
    exported = use_case.execute(request).path

    assert "Edited" in exported.read_text(encoding="utf-8")


def test_diff_uses_declared_parent_and_legacy_unavailable_parent_fails(
    tmp_path: Path,
) -> None:
    """Diff uses an available parent and rejects lost historical content."""
    workspace = workspace_with_draft(tmp_path)
    revision_id = create_revision(workspace, "Episode 1: Test\n\nEdited")

    assert (
        "-Draft"
        in GetDiff(workspace)
        .execute(GetDiffInput(RUN_ID, revision_id))
        .content
    )
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "draft.md").write_text("Published", encoding="utf-8")
    migrated_id = migrate_legacy(workspace)

    with pytest.raises(IntegrityError, match="historical diff"):
        GetDiff(workspace).execute(GetDiffInput(RUN_ID, migrated_id))


def test_legacy_migration_is_idempotent_and_preserves_original_hash(
    tmp_path: Path,
) -> None:
    """Migration snapshots changed content without rewriting history."""
    workspace = workspace_with_draft(tmp_path)
    run_dir = tmp_path / "runs" / RUN_ID
    original_hash = (run_dir / "draft.sha256").read_text(encoding="utf-8")
    (run_dir / "draft.md").write_text("Published", encoding="utf-8")

    first_id = migrate_legacy(workspace, "Published chapter")
    second_id = migrate_legacy(workspace, "Published chapter")
    metadata = json.loads(
        (run_dir / "revisions" / first_id / "revision.json").read_text(
            encoding="utf-8"
        )
    )
    first, _ = workspace.revisions.revision(RUN_ID, first_id)

    assert first_id == second_id
    assert (run_dir / "draft.sha256").read_text(
        encoding="utf-8"
    ) == original_hash
    assert metadata["parent"] == {
        "content_available": False,
        "content_hash": original_hash,
        "kind": "unavailable_generated_draft",
        "revision_id": None,
    }
    assert sha256_text("Published") == first.content_hash
