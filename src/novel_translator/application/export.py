"""Typed artifact export use case."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from novel_translator.application.approve import resolve_artifact
from novel_translator.domain.errors import ApprovalRequired, ValidationError
from novel_translator.domain.translation import extract_draft_title
from novel_translator.infrastructure.workspace import Workspace


class ArtifactWriter(Protocol):
    """Persistence port for a rendered export."""

    def write(self, destination: Path, content: str, overwrite: bool) -> Path:
        """Persist rendered content and return its resolved destination."""
        ...


@dataclass(frozen=True, slots=True)
class ExportArtifactInput:
    """Typed export destination and artifact selection."""

    run_id: str
    destination: Path
    revision_id: str | None = None
    title: str | None = None
    overwrite: bool = False
    publish_date: str | None = None


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Resolved destination of an exported artifact."""

    path: Path


class ExportArtifact:
    """Render and persist one explicitly approved artifact."""

    def __init__(self, workspace: Workspace, writer: ArtifactWriter) -> None:
        self._workspace = workspace
        self._writer = writer

    def execute(self, request: ExportArtifactInput) -> ExportResult:
        """Render and persist the selected approved artifact."""
        artifact = resolve_artifact(
            self._workspace, request.run_id, request.revision_id
        )
        if not self._workspace.approvals.is_artifact_approved(
            artifact, request.run_id
        ):
            raise ApprovalRequired(
                "The selected artifact hash has not been approved."
            )
        title = request.title or extract_draft_title(
            artifact.content, self._workspace.reader.chapter(request.run_id)
        )
        if title is None:
            raise ValidationError(
                "No draft title found; provide a title for this export."
            )
        publish_date = self._publish_date(request.publish_date)
        front_matter = [
            "---",
            f'chapterTitle: "{title}"',
            f"publishDate: {publish_date}",
        ]
        volume = self._workspace.reader.volume(request.run_id)
        if volume is not None:
            front_matter.append(f"volume: {volume}")
        rendered = "\n".join([*front_matter, "---", "", artifact.content, ""])
        path = self._writer.write(
            request.destination, rendered, request.overwrite
        )
        return ExportResult(path)

    @staticmethod
    def _publish_date(value: str | None) -> str:
        """Validate or provide the export publication date."""
        if value is None:
            return date.today().isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValidationError(
                "publish_date must use the YYYY-MM-DD format."
            ) from error
