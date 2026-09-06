"""Behavior tests for framework-independent application use cases."""

from pathlib import Path

import pytest

from novel_translator.application.inspect import GetChapter, GetChapterInput
from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
)
from novel_translator.application.translate import (
    StartTranslation,
    StartTranslationInput,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.domain.models import ChapterIdentity
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
