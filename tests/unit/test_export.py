"""Tests for approved Markdown export behavior."""

from pathlib import Path

import pytest

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
    ExportHistoryInput,
    ListExportHistory,
    PreviewExport,
    PreviewExportInput,
)
from novel_translator.domain.errors import ApprovalRequired, CollisionRequired
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text

VALID_RUN_ID = "0" * 32


def approve(
    workspace: Workspace, run_id: str, revision_id: str | None = None
) -> None:
    """Approve one exact artifact through the public use case."""
    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(run_id, revision_id)
    )


def export_draft(
    workspace: Workspace,
    run_id: str,
    destination: Path,
    revision_id: str | None = None,
    title: str | None = None,
    publish_date: str | None = None,
) -> Path:
    """Export one artifact through the public use case."""
    return (
        ExportArtifact(workspace, FilesystemArtifactWriter())
        .execute(
            ExportArtifactInput(
                run_id,
                destination,
                revision_id,
                title,
                publish_date=publish_date,
            )
        )
        .path
    )


def test_export_uses_an_inferred_draft_title(tmp_path: Path) -> None:
    """Export strips bold Markdown from an inferred draft heading."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text(
        "**Episode 7: Rainy Day**\n\nDraft", encoding="utf-8"
    )
    (run_dir / "draft.sha256").write_text(
        sha256_text("**Episode 7: Rainy Day**\n\nDraft"), encoding="utf-8"
    )
    (run_dir / "run.json").write_text(
        '{"identity": {"chapter": 7}}', encoding="utf-8"
    )
    approve(workspace, VALID_RUN_ID)

    exported = export_draft(workspace, VALID_RUN_ID, tmp_path / "out.md")

    assert 'chapterTitle: "Episode 7: Rainy Day"' in exported.read_text(
        encoding="utf-8"
    )


def test_workspace_requires_current_approval_for_export(
    tmp_path: Path,
) -> None:
    """Export does not occur before an exact hash approval."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    with pytest.raises(ApprovalRequired):
        export_draft(
            workspace, VALID_RUN_ID, tmp_path / "out.md", title="Title"
        )


def test_export_uses_volume_persisted_in_run_metadata(tmp_path: Path) -> None:
    """Export preserves the optional run volume
    in the Markdown front matter."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    (run_dir / "run.json").write_text('{"volume": 2}', encoding="utf-8")
    approve(workspace, VALID_RUN_ID)

    exported = export_draft(
        workspace,
        VALID_RUN_ID,
        tmp_path / "chapter.md",
        title="Chapter 1",
        publish_date="2026-08-24",
    )

    assert 'chapterTitle: "Chapter 1"' in exported.read_text(encoding="utf-8")
    assert "publishDate: 2026-08-24" in exported.read_text(encoding="utf-8")
    assert "volume: 2" in exported.read_text(encoding="utf-8")


def test_preview_renders_without_touching_checkout(tmp_path: Path) -> None:
    """Download/view/copy render the approved Markdown without writing."""

    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    approve(workspace, VALID_RUN_ID)

    preview = PreviewExport(workspace).execute(
        PreviewExportInput(
            VALID_RUN_ID, title="Chapter 1", publish_date="2026-08-24"
        )
    )

    assert 'chapterTitle: "Chapter 1"' in preview.content
    assert preview.content_hash == sha256_text("Draft")
    assert not (tmp_path / "out.md").exists()
    assert (
        ListExportHistory(workspace).execute(ExportHistoryInput(VALID_RUN_ID))
        == ()
    )


def test_preview_requires_current_approval(tmp_path: Path) -> None:
    """Unapproved artifacts cannot be downloaded, viewed, or copied."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    with pytest.raises(ApprovalRequired):
        PreviewExport(workspace).execute(
            PreviewExportInput(VALID_RUN_ID, title="Title")
        )


def test_identical_reexport_is_idempotent(tmp_path: Path) -> None:
    """Repeating an identical export rewrites the same bytes and
    appends one provenance event per export."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    approve(workspace, VALID_RUN_ID)
    destination = tmp_path / "out.md"

    first = export_draft(workspace, VALID_RUN_ID, destination, title="Title")
    second = export_draft(workspace, VALID_RUN_ID, destination, title="Title")

    assert first.read_text(encoding="utf-8") == second.read_text(
        encoding="utf-8"
    )
    history = ListExportHistory(workspace).execute(
        ExportHistoryInput(VALID_RUN_ID)
    )
    assert len(history) == 2
    assert all(event.content_hash == sha256_text("Draft") for event in history)


def test_different_destination_content_requires_confirmation(
    tmp_path: Path,
) -> None:
    """Foreign bytes at the destination require explicit overwrite."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "draft.sha256").write_text(
        sha256_text("Draft"), encoding="utf-8"
    )
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    approve(workspace, VALID_RUN_ID)
    destination = tmp_path / "out.md"
    destination.write_text("foreign bytes", encoding="utf-8")

    with pytest.raises(CollisionRequired):
        export_draft(workspace, VALID_RUN_ID, destination, title="Title")
    assert destination.read_text(encoding="utf-8") == "foreign bytes"
