"""Unit tests for deterministic run bundle export and import."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
)
from novel_translator.application.bundles import (
    ExportRunBundle,
    ExportRunBundleInput,
    ImportRunBundle,
    ImportRunBundleInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
)
from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
)
from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.translation import TranslationBible
from novel_translator.infrastructure.catalog import load_catalog
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text

RUN_ID = "b" * 32
DRAFT = "# Episode 1: Rainy Day\n\nDraft text."


BIBLE_JSON = TranslationBible(title="Novel").model_dump_json()


def seed_run(
    workspace: Path,
    run_id: str = RUN_ID,
    *,
    draft: str = DRAFT,
    source: str = "Source text.",
    bible: str = BIBLE_JSON,
) -> None:
    """Persist one minimal verifiable run through raw workspace files."""
    run_dir = workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "source.txt").write_text(source, encoding="utf-8")
    (run_dir / "draft.md").write_text(draft, encoding="utf-8")
    (run_dir / "draft.sha256").write_text(sha256_text(draft), encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "identity": {"novel": "novel", "chapter": 1},
                "source_hash": sha256_text(source),
                "bible_hash": sha256_text(
                    TranslationBible.model_validate_json(
                        bible
                    ).model_dump_json()
                ),
                "status": "draft_completed",
                "timestamp": "2026-09-06T10:00:00+00:00",
                "provider": "opencode-go",
                "model": "catalog-model",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "bible.json").write_text(bible, encoding="utf-8")
    current = workspace / "current"
    current.mkdir(exist_ok=True)
    (current / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "draft_hash": sha256_text(draft)}),
        encoding="utf-8",
    )


def export_payload(workspace_root: Path, run_id: str = RUN_ID) -> bytes:
    """Export one seeded run into bundle bytes."""
    workspace = Workspace(workspace_root)
    return (
        ExportRunBundle(workspace)
        .execute(ExportRunBundleInput(run_id))
        .payload
    )


def test_export_names_deterministic_zip_without_sessions(
    tmp_path: Path,
) -> None:
    """Bundles sort entries, freeze timestamps, and skip session state."""
    seed_run(tmp_path)
    workspace = Workspace(tmp_path)
    (tmp_path / "working-copies.sqlite").write_bytes(b"session-state")

    result = ExportRunBundle(workspace).execute(ExportRunBundleInput(RUN_ID))

    assert result.run_id == RUN_ID
    assert result.filename == f"novel-ch1-{sha256_text(DRAFT)[:8]}.ntbundle"
    with zipfile.ZipFile(io.BytesIO(result.payload)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        dates = [info.date_time for info in archive.infolist()]
        assert all(day == (1980, 1, 1, 0, 0, 0) for day in dates)
        assert "working-copies.sqlite" not in names
        assert f"runs/{RUN_ID}/source.txt" in names
        assert f"runs/{RUN_ID}/draft.md" in names
        assert f"current/{RUN_ID}.json" in names
        manifest = json.loads(archive.read("bundle.json"))
    assert manifest["run_id"] == RUN_ID
    assert manifest["novel"] == "novel"
    assert manifest["chapter"] == 1
    assert manifest["bundle_version"] == 1


def test_export_includes_revisions_and_ledger_lines(tmp_path: Path) -> None:
    """Revisions plus matching approval and export lines travel along."""
    seed_run(tmp_path)
    workspace = Workspace(tmp_path)
    record = CreateRevision(workspace).execute(
        CreateRevisionInput(
            RUN_ID, "# Episode 1: Rainy Day\n\nRevised text.", None, "polish"
        )
    )
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(RUN_ID, record.revision_id)
    )
    ExportArtifact(workspace, FilesystemArtifactWriter()).execute(
        ExportArtifactInput(
            RUN_ID, tmp_path / "other-novel.md", record.revision_id
        )
    )
    other_id = "c" * 32
    seed_run(
        tmp_path,
        other_id,
        draft="# Episode 1: Rainy Day\n\nOther draft.",
        source="Other src.",
    )
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(other_id, None))

    payload = export_payload(tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert (
            f"runs/{RUN_ID}/revisions/{record.revision_id}/content.md" in names
        )
        approvals = archive.read("editorial/approvals.jsonl").decode()
        exports = archive.read("editorial/exports.jsonl").decode()
    assert other_id not in approvals
    assert other_id not in exports
    assert len(approvals.strip().splitlines()) == 2
    assert len(exports.strip().splitlines()) == 1


def test_export_rejects_unverified_draft(tmp_path: Path) -> None:
    """A draft whose bytes fail verification cannot be bundled."""
    seed_run(tmp_path)
    (tmp_path / "runs" / RUN_ID / "draft.md").write_text(
        "Tampered.", encoding="utf-8"
    )

    with pytest.raises(IntegrityError):
        export_payload(tmp_path)


def test_round_trip_preserves_verified_artifacts(tmp_path: Path) -> None:
    """Import restores every file, the draft, approvals, and exports."""
    seed_run(tmp_path)
    workspace = Workspace(tmp_path)
    record = CreateRevision(workspace).execute(
        CreateRevisionInput(
            RUN_ID, "# Episode 1: Rainy Day\n\nRevised text.", None, None
        )
    )
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    ExportArtifact(workspace, FilesystemArtifactWriter()).execute(
        ExportArtifactInput(RUN_ID, tmp_path / "site.md", None)
    )
    payload = export_payload(tmp_path)

    target = tmp_path / "target"
    result = ImportRunBundle(Workspace(target)).execute(
        ImportRunBundleInput(payload)
    )

    assert (result.run_id, result.novel, result.chapter) == (
        RUN_ID,
        "novel",
        1,
    )
    assert result.created is True
    imported = Workspace(target)
    artifact = imported.runs.generated_draft(RUN_ID)
    assert artifact.content == DRAFT
    _, revision = imported.revisions.revision(RUN_ID, record.revision_id)
    assert revision.content == "# Episode 1: Rainy Day\n\nRevised text."
    assert len(imported.approvals.approval_events(RUN_ID)) == 1
    assert len(imported.exports.events_for_run(RUN_ID)) == 1


def test_reimport_is_idempotent_noop(tmp_path: Path) -> None:
    """Importing identical bytes twice stores no duplicate ledger lines."""
    seed_run(tmp_path)
    workspace = Workspace(tmp_path)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    payload = export_payload(tmp_path)
    target = tmp_path / "target"
    first = ImportRunBundle(Workspace(target)).execute(
        ImportRunBundleInput(payload)
    )
    second = ImportRunBundle(Workspace(target)).execute(
        ImportRunBundleInput(payload)
    )

    assert (first.created, second.created) == (True, False)
    stored = (target / "editorial" / "approvals.jsonl").read_text(
        encoding="utf-8"
    )
    assert len(stored.strip().splitlines()) == 1


def test_divergent_bytes_are_refused(tmp_path: Path) -> None:
    """An existing run with different bytes rejects the bundle loudly."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    target = tmp_path / "target"
    seed_run(
        target,
        draft="# Episode 1: Rainy Day\n\nDifferent draft.",
        source="Different source.",
    )

    with pytest.raises(IntegrityError, match="different content"):
        ImportRunBundle(Workspace(target)).execute(
            ImportRunBundleInput(payload)
        )


def test_tampered_payload_fails_manifest_check(tmp_path: Path) -> None:
    """Rewritten draft bytes without a manifest update fail verification."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }
    entries[f"runs/{RUN_ID}/draft.md"] = b"Tampered draft."
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    tampered = buffer.getvalue()

    with pytest.raises(IntegrityError):
        ImportRunBundle(Workspace(tmp_path / "target")).execute(
            ImportRunBundleInput(tampered)
        )


def test_rejects_non_zip_and_traversal_payloads(tmp_path: Path) -> None:
    """Garbage bytes and escaping entries never reach the workspace."""
    with pytest.raises(ValidationError):
        ImportRunBundle(Workspace(tmp_path)).execute(
            ImportRunBundleInput(b"not a bundle")
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.txt", b"evil")
        archive.writestr("bundle.json", b"{}")
    with pytest.raises(ValidationError):
        ImportRunBundle(Workspace(tmp_path)).execute(
            ImportRunBundleInput(buffer.getvalue())
        )
    assert not (tmp_path / "runs").exists()


def _repack(payload: bytes, mutate) -> bytes:
    """Rebuild bundle bytes after applying a mutation to its entries."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }
    mutate(entries)
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1
    ) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest(entries: dict[str, bytes]) -> dict:
    """Decode the bundle manifest from raw entries."""
    return json.loads(entries["bundle.json"].decode("utf-8"))


def _rehash(entries: dict[str, bytes], name: str) -> None:
    """Refresh the manifest hash after mutating one bundled file."""
    manifest = _manifest(entries)
    manifest["files"][name] = hashlib.sha256(entries[name]).hexdigest()
    entries["bundle.json"] = (json.dumps(manifest) + "\n").encode()


def test_rejects_colon_and_dot_segments(tmp_path: Path) -> None:
    """Drive letters and dot segments are refused."""
    seed_run(tmp_path)

    payloads = [
        _repack(
            export_payload(tmp_path),
            lambda e: e.update(
                {
                    "C:/evil.txt": b"evil",
                }
            ),
        ),
        _repack(
            export_payload(tmp_path),
            lambda e: e.update(
                {
                    f"runs/{RUN_ID}/./evil.txt": b"evil",
                }
            ),
        ),
        _repack(
            export_payload(tmp_path),
            lambda e: e.update(
                {
                    "runs/./evil.txt": b"evil",
                }
            ),
        ),
    ]
    for index, payload in enumerate(payloads):
        with pytest.raises(ValidationError):
            ImportRunBundle(Workspace(tmp_path / f"target-{index}")).execute(
                ImportRunBundleInput(payload)
            )


def test_backslash_entry_never_reaches_workspace(tmp_path: Path) -> None:
    """A backslash entry leaves nothing on disk on any platform.

    The stdlib zip reader normalizes ``\\\\`` to ``/`` on Windows, so the
    rejection surfaces as an integrity failure there and as a validation
    failure where the backslash survives parsing; either way nothing
    reaches the workspace.
    """
    seed_run(tmp_path)
    payload = _repack(
        export_payload(tmp_path),
        lambda e: e.update({f"runs/{RUN_ID}\\evil.txt": b"evil"}),
    )
    target = tmp_path / "target"
    with pytest.raises((ValidationError, IntegrityError)):
        ImportRunBundle(Workspace(target)).execute(
            ImportRunBundleInput(payload)
        )
    assert not (target / "runs").exists()


def test_rejects_other_run_smuggling_and_stray_files(tmp_path: Path) -> None:
    """Sibling run IDs and unlisted top-level files are refused."""
    seed_run(tmp_path)
    other = "d" * 32
    payload = export_payload(tmp_path)

    def add_smuggled(entries: dict[str, bytes]) -> None:
        entries[f"runs/{other}/draft.md"] = b"smuggled"

    def add_stray(entries: dict[str, bytes]) -> None:
        entries["notes.txt"] = b"stray"

    with pytest.raises(ValidationError, match="unexpected file"):
        ImportRunBundle(Workspace(tmp_path / "target-a")).execute(
            ImportRunBundleInput(_repack(payload, add_smuggled))
        )
    with pytest.raises(ValidationError, match="unexpected file"):
        ImportRunBundle(Workspace(tmp_path / "target-b")).execute(
            ImportRunBundleInput(_repack(payload, add_stray))
        )


def test_rejects_bundle_version_and_missing_core_file(tmp_path: Path) -> None:
    """Version drift and absent core files fail before any write."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)

    def bump_version(entries: dict[str, bytes]) -> None:
        manifest = _manifest(entries)
        manifest["bundle_version"] = 999
        entries["bundle.json"] = (json.dumps(manifest) + "\n").encode()

    def drop_source(entries: dict[str, bytes]) -> None:
        del entries[f"runs/{RUN_ID}/source.txt"]

    with pytest.raises(ValidationError, match="version"):
        ImportRunBundle(Workspace(tmp_path / "target-a")).execute(
            ImportRunBundleInput(_repack(payload, bump_version))
        )
    with pytest.raises(ValidationError, match="incomplete"):
        ImportRunBundle(Workspace(tmp_path / "target-b")).execute(
            ImportRunBundleInput(_repack(payload, drop_source))
        )
    assert not (tmp_path / "target-b" / "runs").exists()


def test_dedupes_intra_bundle_ledger_lines(tmp_path: Path) -> None:
    """Repeated ledger lines inside one bundle are stored exactly once."""
    seed_run(tmp_path)
    workspace = Workspace(tmp_path)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    payload = export_payload(tmp_path)

    def duplicate(entries: dict[str, bytes]) -> None:
        raw = entries["editorial/approvals.jsonl"]
        entries["editorial/approvals.jsonl"] = raw + raw
        _rehash(entries, "editorial/approvals.jsonl")

    target = tmp_path / "target"
    ImportRunBundle(Workspace(target)).execute(
        ImportRunBundleInput(_repack(payload, duplicate))
    )
    stored = (target / "editorial" / "approvals.jsonl").read_text(
        encoding="utf-8"
    )
    assert len(stored.strip().splitlines()) == 1


def test_expected_novel_and_chapter_mismatch_stores_nothing(
    tmp_path: Path,
) -> None:
    """Route-scoped expectations reject foreign bundles without persisting."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    target = tmp_path / "target"

    with pytest.raises(ValidationError, match="requested novel"):
        ImportRunBundle(Workspace(target)).execute(
            ImportRunBundleInput(
                payload, expected_novel="other", expected_chapter=1
            )
        )
    with pytest.raises(ValidationError, match="requested novel"):
        ImportRunBundle(Workspace(target)).execute(
            ImportRunBundleInput(
                payload, expected_novel="novel", expected_chapter=9
            )
        )
    assert not (target / "runs").exists()


def test_registry_rejects_unregistered_novel(tmp_path: Path) -> None:
    """A catalog-backed import refuses orphans without storing a run."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    target = tmp_path / "target"
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "chapter-1.md").write_text(
        "source", encoding="utf-8"
    )
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    (tmp_path / "novels.yaml").write_text(
        "novels:\n"
        "  other:\n"
        "    title: Other Novel\n"
        "    bible: bible.yaml\n"
        "    source_directory: sources\n"
        "    export:\n"
        "      repository: gregori/novels-site\n"
        "      directory: src/content/novels/other\n"
        '      filename_template: "{chapter:03}.md"\n'
        "    translation:\n"
        "      provider: opencode-go\n"
        "      model: catalog-model\n",
        encoding="utf-8",
    )
    registry = load_catalog(tmp_path / "novels.yaml")

    with pytest.raises(ValidationError, match="not registered"):
        ImportRunBundle(Workspace(target), registry).execute(
            ImportRunBundleInput(payload)
        )
    assert not (target / "runs").exists()


def test_registry_accepts_registered_novel(tmp_path: Path) -> None:
    """A registered novel passes the catalog gate and stores the run."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "chapter-1.md").write_text(
        "source", encoding="utf-8"
    )
    config = tmp_path / "novels.yaml"
    config.write_text(
        "novels:\n"
        "  novel:\n"
        "    title: Test Novel\n"
        "    bible: bible.yaml\n"
        "    source_directory: sources\n"
        "    export:\n"
        "      repository: gregori/novels-site\n"
        "      directory: src/content/novels/novel\n"
        '      filename_template: "{chapter:03}.md"\n'
        "    translation:\n"
        "      provider: opencode-go\n"
        "      model: catalog-model\n",
        encoding="utf-8",
    )
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    registry = load_catalog(config)
    target = tmp_path / "target"

    result = ImportRunBundle(Workspace(target), registry).execute(
        ImportRunBundleInput(payload)
    )

    assert (result.novel, result.chapter, result.created) == (
        "novel",
        1,
        True,
    )


def test_rejects_zip_bomb_by_uncompressed_total(tmp_path: Path) -> None:
    """Highly compressible entries trip the unpacked-size ceiling."""
    seed_run(tmp_path)
    payload = export_payload(tmp_path)
    filler = b"0" * (300_000_000)

    def add_filler(entries: dict[str, bytes]) -> None:
        entries[f"runs/{RUN_ID}/revisions/filler.bin"] = filler
        _rehash(entries, f"runs/{RUN_ID}/revisions/filler.bin")

    bomb = _repack(payload, add_filler)
    assert len(bomb) < 50_000_000
    with pytest.raises(ValidationError, match="unpacked"):
        ImportRunBundle(Workspace(tmp_path / "target")).execute(
            ImportRunBundleInput(bomb)
        )
    assert not (tmp_path / "target" / "runs").exists()
