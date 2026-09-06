"""Behavior tests for framework-independent application use cases."""

import json
from pathlib import Path

import pytest

from novel_translator.application.inspect import (
    GetChapter,
    GetChapterInput,
    ListChapters,
    ListChaptersInput,
    ListNovels,
    NovelSummary,
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
    RunEntryError,
    RunEntryIssue,
)
from novel_translator.domain.translation import (
    SourceDocument,
    TranslationBible,
)
from novel_translator.infrastructure.workspace import Workspace


class FakeGateway:
    """Return deterministic translations without network access."""

    def translate(self, prompt: str) -> str:
        """Translate one prompt deterministically."""
        return "Episode 1: Draft\n\nEnglish"


def start_run(
    workspace: Workspace, novel: str, chapter: int, source: str
) -> str:
    """Start one translation run and return its run identifier."""
    return (
        StartTranslation(workspace, FakeGateway())
        .execute(
            StartTranslationInput(
                ChapterIdentity(novel, chapter),
                SourceDocument(source, f"source-{chapter}"),
                TranslationBible.model_validate({"title": "Novel"}),
                "fake",
                "fake-model",
            )
        )
        .run_id
    )


def test_chapter_listing_preserves_ambiguous_runs_for_explicit_selection(
    tmp_path: Path,
) -> None:
    """Two valid runs for a chapter remain visible with their exact sources."""
    workspace = Workspace(tmp_path)
    run_sources = {
        start_run(workspace, "novel", 1, source): source
        for source in ("第一話", "第一話 改訂")
    }

    novels = ListNovels(workspace).execute()
    chapters = ListChapters(workspace).execute(ListChaptersInput("novel"))
    selected_sources = {
        run_id: GetChapter(workspace)
        .execute(GetChapterInput(run_id, include_source=True))
        .data["source"]
        for run_id in run_sources
    }

    assert novels.novels == (NovelSummary("novel", 1, 2),)
    assert {chapter.run_id for chapter in chapters.chapters} == set(
        run_sources
    )
    assert selected_sources == run_sources
    expected = sorted(
        run_sources,
        key=lambda run_id: (
            1,
            str(workspace.reader.inspect_run(run_id)["timestamp"]),
            run_id,
        ),
    )
    assert [chapter.run_id for chapter in chapters.chapters] == expected


def test_chapter_listing_is_deterministic_and_normalizes_novel(
    tmp_path: Path,
) -> None:
    """Listings are stable, chapter-ordered, and accept padded identifiers."""
    workspace = Workspace(tmp_path)
    start_run(workspace, "novel", 2, "第二話")
    start_run(workspace, "novel", 1, "第一話")
    start_run(workspace, "other", 1, "other chapter")

    chapters = ListChapters(workspace).execute(ListChaptersInput("  novel  "))
    repeated = ListChapters(workspace).execute(ListChaptersInput("novel"))
    other = ListChapters(workspace).execute(ListChaptersInput("other"))

    assert [chapter.chapter for chapter in chapters.chapters] == [1, 2]
    assert all(chapter.novel == "novel" for chapter in chapters.chapters)
    assert [chapter.chapter for chapter in other.chapters] == [1]
    assert repeated.chapters == chapters.chapters
    assert repeated.issues == chapters.issues


def test_listing_rejects_blank_novel_with_typed_validation_error(
    tmp_path: Path,
) -> None:
    """A blank novel filter fails as a domain validation error."""
    workspace = Workspace(tmp_path)
    start_run(workspace, "novel", 1, "第一話")

    with pytest.raises(ValidationError, match="Novel must be non-empty"):
        ListChapters(workspace).execute(ListChaptersInput("   "))


def test_listing_survives_foreign_incomplete_and_corrupt_run_entries(
    tmp_path: Path,
) -> None:
    """Healthy runs stay listed while damaged entries
    surface as typed issues."""
    workspace = Workspace(tmp_path)
    healthy = start_run(workspace, "novel", 1, "第一話")
    runs = tmp_path / "runs"
    (runs / "notes.txt").write_text("stray file", encoding="utf-8")
    (runs / ("0" * 32)).mkdir()
    corrupt = runs / ("1" * 32)
    corrupt.mkdir()
    (corrupt / "run.json").write_text("{ not json", encoding="utf-8")
    identity_less = runs / ("2" * 32)
    identity_less.mkdir()
    (identity_less / "run.json").write_text(
        json.dumps({"run_id": "2" * 32}), encoding="utf-8"
    )

    novels = ListNovels(workspace).execute()
    chapters = ListChapters(workspace).execute(ListChaptersInput("novel"))

    assert [chapter.run_id for chapter in chapters.chapters] == [healthy]
    assert novels.novels == (NovelSummary("novel", 1, 1),)
    assert chapters.issues == (
        RunEntryIssue("0" * 32, RunEntryError.INCOMPLETE),
        RunEntryIssue("1" * 32, RunEntryError.CORRUPT),
        RunEntryIssue("2" * 32, RunEntryError.CORRUPT),
        RunEntryIssue("notes.txt", RunEntryError.FOREIGN),
    )
    assert novels.issues == chapters.issues


def test_get_chapter_rejects_content_without_revision_selection(
    tmp_path: Path,
) -> None:
    """Content requires an immutable revision; it is not read from a run."""
    workspace = Workspace(tmp_path)
    run_id = start_run(workspace, "novel", 1, "第一話")

    with pytest.raises(ValidationError, match="revision"):
        GetChapter(workspace).execute(
            GetChapterInput(run_id, include_content=True)
        )


def test_get_chapter_honors_flags_for_revision_selection(
    tmp_path: Path,
) -> None:
    """Revision inspection includes the exact source and
    draft only on request."""
    workspace = Workspace(tmp_path)
    run_id = start_run(workspace, "novel", 1, "第一話")
    revision = CreateRevision(workspace).execute(
        CreateRevisionInput(run_id, "Episode 1: Draft\n\nEnglish edited")
    )

    details = GetChapter(workspace).execute(
        GetChapterInput(
            run_id,
            include_source=True,
            include_draft=True,
            revision_id=revision.revision_id,
            include_content=True,
        )
    )
    minimal = GetChapter(workspace).execute(
        GetChapterInput(run_id, revision_id=revision.revision_id)
    )

    assert details.data["source"] == "第一話"
    assert details.data["draft"] == "Episode 1: Draft\n\nEnglish"
    assert details.data["content"] == "Episode 1: Draft\n\nEnglish edited"
    assert details.data["revision_id"] == revision.revision_id
    assert "source" not in minimal.data
    assert "draft" not in minimal.data
    assert "content" not in minimal.data
