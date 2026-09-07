"""Presentation helpers for the web adapter.

This module holds no editorial rules: every decision here is about
turning typed use-case results into template-friendly view models.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

from markdown_it import MarkdownIt

from novel_translator.application.catalog import ChapterSummary
from novel_translator.application.inspect import ReviewRevision
from novel_translator.domain.models import ChapterState

_MD = MarkdownIt("commonmark", {"html": False})
_MD.enable(["smartquotes", "replacements"])

STATE_LABELS: dict[ChapterState, str] = {
    ChapterState.NO_SOURCE: "No source",
    ChapterState.READY: "Ready to translate",
    ChapterState.TRANSLATING: "Translating",
    ChapterState.DRAFT_AVAILABLE: "Draft available",
    ChapterState.IN_REVIEW: "In review",
    ChapterState.APPROVED: "Approved",
    ChapterState.EXPORTED: "Exported",
    ChapterState.FAILED: "Failed",
}


def state_label(value: ChapterState | str) -> str:
    """Return the human label for one aggregate chapter state."""
    state = (
        value if isinstance(value, ChapterState) else ChapterState(str(value))
    )
    return STATE_LABELS.get(state, str(value).replace("_", " ").title())


def state_class(value: ChapterState | str) -> str:
    """Return the CSS modifier for one aggregate chapter state."""
    state = (
        value if isinstance(value, ChapterState) else ChapterState(str(value))
    )
    return f"state-{state.value}"


def format_timestamp(value: str | None) -> str:
    """Format one ISO timestamp as an explicit UTC reading stamp."""
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def render_markdown(content: str) -> str:
    """Render chapter Markdown to safe HTML.

    The commonmark preset keeps raw HTML disabled, so authored chapter
    text can never inject markup into the preview.
    """
    return _MD.render(content)


def diff_html(unified: str) -> str:
    """Escape a unified diff into classed, line-based HTML."""
    lines: list[str] = []
    for line in unified.splitlines():
        css = "ctx"
        if line.startswith("@@"):
            css = "hunk"
        elif line.startswith("+"):
            css = "add"
        elif line.startswith("-"):
            css = "del"
        lines.append(f'<div class="line {css}">{escape(line)}</div>')
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ChapterFilter:
    """Server-side chapter search/filter criteria from the querystring."""

    query: str
    state: ChapterState | None

    def matches(self, chapter: ChapterSummary) -> bool:
        """Match by chapter digits and exact state when informed."""
        if self.state is not None and chapter.state is not self.state:
            return False
        digits = "".join(
            character for character in self.query if character.isdigit()
        )
        if not digits:
            return not self.query.strip()
        return digits in str(chapter.chapter)


def filter_chapters(
    chapters: Sequence[ChapterSummary], chapter_filter: ChapterFilter
) -> tuple[ChapterSummary, ...]:
    """Apply the friendly search and state filter over one catalog."""
    return tuple(
        chapter for chapter in chapters if chapter_filter.matches(chapter)
    )


def state_counts(
    chapters: Sequence[ChapterSummary],
) -> list[tuple[ChapterState, int]]:
    """Count chapters per state for the filter chips, in enum order."""
    return [
        (state, sum(1 for chapter in chapters if chapter.state is state))
        for state in ChapterState
    ]


@dataclass(frozen=True, slots=True)
class RecentChapter:
    """One chapter touched recently, for the dashboard timeline."""

    novel: str
    chapter: int
    state: ChapterState
    timestamp: str


def _latest_stamp(chapter: ChapterSummary) -> str:
    """Return the newest run timestamp of one chapter summary."""
    stamps = [run.timestamp for run in chapter.runs]
    return max(stamps) if stamps else ""


def recent_chapters(
    chapters: Sequence[ChapterSummary],
    limit: int = 8,
) -> tuple[RecentChapter, ...]:
    """Rank chapters by their newest run timestamp across all novels."""
    entries = [
        RecentChapter(
            chapter.novel,
            chapter.chapter,
            chapter.state,
            _latest_stamp(chapter),
        )
        for chapter in chapters
        if chapter.runs
    ]
    ranked = sorted(entries, key=lambda item: item.timestamp, reverse=True)
    return tuple(ranked[:limit])


@dataclass(frozen=True, slots=True)
class StateGroup:
    """Dashboard grouping label plus the chapters it contains."""

    title: str
    states: tuple[ChapterState, ...]
    items: tuple[RecentChapter, ...]

    def matches(self, chapter: ChapterSummary) -> bool:
        """Report whether a chapter belongs to this dashboard group."""
        return chapter.state in self.states


DASHBOARD_GROUPS: tuple[StateGroup, ...] = (
    StateGroup("Translating", (ChapterState.TRANSLATING,), ()),
    StateGroup(
        "Awaiting review",
        (ChapterState.DRAFT_AVAILABLE, ChapterState.IN_REVIEW),
        (),
    ),
    StateGroup("Approved", (ChapterState.APPROVED,), ()),
    StateGroup("Exported", (ChapterState.EXPORTED,), ()),
    StateGroup("Failed", (ChapterState.FAILED,), ()),
)


def dashboard_groups(
    chapters: Sequence[ChapterSummary],
    limit_per_group: int = 8,
) -> tuple[StateGroup, ...]:
    """Group dashboard chapters by their actionable aggregate state."""
    groups: list[StateGroup] = []
    for group in DASHBOARD_GROUPS:
        items = [
            RecentChapter(
                chapter.novel,
                chapter.chapter,
                chapter.state,
                _latest_stamp(chapter),
            )
            for chapter in chapters
            if group.matches(chapter)
        ]
        items.sort(key=lambda item: item.timestamp, reverse=True)
        groups.append(
            StateGroup(
                group.title,
                group.states,
                tuple(items[:limit_per_group]),
            )
        )
    return tuple(groups)


@dataclass(frozen=True, slots=True)
class RevisionView:
    """One revision history row, hiding its opaque identifier."""

    ordinal: int
    revision_id: str
    content_hash: str
    created_at: str
    note: str | None
    approved: bool


def revision_views(
    revisions: Sequence[ReviewRevision],
) -> tuple[RevisionView, ...]:
    """Turn review revisions into display-safe history rows."""
    return tuple(
        RevisionView(
            revision.ordinal,
            revision.record.revision_id,
            revision.record.content_hash,
            format_timestamp(revision.record.created_at),
            revision.record.note,
            revision.approved,
        )
        for revision in revisions
    )
