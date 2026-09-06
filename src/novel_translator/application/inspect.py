"""Typed read use cases for novels, chapters, and runs."""

from dataclasses import asdict, dataclass
from typing import cast

from novel_translator.domain.errors import ValidationError
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
