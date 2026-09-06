"""Typed read use cases for novels, chapters, and runs."""

from dataclasses import asdict, dataclass
from typing import cast

from novel_translator.domain.errors import (
    IntegrityError,
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import RunEntryError, RunEntryIssue
from novel_translator.infrastructure.workspace import Workspace


@dataclass(frozen=True, slots=True)
class ListChaptersInput:
    """Filter chapters by canonical novel identifier."""

    novel: str


@dataclass(frozen=True, slots=True)
class NovelSummary:
    """Aggregate run counts for one novel."""

    novel: str
    chapter_count: int
    run_count: int


@dataclass(frozen=True, slots=True)
class NovelCatalog:
    """Novel aggregates plus typed issues for skipped run entries."""

    novels: tuple[NovelSummary, ...]
    issues: tuple[RunEntryIssue, ...]


@dataclass(frozen=True, slots=True)
class ChapterSummary:
    """One persisted run in a novel chapter listing."""

    run_id: str
    novel: str
    chapter: int
    status: str
    timestamp: str
    volume: int | None


@dataclass(frozen=True, slots=True)
class ChapterCatalog:
    """Chapter runs for one novel plus typed skipped-entry issues."""

    chapters: tuple[ChapterSummary, ...]
    issues: tuple[RunEntryIssue, ...]


@dataclass(frozen=True, slots=True)
class GetChapterInput:
    """Select one run or immutable revision for inspection."""

    run_id: str
    include_source: bool = False
    include_draft: bool = False
    revision_id: str | None = None
    include_content: bool = False


@dataclass(frozen=True, slots=True)
class ChapterDetails:
    """Typed envelope around persisted run or revision fields."""

    run_id: str
    data: dict[str, object]


def _summary(workspace: Workspace, run_id: str) -> ChapterSummary:
    metadata = workspace.reader.inspect_run(run_id)
    identity_value = metadata.get("identity")
    if not isinstance(identity_value, dict):
        raise IntegrityError("Run identity is invalid.")
    identity = cast(dict[str, object], identity_value)
    novel = identity.get("novel")
    chapter = identity.get("chapter")
    status = metadata.get("status")
    timestamp = metadata.get("timestamp")
    volume = metadata.get("volume")
    if (
        not isinstance(novel, str)
        or not novel.strip()
        or type(chapter) is not int
        or not isinstance(status, str)
        or not isinstance(timestamp, str)
        or (volume is not None and (type(volume) is not int or volume < 1))
    ):
        raise IntegrityError("Run summary metadata is invalid.")
    return ChapterSummary(run_id, novel, chapter, status, timestamp, volume)


def _catalog(
    workspace: Workspace,
) -> tuple[tuple[ChapterSummary, ...], tuple[RunEntryIssue, ...]]:
    """Summarize every listable run, typing each skipped entry."""
    catalog = workspace.reader.run_catalog()
    summaries: list[ChapterSummary] = []
    issues = list(catalog.issues)
    for run_id in catalog.run_ids:
        try:
            summaries.append(_summary(workspace, run_id))
        except NovelTranslatorError:
            issues.append(RunEntryIssue(run_id, RunEntryError.CORRUPT))
    issues.sort(key=lambda issue: (issue.entry, issue.error.value))
    return tuple(summaries), tuple(issues)


class ListNovels:
    """List novels discovered from persisted runs."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self) -> NovelCatalog:
        """Return stable novel summaries plus typed skipped-entry issues."""
        summaries, issues = _catalog(self._workspace)
        chapters: dict[str, set[int]] = {}
        runs: dict[str, int] = {}
        for item in summaries:
            chapters.setdefault(item.novel, set()).add(item.chapter)
            runs[item.novel] = runs.get(item.novel, 0) + 1
        novels = tuple(
            NovelSummary(novel, len(chapters[novel]), runs[novel])
            for novel in sorted(runs)
        )
        return NovelCatalog(novels, issues)


class ListChapters:
    """List every persisted run for one novel."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: ListChaptersInput) -> ChapterCatalog:
        """Return chapter runs without silently selecting among duplicates."""
        novel = request.novel.strip()
        if not novel:
            raise ValidationError("Novel must be non-empty.")
        summaries, issues = _catalog(self._workspace)
        chapters = tuple(
            sorted(
                (item for item in summaries if item.novel == novel),
                key=lambda item: (item.chapter, item.timestamp, item.run_id),
            )
        )
        return ChapterCatalog(chapters, issues)


class GetChapter:
    """Read one explicitly selected run or revision."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: GetChapterInput) -> ChapterDetails:
        """Return selected data while keeping content opt-in."""
        if request.include_content and request.revision_id is None:
            raise ValidationError(
                "include_content requires an immutable revision selection."
            )
        if request.revision_id is None:
            data = self._workspace.reader.inspect_run(
                request.run_id, request.include_draft
            )
            if request.include_source:
                data["source"] = self._workspace.reader.source(request.run_id)
        else:
            record, artifact = self._workspace.revisions.revision(
                request.run_id, request.revision_id
            )
            data = cast(dict[str, object], asdict(record))
            data["approved"] = self._workspace.approvals.is_artifact_approved(
                artifact, request.run_id
            )
            if request.include_source:
                data["source"] = self._workspace.reader.source(request.run_id)
            if request.include_draft:
                data["draft"] = self._workspace.reader.inspect_run(
                    request.run_id, include_draft=True
                )["draft"]
            if request.include_content:
                data["content"] = artifact.content
        return ChapterDetails(request.run_id, data)
