"""Integration tests for working copy persistence and concurrency."""

from pathlib import Path

import pytest

from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
)
from novel_translator.application.working_copy import (
    CreateRevisionFromWorkingCopy,
    CreateRevisionFromWorkingCopyInput,
    DiscardWorkingCopy,
    DiscardWorkingCopyInput,
    GetWorkingCopy,
    GetWorkingCopyDiff,
    GetWorkingCopyDiffInput,
    GetWorkingCopyInput,
    SaveWorkingCopy,
    SaveWorkingCopyInput,
    StartWorkingCopy,
    StartWorkingCopyInput,
)
from novel_translator.domain.errors import IntegrityError, WorkingCopyConflict
from novel_translator.domain.models import (
    ArtifactKind,
    RevisionParentKind,
    WorkingCopy,
)
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.working_copies import (
    SqlAlchemyWorkingCopyRepository,
)
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text

RUN_ID = "1" * 32
DRAFT = "Episode 1: Test\n\nDraft"


def environment(
    tmp_path: Path,
) -> tuple[Workspace, SqlAlchemyWorkingCopyRepository]:
    """Compose a migrated database beside a workspace with a draft."""
    workspace = Workspace(tmp_path / "workspace")
    run_dir = tmp_path / "workspace" / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        '{"identity": {"chapter": 1}}', encoding="utf-8"
    )
    workspace.runs.save_draft(RUN_ID, DRAFT)
    database = Database(str(tmp_path / "app.db"))
    database.prepare()
    return workspace, SqlAlchemyWorkingCopyRepository(database)


def started_copy(
    workspace: Workspace, working_copies: SqlAlchemyWorkingCopyRepository
) -> WorkingCopy:
    """Start the run's working copy in one call."""
    return StartWorkingCopy(workspace, working_copies).execute(
        StartWorkingCopyInput(RUN_ID)
    )


def fetched_copy(
    working_copies: SqlAlchemyWorkingCopyRepository,
) -> WorkingCopy | None:
    """Read the run's active working copy in one call."""
    return GetWorkingCopy(working_copies).execute(GetWorkingCopyInput(RUN_ID))


def test_start_seeds_from_verified_draft_and_draft_stays_immutable(
    tmp_path: Path,
) -> None:
    """Saving a working copy never changes the generated draft."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    assert started.base_artifact_kind is ArtifactKind.GENERATED_DRAFT
    assert started.base_artifact_id is None
    assert started.base_content_hash == sha256_text(DRAFT)
    assert started.content == DRAFT
    assert started.version == 1
    saved = SaveWorkingCopy(working_copies).execute(
        SaveWorkingCopyInput(started.id, 1, "Episode 1: Edited\n\nTab")
    )
    assert saved.version == 2
    assert fetched_copy(working_copies) == saved
    draft = tmp_path / "workspace" / "runs" / RUN_ID / "draft.md"
    assert draft.read_text(encoding="utf-8") == DRAFT


def test_stale_save_conflict_exposes_both_contents(tmp_path: Path) -> None:
    """A save racing a newer version never silently overwrites it."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    SaveWorkingCopy(working_copies).execute(
        SaveWorkingCopyInput(started.id, 1, "Saved by tab one")
    )
    with pytest.raises(WorkingCopyConflict) as details:
        SaveWorkingCopy(working_copies).execute(
            SaveWorkingCopyInput(started.id, 1, "Saved by tab two")
        )
    conflict = details.value
    assert conflict.current_content == "Saved by tab one"
    assert conflict.current_version == 2
    assert conflict.submitted_content == "Saved by tab two"
    assert conflict.submitted_version == 1
    persisted = fetched_copy(working_copies)
    assert persisted is not None
    assert persisted.content == "Saved by tab one"
    assert persisted.version == 2


def test_single_active_working_copy_per_run_and_discard_leaves_artifacts(
    tmp_path: Path,
) -> None:
    """Discard removes only the working copy and allows a fresh start."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    with pytest.raises(IntegrityError):
        started_copy(workspace, working_copies)
    DiscardWorkingCopy(working_copies).execute(
        DiscardWorkingCopyInput(started.id)
    )
    assert fetched_copy(working_copies) is None
    with pytest.raises(IntegrityError):
        SaveWorkingCopy(working_copies).execute(
            SaveWorkingCopyInput(started.id, 1, "Too late")
        )
    draft = tmp_path / "workspace" / "runs" / RUN_ID / "draft.md"
    assert draft.read_text(encoding="utf-8") == DRAFT
    assert workspace.revisions.revision_records(RUN_ID) == []
    restarted = started_copy(workspace, working_copies)
    assert restarted.version == 1
    assert restarted.id != started.id


def test_start_uses_latest_revision_as_base(tmp_path: Path) -> None:
    """A fresh working copy continues from the latest revision."""
    workspace, working_copies = environment(tmp_path)
    first = CreateRevision(workspace).execute(
        CreateRevisionInput(RUN_ID, "Episode 1: Reviewed\n\nFirst")
    )
    started = started_copy(workspace, working_copies)
    assert started.base_artifact_kind is ArtifactKind.REVISION
    assert started.base_artifact_id == first.revision_id
    assert started.base_content_hash == first.content_hash
    assert started.content == "Episode 1: Reviewed\n\nFirst"
    record = CreateRevisionFromWorkingCopy(workspace, working_copies).execute(
        CreateRevisionFromWorkingCopyInput(RUN_ID, started.id)
    )
    assert record.parent.kind is RevisionParentKind.REVISION
    assert record.parent.revision_id == first.revision_id
    assert record.parent.content_hash == first.content_hash


def test_revision_from_working_copy_points_to_exact_parent(
    tmp_path: Path,
) -> None:
    """Freezing a working copy records its exact base and hash."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    edited = SaveWorkingCopy(working_copies).execute(
        SaveWorkingCopyInput(started.id, 1, "Episode 1: Frozen\n\nEdit")
    )
    record = CreateRevisionFromWorkingCopy(workspace, working_copies).execute(
        CreateRevisionFromWorkingCopyInput(RUN_ID, edited.id)
    )
    assert record.parent.kind is RevisionParentKind.GENERATED_DRAFT
    assert record.parent.revision_id is None
    assert record.parent.content_hash == sha256_text(DRAFT)
    assert record.parent.content_available is True
    assert record.content_hash == sha256_text("Episode 1: Frozen\n\nEdit")
    assert fetched_copy(working_copies) is None
    _, artifact = workspace.revisions.revision(RUN_ID, record.revision_id)
    assert artifact.content == "Episode 1: Frozen\n\nEdit"


def test_diff_and_freeze_reject_corrupted_base(tmp_path: Path) -> None:
    """A corrupted base blocks diffs and freezing without leftovers."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    SaveWorkingCopy(working_copies).execute(
        SaveWorkingCopyInput(started.id, 1, "Edited\n\nSurvives")
    )
    diff = GetWorkingCopyDiff(workspace, working_copies).execute(
        GetWorkingCopyDiffInput(started.id)
    )
    assert "+Edited" in diff.content
    assert "--- generated_draft" in diff.content
    draft = tmp_path / "workspace" / "runs" / RUN_ID / "draft.md"
    draft.write_text("tampered", encoding="utf-8")
    with pytest.raises(IntegrityError):
        GetWorkingCopyDiff(workspace, working_copies).execute(
            GetWorkingCopyDiffInput(started.id)
        )
    with pytest.raises(IntegrityError):
        CreateRevisionFromWorkingCopy(workspace, working_copies).execute(
            CreateRevisionFromWorkingCopyInput(RUN_ID, started.id)
        )
    assert workspace.revisions.revision_records(RUN_ID) == []
    assert fetched_copy(working_copies) is not None


def test_prepare_migrates_empty_database_idempotently(
    tmp_path: Path,
) -> None:
    """Repeated prepare calls keep an empty database usable."""
    database = Database(str(tmp_path / "app.db"))
    database.prepare()
    database.prepare()
    working_copies = SqlAlchemyWorkingCopyRepository(database)
    assert working_copies.get_by_run(RUN_ID) is None


def test_prepare_migrates_shared_in_memory_database() -> None:
    """Alembic upgrades the same in-memory connection used by sessions."""
    database = Database(":memory:")

    database.prepare()
    working_copies = SqlAlchemyWorkingCopyRepository(database)

    assert working_copies.get_by_run(RUN_ID) is None


def test_freeze_rejects_working_copy_based_on_superseded_artifact(
    tmp_path: Path,
) -> None:
    """A concurrent immutable revision prevents a stale branch."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    CreateRevision(workspace).execute(
        CreateRevisionInput(RUN_ID, "Episode 1: Concurrent\n\nRevision")
    )

    with pytest.raises(IntegrityError, match="no longer the latest"):
        CreateRevisionFromWorkingCopy(workspace, working_copies).execute(
            CreateRevisionFromWorkingCopyInput(RUN_ID, started.id)
        )

    assert fetched_copy(working_copies) == started
    assert len(workspace.revisions.revision_records(RUN_ID)) == 1


def test_freeze_retry_is_idempotent_after_delete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial cross-store failure reuses one deterministic revision."""
    workspace, working_copies = environment(tmp_path)
    started = started_copy(workspace, working_copies)
    delete = working_copies.delete
    attempts = 0

    def fail_once(working_copy_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated SQLite failure")
        delete(working_copy_id)

    monkeypatch.setattr(working_copies, "delete", fail_once)
    freeze = CreateRevisionFromWorkingCopy(workspace, working_copies)
    request = CreateRevisionFromWorkingCopyInput(RUN_ID, started.id)

    with pytest.raises(OSError, match="simulated"):
        freeze.execute(request)
    retried = freeze.execute(request)
    after_delete = freeze.execute(request)

    assert retried.revision_id == started.id
    assert after_delete == retried
    assert len(workspace.revisions.revision_records(RUN_ID)) == 1
    assert fetched_copy(working_copies) is None
