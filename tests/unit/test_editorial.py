"""Unit tests for immutable editorial revisions."""

import json
from pathlib import Path

import pytest

from novel_translator.core import Workspace
from novel_translator.editorial import (
    approve_artifact,
    create_revision,
    export_artifact,
    migrate_legacy_draft,
    revision_diff,
)
from novel_translator.shared.errors import ApprovalRequired, IntegrityError, ValidationError
from novel_translator.shared.utils import sha256_text

RUN_ID = "1" * 32


def workspace_with_draft(tmp_path: Path, content: str = "Episode 1: Test\n\nDraft") -> Workspace:
    """Create a minimal complete run with an integrity-protected generated draft."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text('{"identity": {"chapter": 1}}', encoding="utf-8")
    workspace.save_draft(RUN_ID, content)
    return workspace


def test_create_revision_requires_explicit_parent_after_first_revision(tmp_path: Path) -> None:
    """A second revision cannot silently select the most recent revision."""
    workspace = workspace_with_draft(tmp_path)
    first = create_revision(workspace, RUN_ID, "Episode 1: Test\n\nEdited")

    assert first.parent.kind == "generated_draft"
    with pytest.raises(ValidationError, match="Specify --parent"):
        create_revision(workspace, RUN_ID, "Episode 1: Test\n\nEdited twice")


def test_revision_detects_manual_content_corruption(tmp_path: Path) -> None:
    """Changed revision content cannot be approved or exported."""
    workspace = workspace_with_draft(tmp_path)
    revision = create_revision(workspace, RUN_ID, "Episode 1: Test\n\nEdited")
    path = tmp_path / "runs" / RUN_ID / "revisions" / revision.revision_id / "content.md"
    path.write_text("Corrupted", encoding="utf-8")

    with pytest.raises(IntegrityError, match="Revision content integrity"):
        approve_artifact(workspace, RUN_ID, revision.revision_id)


def test_revision_approval_and_export_use_exact_hash(tmp_path: Path) -> None:
    """Only the explicitly approved immutable revision is exportable."""
    workspace = workspace_with_draft(tmp_path)
    revision = create_revision(workspace, RUN_ID, "Episode 1: Test\n\nEdited")

    with pytest.raises(ApprovalRequired):
        export_artifact(workspace, RUN_ID, tmp_path / "out.md", revision.revision_id)
    approve_artifact(workspace, RUN_ID, revision.revision_id)
    exported = export_artifact(workspace, RUN_ID, tmp_path / "out.md", revision.revision_id)

    assert "Edited" in exported.read_text(encoding="utf-8")


def test_diff_uses_declared_parent_and_legacy_unavailable_parent_fails(tmp_path: Path) -> None:
    """Diff derives from the parent when available and rejects lost historical content."""
    workspace = workspace_with_draft(tmp_path)
    revision = create_revision(workspace, RUN_ID, "Episode 1: Test\n\nEdited")

    assert "-Draft" in revision_diff(workspace, RUN_ID, revision.revision_id)
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "draft.md").write_text("Published", encoding="utf-8")
    migrated = migrate_legacy_draft(workspace, RUN_ID, True)

    with pytest.raises(IntegrityError, match="historical diff"):
        revision_diff(workspace, RUN_ID, migrated.revision_id)


def test_legacy_migration_is_idempotent_and_preserves_original_hash(tmp_path: Path) -> None:
    """Migration snapshots changed legacy content without rewriting its historical files."""
    workspace = workspace_with_draft(tmp_path)
    run_dir = tmp_path / "runs" / RUN_ID
    original_hash = (run_dir / "draft.sha256").read_text(encoding="utf-8")
    (run_dir / "draft.md").write_text("Published", encoding="utf-8")

    first = migrate_legacy_draft(workspace, RUN_ID, True, "Published chapter")
    second = migrate_legacy_draft(workspace, RUN_ID, True, "Published chapter")
    metadata = json.loads((run_dir / "revisions" / first.revision_id / "revision.json").read_text(encoding="utf-8"))

    assert first.revision_id == second.revision_id
    assert (run_dir / "draft.sha256").read_text(encoding="utf-8") == original_hash
    assert metadata["parent"] == {
        "content_available": False,
        "content_hash": original_hash,
        "kind": "unavailable_generated_draft",
        "revision_id": None,
    }
    assert sha256_text("Published") == first.content_hash
