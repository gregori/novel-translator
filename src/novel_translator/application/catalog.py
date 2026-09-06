"""Registered novel catalog, chapter aggregation, and friendly resolution."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from novel_translator.domain.errors import (
    IntegrityError,
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import (
    ArtifactKey,
    ArtifactKind,
    ChapterState,
    RunEntryError,
    RunEntryIssue,
    RunStatus,
)
from novel_translator.infrastructure.catalog import NovelRegistry
from novel_translator.infrastructure.workspace import Workspace


@dataclass(frozen=True, slots=True)
class ListChaptersInput:
    """Select chapters for one registered novel."""

    novel: str


@dataclass(frozen=True, slots=True)
class ResolveChapterInput:
    """Select one chapter and an optional friendly run choice."""

    novel: str
    chapter: int
    run_choice: int | None = None


@dataclass(frozen=True, slots=True)
class RunChoice:
    """Display-safe selection for one indexed run."""

    choice: int
    status: str
    timestamp: str
    model: str
    volume: int | None


@dataclass(frozen=True, slots=True)
class SourceChoice:
    """Display-safe selection for one configured source file."""

    choice: int
    filename: str


@dataclass(frozen=True, slots=True)
class NovelSummary:
    """One configured novel with aggregate chapter and run counts."""

    novel: str
    title: str
    chapter_count: int
    run_count: int


@dataclass(frozen=True, slots=True)
class NovelCatalog:
    """Configured novels plus typed issues from existing runs."""

    novels: tuple[NovelSummary, ...]
    issues: tuple[RunEntryIssue, ...]


@dataclass(frozen=True, slots=True)
class ChapterSummary:
    """Aggregated source, editorial state, and friendly run choices."""

    novel: str
    chapter: int
    state: ChapterState
    sources: tuple[SourceChoice, ...]
    runs: tuple[RunChoice, ...]

    @property
    def source_selection_required(self) -> bool:
        """Return whether more than one configured source must be chosen."""
        return len(self.sources) > 1

    @property
    def run_selection_required(self) -> bool:
        """Return whether more than one valid run must be chosen."""
        return len(self.runs) > 1


@dataclass(frozen=True, slots=True)
class ChapterCatalog:
    """Aggregated chapters for one registered novel."""

    chapters: tuple[ChapterSummary, ...]
    issues: tuple[RunEntryIssue, ...]


@dataclass(frozen=True, slots=True)
class ResolvedChapter:
    """Run identity and aggregate state resolved from friendly choices."""

    novel: str
    chapter: int
    state: ChapterState
    run_id: str | None
    runs: tuple[RunChoice, ...]


@dataclass(frozen=True, slots=True)
class _IndexedRun:
    run_id: str
    novel: str
    chapter: int
    status: RunStatus
    timestamp: str
    model: str
    volume: int | None
    has_revision: bool
    approved: bool
    exported: bool


def select_candidate[T](
    values: Sequence[T], choice: int | None, kind: str
) -> T | None:
    """Select a singleton automatically, but never an ambiguity."""
    if not values:
        if choice is not None:
            raise ValidationError(f"No {kind} candidates are available.")
        return None
    if choice is None:
        if len(values) == 1:
            return values[0]
        raise ValidationError(
            f"Multiple {kind} candidates exist; choose 1-{len(values)}."
        )
    if choice < 1 or choice > len(values):
        raise ValidationError(
            f"Invalid {kind} choice; choose 1-{len(values)}."
        )
    return values[choice - 1]


def _editorial_state(
    workspace: Workspace,
    run_id: str,
    status: RunStatus,
    approvals: dict[ArtifactKey, bool],
    exports: frozenset[ArtifactKey],
) -> tuple[bool, bool, bool]:
    """Project revision, approval, and export flags from metadata only."""
    records = workspace.revisions.revision_records(run_id)
    keys: list[ArtifactKey] = [
        (ArtifactKind.REVISION, record.revision_id, record.content_hash)
        for record in records
    ]
    if status is RunStatus.DRAFT_COMPLETED:
        keys.append(
            (
                ArtifactKind.GENERATED_DRAFT,
                None,
                workspace.runs.recorded_draft_hash(run_id),
            )
        )
    approved = any(approvals.get(key) is True for key in keys)
    exported = any(key in exports for key in keys)
    return bool(records), approved, exported


def _indexed_run(
    workspace: Workspace,
    run_id: str,
    approvals_by_run: dict[str, dict[ArtifactKey, bool]],
    exports_by_run: dict[str, frozenset[ArtifactKey]],
) -> tuple[_IndexedRun, RunEntryIssue | None]:
    """Index one run while separating metadata from editorial damage."""
    metadata = workspace.reader.inspect_run(run_id)
    identity_value = metadata.get("identity")
    if not isinstance(identity_value, dict):
        raise IntegrityError("Run identity is invalid.")
    identity = cast(dict[str, object], identity_value)
    novel = identity.get("novel")
    chapter = identity.get("chapter")
    timestamp = metadata.get("timestamp")
    model = metadata.get("model")
    volume = metadata.get("volume")
    status_value = metadata.get("status")
    if not isinstance(status_value, str):
        raise IntegrityError("Run status is invalid.")
    try:
        status = RunStatus(status_value)
    except ValueError as error:
        raise IntegrityError("Run status is invalid.") from error
    if (
        not isinstance(novel, str)
        or not novel.strip()
        or type(chapter) is not int
        or chapter < 1
        or not isinstance(timestamp, str)
        or not isinstance(model, str)
        or not model.strip()
        or (volume is not None and (type(volume) is not int or volume < 1))
    ):
        raise IntegrityError("Run summary metadata is invalid.")
    try:
        has_revision, approved, exported = _editorial_state(
            workspace,
            run_id,
            status,
            approvals_by_run.get(run_id, {}),
            exports_by_run.get(run_id, frozenset()),
        )
    except NovelTranslatorError:
        has_revision = False
        approved = False
        exported = False
        issue: RunEntryIssue | None = RunEntryIssue(
            run_id, RunEntryError.EDITORIAL
        )
    else:
        issue = None
    return (
        _IndexedRun(
            run_id,
            novel,
            chapter,
            status,
            timestamp,
            model,
            volume,
            has_revision,
            approved,
            exported,
        ),
        issue,
    )


def _ledger_projection[E](load: Callable[[], E]) -> E | None:
    """Load one whole-ledger projection, or None when it is invalid."""
    try:
        return load()
    except NovelTranslatorError:
        return None


def _run_index(
    workspace: Workspace,
    known_identities: frozenset[str],
) -> tuple[tuple[_IndexedRun, ...], tuple[RunEntryIssue, ...]]:
    """Index claimable runs while isolating damaged or orphan entries."""
    catalog = workspace.reader.run_catalog()
    approvals_by_run = _ledger_projection(
        workspace.approvals.latest_approvals_by_run
    )
    exports_by_run = _ledger_projection(workspace.exports.exported_keys_by_run)
    indexed: list[_IndexedRun] = []
    issues = list(catalog.issues)
    for run_id in catalog.run_ids:
        try:
            run, issue = _indexed_run(
                workspace, run_id, approvals_by_run or {}, exports_by_run or {}
            )
        except NovelTranslatorError:
            issues.append(RunEntryIssue(run_id, RunEntryError.CORRUPT))
            continue
        if issue is not None:
            issues.append(issue)
        if approvals_by_run is None or exports_by_run is None:
            issues.append(RunEntryIssue(run_id, RunEntryError.EDITORIAL))
        if run.novel not in known_identities:
            issues.append(RunEntryIssue(run_id, RunEntryError.ORPHAN))
            continue
        indexed.append(run)
    indexed.sort(
        key=lambda item: (
            item.novel,
            item.chapter,
            item.timestamp,
            item.run_id,
        )
    )
    issues = list(dict.fromkeys(issues))
    issues.sort(key=lambda issue: (issue.entry, issue.error.value))
    return tuple(indexed), tuple(issues)


def _chapter_state(
    sources: tuple[Path, ...], runs: tuple[_IndexedRun, ...]
) -> ChapterState:
    """Aggregate the most actionable persisted state for one chapter."""
    if any(run.exported for run in runs):
        return ChapterState.EXPORTED
    if any(run.approved for run in runs):
        return ChapterState.APPROVED
    if any(run.has_revision for run in runs):
        return ChapterState.IN_REVIEW
    if any(run.status is RunStatus.DRAFT_COMPLETED for run in runs):
        return ChapterState.DRAFT_AVAILABLE
    if any(
        run.status in {RunStatus.STARTED, RunStatus.TRANSLATING}
        for run in runs
    ):
        return ChapterState.TRANSLATING
    if runs:
        return ChapterState.FAILED
    if sources:
        return ChapterState.READY
    return ChapterState.NO_SOURCE


def _summaries(
    registry: NovelRegistry,
    novel: str,
    indexed: tuple[_IndexedRun, ...],
) -> tuple[ChapterSummary, ...]:
    """Group configured sources and indexed runs by chapter."""
    source_index = registry.source_candidates(novel)
    identities = registry.run_identities(novel)
    run_index: dict[int, list[_IndexedRun]] = {}
    for run in indexed:
        if run.novel in identities:
            run_index.setdefault(run.chapter, []).append(run)
    chapters = sorted(set(source_index) | set(run_index))
    summaries: list[ChapterSummary] = []
    for chapter in chapters:
        source_paths = source_index.get(chapter, ())
        chapter_runs = tuple(run_index.get(chapter, ()))
        sources = tuple(
            SourceChoice(choice, path.name)
            for choice, path in enumerate(source_paths, start=1)
        )
        runs = tuple(
            RunChoice(
                choice,
                run.status.value,
                run.timestamp,
                run.model,
                run.volume,
            )
            for choice, run in enumerate(chapter_runs, start=1)
        )
        summaries.append(
            ChapterSummary(
                novel,
                chapter,
                _chapter_state(source_paths, chapter_runs),
                sources,
                runs,
            )
        )
    return tuple(summaries)


class ListNovels:
    """List configured novels with counts from sources and existing runs."""

    def __init__(self, registry: NovelRegistry, workspace: Workspace) -> None:
        self._registry = registry
        self._workspace = workspace

    def execute(self) -> NovelCatalog:
        """Return every registered novel, including those without runs."""
        indexed, issues = _run_index(
            self._workspace, self._registry.all_run_identities()
        )
        novels: list[NovelSummary] = []
        for novel_id, config in sorted(self._registry.config.novels.items()):
            identities = self._registry.run_identities(novel_id)
            novels.append(
                NovelSummary(
                    novel_id,
                    config.title,
                    len(_summaries(self._registry, novel_id, indexed)),
                    sum(run.novel in identities for run in indexed),
                )
            )
        return NovelCatalog(tuple(novels), issues)


class ListChapters:
    """List aggregated chapters for one registered novel."""

    def __init__(self, registry: NovelRegistry, workspace: Workspace) -> None:
        self._registry = registry
        self._workspace = workspace

    def execute(self, request: ListChaptersInput) -> ChapterCatalog:
        """Return stable chapter summaries without selecting a run."""
        novel = request.novel.strip()
        self._registry.novel(novel)
        indexed, issues = _run_index(
            self._workspace, self._registry.all_run_identities()
        )
        return ChapterCatalog(
            _summaries(self._registry, novel, indexed), issues
        )


class ResolveChapter:
    """Resolve one chapter's run and aggregate state from choices."""

    def __init__(self, registry: NovelRegistry, workspace: Workspace) -> None:
        self._registry = registry
        self._workspace = workspace

    def execute(self, request: ResolveChapterInput) -> ResolvedChapter:
        """Resolve an unambiguous run or require an explicit valid choice."""
        if request.chapter < 1:
            raise ValidationError("Chapter must be positive.")
        novel = request.novel.strip()
        identities = self._registry.run_identities(novel)
        indexed, _ = _run_index(
            self._workspace, self._registry.all_run_identities()
        )
        runs = tuple(
            run
            for run in indexed
            if run.novel in identities and run.chapter == request.chapter
        )
        sources = self._registry.source_candidates(novel).get(
            request.chapter, ()
        )
        selected_run = select_candidate(runs, request.run_choice, "run")
        run_choices = tuple(
            RunChoice(
                choice,
                run.status.value,
                run.timestamp,
                run.model,
                run.volume,
            )
            for choice, run in enumerate(runs, start=1)
        )
        return ResolvedChapter(
            novel,
            request.chapter,
            _chapter_state(sources, runs),
            selected_run.run_id if selected_run is not None else None,
            run_choices,
        )
