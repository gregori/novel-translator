"""Behavior tests for the registered novel and chapter catalog."""

from pathlib import Path

import pytest

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
    RevokeApproval,
)
from novel_translator.application.catalog import (
    ListChapters,
    ListChaptersInput,
    ListNovels,
    ResolveChapter,
    ResolveChapterInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
)
from novel_translator.application.prepare import (
    PrepareTranslation,
    PrepareTranslationInput,
)
from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
)
from novel_translator.application.translate import (
    StartTranslation,
    StartTranslationInput,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.domain.models import (
    ChapterIdentity,
    ChapterState,
    RunEntryError,
)
from novel_translator.domain.translation import (
    SourceDocument,
    TranslationBible,
)
from novel_translator.infrastructure.catalog import NovelRegistry, load_catalog
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.workspace import Workspace

CATALOG_YAML = """novels:
  test-novel:
    title: Test Novel
    run_aliases:
      - legacy-test-novel
    bible: bible.yaml
    source_directory: sources
    kakuyomu_episode_root: https://kakuyomu.jp/works/123/episodes/
    export:
      repository: gregori/novels-site
      directory: src/content/novels/test-novel
      filename_template: "{chapter:03}.md"
    translation:
      provider: opencode-go
      model: test-model
      default_volume: 2
"""


class FakeGateway:
    """Return a deterministic draft without network access."""

    def translate(self, prompt: str) -> str:
        """Return content with an exportable chapter title."""
        return "Episode 1: Draft\n\nEnglish"


def create_registry(tmp_path: Path) -> NovelRegistry:
    """Create one valid catalog and configured source directory."""
    source_directory = tmp_path / "sources"
    source_directory.mkdir()
    bible = tmp_path / "bible.yaml"
    bible.write_text("title: Test Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    return load_catalog(config)


def write_source(
    tmp_path: Path, chapter: int, content: str = "第一章"
) -> Path:
    """Write one configured source file for a chapter."""
    path = tmp_path / "sources" / f"chapter-{chapter}.md"
    path.write_text(content, encoding="utf-8")
    return path


def start_run(
    workspace: Workspace,
    chapter: int,
    source: str,
    novel: str = "test-novel",
) -> str:
    """Persist one completed run for a catalog test."""
    return (
        StartTranslation(workspace, FakeGateway())
        .execute(
            StartTranslationInput(
                ChapterIdentity(novel, chapter),
                SourceDocument(source, f"source-{chapter}"),
                TranslationBible.model_validate({"title": "Test Novel"}),
                "fake",
                "test-model",
            )
        )
        .run_id
    )


def chapter_state(
    registry: NovelRegistry, workspace: Workspace, chapter: int
) -> ChapterState:
    """Return one chapter state from the public listing use case."""
    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )
    return next(
        item.state for item in catalog.chapters if item.chapter == chapter
    )


def test_catalog_lists_registered_novel_and_source_without_runs(
    tmp_path: Path,
) -> None:
    """Configuration, not prior execution, defines the novel catalog."""
    registry = create_registry(tmp_path)
    write_source(tmp_path, 7, "第七話")
    workspace = Workspace(tmp_path / "workspace")

    novels = ListNovels(registry, workspace).execute()
    chapters = ListChapters(registry, workspace).execute(
        ListChaptersInput(" test-novel ")
    )

    assert novels.novels[0].novel == "test-novel"
    assert novels.novels[0].chapter_count == 1
    assert novels.novels[0].run_count == 0
    assert chapters.chapters[0].state is ChapterState.READY
    assert chapters.chapters[0].sources[0].filename == "chapter-7.md"


def test_resolver_requires_choice_for_multiple_valid_runs(
    tmp_path: Path,
) -> None:
    """An ambiguous chapter is never resolved to a run silently."""
    registry = create_registry(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    run_ids = [
        start_run(
            workspace,
            3,
            source,
            "legacy-test-novel" if index == 1 else "test-novel",
        )
        for index, source in enumerate(("第三話", "第三話 改訂"), start=1)
    ]
    resolver = ResolveChapter(registry, workspace)

    with pytest.raises(ValidationError, match="Multiple run candidates"):
        resolver.execute(ResolveChapterInput("test-novel", 3))

    resolved = resolver.execute(
        ResolveChapterInput("test-novel", 3, run_choice=1)
    )
    assert resolved.run_id in run_ids
    assert len(resolved.runs) == 2
    assert all(run_id not in repr(resolved.runs) for run_id in run_ids)


def test_run_choice_matches_the_order_listed_by_chapters(
    tmp_path: Path,
) -> None:
    """An ordinal run choice selects exactly the listed run."""
    registry = create_registry(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    first = start_run(workspace, 3, "第三話")
    second = start_run(workspace, 3, "第三話 改訂")

    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )
    choices = next(item.runs for item in catalog.chapters if item.chapter == 3)

    assert [run.choice for run in choices] == [1, 2]
    assert (
        ResolveChapter(registry, workspace)
        .execute(ResolveChapterInput("test-novel", 3, run_choice=1))
        .run_id
        == first
    )
    assert (
        ResolveChapter(registry, workspace)
        .execute(ResolveChapterInput("test-novel", 3, run_choice=2))
        .run_id
        == second
    )


def test_resolver_makes_no_source_observable(
    tmp_path: Path,
) -> None:
    """Chapter state is observable for chapters without runs."""
    registry = create_registry(tmp_path)
    write_source(tmp_path, 7, "第七話")
    workspace = Workspace(tmp_path / "workspace")

    ready = ResolveChapter(registry, workspace).execute(
        ResolveChapterInput("test-novel", 7)
    )
    no_source = ResolveChapter(registry, workspace).execute(
        ResolveChapterInput("test-novel", 99)
    )

    assert ready.state is ChapterState.READY
    assert ready.run_id is None
    assert no_source.state is ChapterState.NO_SOURCE
    assert no_source.run_id is None
    assert no_source.runs == ()


def test_chapter_state_advances_through_editorial_workflow(
    tmp_path: Path,
) -> None:
    """Aggregate state follows revision, approval, and export."""
    registry = create_registry(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    run_id = start_run(workspace, 4, "第四話")
    assert (
        chapter_state(registry, workspace, 4) is ChapterState.DRAFT_AVAILABLE
    )

    revision = CreateRevision(workspace).execute(
        CreateRevisionInput(run_id, "Episode 4: Reviewed\n\nEnglish")
    )
    assert chapter_state(registry, workspace, 4) is ChapterState.IN_REVIEW

    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(run_id, revision.revision_id)
    )
    assert chapter_state(registry, workspace, 4) is ChapterState.APPROVED

    site_root = tmp_path / "novels-site"
    site_root.mkdir()
    ExportArtifact(workspace, FilesystemArtifactWriter()).execute(
        ExportArtifactInput(
            run_id,
            registry.export_destination("test-novel", 4, site_root),
            revision.revision_id,
        )
    )
    assert chapter_state(registry, workspace, 4) is ChapterState.EXPORTED


def test_exported_state_is_a_historical_fact_after_revocation(
    tmp_path: Path,
) -> None:
    """A later revocation never rewrites the exported historical state."""
    registry = create_registry(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    run_id = start_run(workspace, 4, "第四話")
    revision = CreateRevision(workspace).execute(
        CreateRevisionInput(run_id, "Episode 4: Reviewed\n\nEnglish")
    )
    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(run_id, revision.revision_id)
    )
    site_root = tmp_path / "novels-site"
    site_root.mkdir()
    ExportArtifact(workspace, FilesystemArtifactWriter()).execute(
        ExportArtifactInput(
            run_id,
            registry.export_destination("test-novel", 4, site_root),
            revision.revision_id,
        )
    )

    RevokeApproval(workspace).execute(
        ArtifactApprovalInput(run_id, revision.revision_id)
    )

    assert chapter_state(registry, workspace, 4) is ChapterState.EXPORTED


def test_run_index_keeps_healthy_runs_when_an_entry_is_corrupt(
    tmp_path: Path,
) -> None:
    """A corrupt historical run is reported without hiding healthy chapters."""
    registry = create_registry(tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace = Workspace(workspace_root)
    healthy = start_run(workspace, 5, "第五話")
    corrupt = workspace_root / "runs" / ("0" * 32)
    corrupt.mkdir()
    (corrupt / "run.json").write_text("{not-json", encoding="utf-8")

    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )

    assert catalog.chapters[0].chapter == 5
    assert catalog.chapters[0].runs[0].choice == 1
    assert healthy not in repr(catalog.chapters[0].runs)
    assert catalog.issues[0].entry == "0" * 32
    assert catalog.issues[0].error is RunEntryError.CORRUPT


def test_run_index_reports_foreign_incomplete_and_orphan_entries(
    tmp_path: Path,
) -> None:
    """Every unlistable entry is reported explicitly with its reason."""
    registry = create_registry(tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace = Workspace(workspace_root)
    healthy = start_run(workspace, 5, "第五話")
    orphan = start_run(workspace, 1, "第一章", novel="unregistered-novel")
    runs = workspace_root / "runs"
    foreign = runs / "not-a-run"
    foreign.mkdir()
    incomplete = runs / ("b" * 32)
    incomplete.mkdir()

    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )
    reported = {
        (issue.entry, issue.error)
        for issue in (
            *catalog.issues,
            *ListNovels(registry, workspace).execute().issues,
        )
    }

    assert ("not-a-run", RunEntryError.FOREIGN) in reported
    assert (("b" * 32), RunEntryError.INCOMPLETE) in reported
    assert (orphan, RunEntryError.ORPHAN) in reported
    assert catalog.chapters[0].chapter == 5
    assert catalog.chapters[0].runs[0].status == "draft_completed"
    assert all(chapter.chapter != 1 for chapter in catalog.chapters)
    assert healthy not in repr(catalog.chapters)


def test_editorial_failure_preserves_run_identity_and_state(
    tmp_path: Path,
) -> None:
    """A damaged revision ledger never hides or resets the run to ready."""
    registry = create_registry(tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace = Workspace(workspace_root)
    run_id = start_run(workspace, 6, "第六話")
    revision = CreateRevision(workspace).execute(
        CreateRevisionInput(run_id, "Episode 6: Reviewed\n\nEnglish")
    )
    revision_metadata = (
        workspace_root
        / "runs"
        / run_id
        / "revisions"
        / revision.revision_id
        / "revision.json"
    )
    revision_metadata.write_text("{not-json", encoding="utf-8")

    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )

    assert catalog.chapters[0].chapter == 6
    assert catalog.chapters[0].state is ChapterState.DRAFT_AVAILABLE
    issues = [(issue.entry, issue.error) for issue in catalog.issues]
    assert (run_id, RunEntryError.EDITORIAL) in issues
    assert (
        ResolveChapter(registry, workspace)
        .execute(ResolveChapterInput("test-novel", 6))
        .run_id
        == run_id
    )


def test_prepare_translation_resolves_source_without_run_choice(
    tmp_path: Path,
) -> None:
    """A new translation never requires choosing among existing runs."""
    registry = create_registry(tmp_path)
    source = write_source(tmp_path, 3, "第三話 改訂")
    workspace = Workspace(tmp_path / "workspace")
    start_run(workspace, 3, "第三話")
    start_run(workspace, 3, "第三話 旧")

    prepared = PrepareTranslation(registry).execute(
        PrepareTranslationInput("test-novel", 3)
    )

    assert prepared.source == str(source)
    assert prepared.provider == "opencode-go"
    assert prepared.model == "test-model"
    assert prepared.volume == 2
    assert prepared.bible == registry.resolve_path(Path("bible.yaml"))
    third = start_run(workspace, 3, "第三話 最新")
    catalog = ListChapters(registry, workspace).execute(
        ListChaptersInput("test-novel")
    )
    assert len(catalog.chapters[0].runs) == 3
    assert third not in repr(catalog.chapters[0].runs)


def test_prepare_translation_explicit_source_ignores_ambiguity(
    tmp_path: Path,
) -> None:
    """An explicit source bypasses a configured source ambiguity."""
    registry = create_registry(tmp_path)
    write_source(tmp_path, 1, "第一話")
    alternate = tmp_path / "sources" / "chapter-1.txt"
    alternate.write_text("第一話 別稿", encoding="utf-8")

    with pytest.raises(ValidationError, match="Multiple source candidates"):
        PrepareTranslation(registry).execute(
            PrepareTranslationInput("test-novel", 1)
        )

    prepared = PrepareTranslation(registry).execute(
        PrepareTranslationInput("test-novel", 1, source="custom.txt")
    )
    assert prepared.source == "custom.txt"

    chosen = PrepareTranslation(registry).execute(
        PrepareTranslationInput("test-novel", 1, source_choice=2)
    )
    assert chosen.source == str(alternate)


def test_prepare_translation_requires_a_source_for_unknown_chapter(
    tmp_path: Path,
) -> None:
    """A chapter without sources or runs cannot be prepared blindly."""
    registry = create_registry(tmp_path)

    with pytest.raises(ValidationError, match="no configured source"):
        PrepareTranslation(registry).execute(
            PrepareTranslationInput("test-novel", 99)
        )


def test_prepare_translation_applies_override_precedence(
    tmp_path: Path,
) -> None:
    """Explicit overrides win over every configured default."""
    registry = create_registry(tmp_path)
    write_source(tmp_path, 2, "第二話")
    custom_bible = tmp_path / "custom-bible.yaml"
    custom_bible.write_text("title: Custom\n", encoding="utf-8")

    prepared = PrepareTranslation(registry).execute(
        PrepareTranslationInput(
            "test-novel",
            2,
            bible=custom_bible,
            provider="other-provider",
            model="other-model",
            volume=5,
        )
    )

    assert prepared.bible == custom_bible
    assert prepared.provider == "other-provider"
    assert prepared.model == "other-model"
    assert prepared.volume == 5


def test_prepare_translation_composes_the_registered_episode_url(
    tmp_path: Path,
) -> None:
    """An episode identifier becomes the canonical Kakuyomu source URL."""
    registry = create_registry(tmp_path)

    prepared = PrepareTranslation(registry).execute(
        PrepareTranslationInput("test-novel", 34, episode=" 456 ")
    )

    assert prepared.source == "https://kakuyomu.jp/works/123/episodes/456"


def test_prepare_translation_rejects_invalid_episode_selections(
    tmp_path: Path,
) -> None:
    """Episode input is validated and never combined with an explicit
    source."""
    registry = create_registry(tmp_path)
    write_source(tmp_path, 1, "第一話")

    with pytest.raises(ValidationError, match="must be numeric"):
        PrepareTranslation(registry).execute(
            PrepareTranslationInput(
                "test-novel", 1, episode="../works/999/episodes/1"
            )
        )

    with pytest.raises(ValidationError, match="not both"):
        PrepareTranslation(registry).execute(
            PrepareTranslationInput(
                "test-novel", 1, source="custom.txt", episode="456"
            )
        )


def test_catalog_rejects_a_foreign_episode_root(tmp_path: Path) -> None:
    """Only canonical Kakuyomu work roots can be registered."""
    config = tmp_path / "novels.yaml"
    config.write_text(
        CATALOG_YAML.replace(
            "https://kakuyomu.jp/works/123/episodes/",
            "https://example.test/works/123/episodes/",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="kakuyomu_episode_root"):
        load_catalog(config)
