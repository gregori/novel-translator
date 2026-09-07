"""Composition container wiring application use cases for the web adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novel_translator.application.approve import (
    ApproveArtifact,
    RevokeApproval,
)
from novel_translator.application.catalog import (
    ChapterCatalog,
    DashboardCatalog,
    ListChapters,
    ListChaptersInput,
    ListDashboard,
    ResolveChapter,
)
from novel_translator.application.export import ExportArtifact
from novel_translator.application.inspect import ReadChapterForReview
from novel_translator.application.review import GetDiff, ListRevisions
from novel_translator.application.working_copy import (
    CreateRevisionFromWorkingCopy,
    DiscardWorkingCopy,
    GetWorkingCopy,
    GetWorkingCopyDiff,
    SaveWorkingCopy,
    StartWorkingCopy,
)
from novel_translator.domain.errors import NovelTranslatorError
from novel_translator.infrastructure.catalog import NovelRegistry


@dataclass(frozen=True, slots=True)
class Services:
    """Use cases and configuration shared by every web route."""

    registry: NovelRegistry
    list_dashboard: ListDashboard
    list_chapters: ListChapters
    resolve_chapter: ResolveChapter
    read_chapter_for_review: ReadChapterForReview
    list_revisions: ListRevisions
    get_diff: GetDiff
    approve_artifact: ApproveArtifact
    revoke_approval: RevokeApproval
    export_artifact: ExportArtifact
    get_working_copy: GetWorkingCopy
    start_working_copy: StartWorkingCopy
    save_working_copy: SaveWorkingCopy
    discard_working_copy: DiscardWorkingCopy
    get_working_copy_diff: GetWorkingCopyDiff
    create_revision_from_working_copy: CreateRevisionFromWorkingCopy
    site_root: Path | None

    def dashboard(self) -> DashboardCatalog:
        """List novels and chapters across the catalog in one indexation."""
        return self.list_dashboard.execute()

    def chapter_catalog(self, novel: str) -> ChapterCatalog:
        """List aggregated chapters for one registered novel."""
        return self.list_chapters.execute(ListChaptersInput(novel))

    def novel_registered(self, novel: str) -> bool:
        """Report whether one novel identifier is registered."""
        return novel.strip() in self.registry.config.novels

    def novel_title(self, novel: str) -> str:
        """Return the configured display title for one novel."""
        return self.registry.novel(novel).title

    def export_destination(self, novel: str, chapter: int) -> Path:
        """Resolve the export destination inside the site checkout."""
        if self.site_root is None:
            raise NovelTranslatorError(
                "Exports are not configured: this server was started "
                "without a site checkout root."
            )
        return self.registry.export_destination(novel, chapter, self.site_root)
