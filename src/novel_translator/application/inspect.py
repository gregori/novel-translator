"""Typed read use cases for novels, chapters, and runs."""

from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import cast

from novel_translator.application.catalog import (
    ResolveChapter,
    ResolveChapterInput,
)
from novel_translator.application.working_copy import WorkingCopyRepository
from novel_translator.domain.errors import (
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import (
    ArtifactKind,
    ChapterState,
    RevisionRecord,
    WorkingCopy,
)
from novel_translator.infrastructure.catalog import NovelRegistry
from novel_translator.infrastructure.workspace import Workspace


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


@dataclass(frozen=True, slots=True)
class ReadChapterForReviewInput:
    """Select one chapter review surface from friendly choices."""

    novel: str
    chapter: int
    run_choice: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewRevision:
    """One immutable revision with its display ordinal and approval."""

    ordinal: int
    record: RevisionRecord
    approved: bool


@dataclass(frozen=True, slots=True)
class ChapterForReview:
    """Every artifact one review surface renders, degraded per artifact."""

    novel: str
    chapter: int
    state: ChapterState
    run_id: str | None
    run_choice: int | None
    run_status: str
    source: str | None
    draft: str | None
    working_copy: WorkingCopy | None
    draft_approved: bool
    revisions: tuple[ReviewRevision, ...]
    details: dict[str, object]


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


class ReadChapterForReview:
    """Read one chapter's review data with independent degradation.

    The source, draft, revisions, technical run details, and active
    working copy are read separately: one unreadable artifact never
    blanks the others, and a draft stays readable without its source.
    """

    def __init__(
        self,
        registry: NovelRegistry,
        workspace: Workspace,
        working_copies: WorkingCopyRepository,
    ) -> None:
        self._registry = registry
        self._workspace = workspace
        self._working_copies = working_copies
        self._resolve = ResolveChapter(registry, workspace, working_copies)

    def execute(self, request: ReadChapterForReviewInput) -> ChapterForReview:
        """Resolve the run and read each artifact independently."""
        resolved = self._resolve.execute(
            ResolveChapterInput(
                request.novel, request.chapter, request.run_choice
            )
        )
        if resolved.run_id is None:
            return ChapterForReview(
                novel=resolved.novel,
                chapter=resolved.chapter,
                state=resolved.state,
                run_id=None,
                run_choice=None,
                run_status="",
                source=self._source_without_run(
                    resolved.novel, resolved.chapter
                ),
                draft=None,
                draft_approved=False,
                working_copy=None,
                revisions=(),
                details={},
            )
        run_id = resolved.run_id
        details = self._run_details(run_id)
        return ChapterForReview(
            novel=resolved.novel,
            chapter=resolved.chapter,
            state=resolved.state,
            run_id=run_id,
            run_choice=request.run_choice,
            run_status=str(details.get("status", "")),
            source=self._run_source(run_id),
            draft=self._draft(run_id),
            draft_approved=self._draft_approved(run_id),
            working_copy=self._working_copy(run_id),
            revisions=self._revisions(run_id),
            details=details,
        )

    def _source_without_run(self, novel: str, chapter: int) -> str | None:
        """Read the single configured source when no run exists yet."""
        try:
            candidates = self._registry.source_candidates(novel).get(
                chapter, ()
            )
        except NovelTranslatorError:
            return None
        if len(candidates) != 1:
            return None
        try:
            return candidates[0].read_text(encoding="utf-8")
        except OSError, UnicodeError:
            return None

    def _run_details(self, run_id: str) -> dict[str, object]:
        """Read technical run metadata without any chapter content."""
        try:
            data = self._workspace.reader.inspect_run(run_id)
        except NovelTranslatorError:
            data = {}
        with suppress(NovelTranslatorError):
            data["draft_hash"] = self._workspace.runs.recorded_draft_hash(
                run_id
            )
        return data

    def _run_source(self, run_id: str) -> str | None:
        """Read the run's archived source independently of the draft."""
        try:
            return self._workspace.reader.source(run_id)
        except NovelTranslatorError:
            return None

    def _draft(self, run_id: str) -> str | None:
        """Read the generated draft independently of its source."""
        try:
            data = self._workspace.reader.inspect_run(
                run_id, include_draft=True
            )
        except NovelTranslatorError:
            return None
        draft = data.get("draft")
        return draft if isinstance(draft, str) else None

    def _draft_approved(self, run_id: str) -> bool:
        """Report approval of this run's exact generated draft hash."""
        try:
            artifact = self._workspace.runs.generated_draft(run_id)
            return self._workspace.approvals.is_artifact_approved(
                artifact, run_id
            )
        except NovelTranslatorError:
            return False

    def _working_copy(self, run_id: str) -> WorkingCopy | None:
        """Return the run's active working copy when one exists."""
        return self._working_copies.get_by_run(run_id)

    def _revisions(self, run_id: str) -> tuple[ReviewRevision, ...]:
        """List revision metadata and approval state independently."""
        try:
            records = self._workspace.revisions.revision_records(run_id)
            approvals = self._workspace.approvals.latest_approvals(run_id)
        except NovelTranslatorError:
            return ()
        return tuple(
            ReviewRevision(
                ordinal,
                record,
                approvals.get(
                    (
                        ArtifactKind.REVISION,
                        record.revision_id,
                        record.content_hash,
                    ),
                    False,
                )
                is True,
            )
            for ordinal, record in enumerate(records, start=1)
        )
