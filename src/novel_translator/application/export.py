"""Typed artifact export use cases."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from novel_translator.application.approve import resolve_artifact
from novel_translator.domain.errors import ApprovalRequired, ValidationError
from novel_translator.domain.models import EditorialArtifact, ExportEvent
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


def _require_approved(
    workspace: Workspace, run_id: str, revision_id: str | None
) -> EditorialArtifact:
    """Resolve one artifact and require its current approval."""
    artifact = resolve_artifact(workspace, run_id, revision_id)
    if not workspace.approvals.is_artifact_approved(artifact, run_id):
        raise ApprovalRequired(
            "The selected artifact hash has not been approved."
        )
    return artifact


def _render(
    workspace: Workspace,
    run_id: str,
    artifact: EditorialArtifact,
    title: str | None,
    publish_date: str | None,
) -> str:
    """Render one approved artifact as novels-site Markdown."""
    resolved = title or extract_draft_title(
        artifact.content, workspace.reader.chapter(run_id)
    )
    if resolved is None:
        raise ValidationError(
            "No draft title found; provide a title for this export."
        )
    front_matter = [
        "---",
        f'chapterTitle: "{resolved}"',
        f"publishDate: {_publish_date_value(publish_date)}",
    ]
    volume = workspace.reader.volume(run_id)
    if volume is not None:
        front_matter.append(f"volume: {volume}")
    return "\n".join([*front_matter, "---", "", artifact.content, ""])


def _publish_date_value(value: str | None) -> str:
    """Validate or provide the export publication date."""
    if value is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValidationError(
            "publish_date must use the YYYY-MM-DD format."
        ) from error


class ExportArtifact:
    """Render and persist one explicitly approved artifact."""

    def __init__(self, workspace: Workspace, writer: ArtifactWriter) -> None:
        self._workspace = workspace
        self._writer = writer

    def execute(self, request: ExportArtifactInput) -> ExportResult:
        """Render and persist the selected approved artifact."""
        artifact = _require_approved(
            self._workspace, request.run_id, request.revision_id
        )
        rendered = _render(
            self._workspace,
            request.run_id,
            artifact,
            request.title,
            request.publish_date,
        )
        path = self._writer.write(
            request.destination, rendered, request.overwrite
        )
        self._workspace.exports.append(
            ExportEvent(
                schema_version=1,
                run_id=request.run_id,
                artifact_kind=artifact.kind,
                artifact_id=artifact.artifact_id,
                content_hash=artifact.content_hash,
                destination=str(path.resolve()),
                exported_at=datetime.now(UTC).isoformat(),
            )
        )
        return ExportResult(path)


@dataclass(frozen=True, slots=True)
class PreviewExportInput:
    """Select one approved artifact for download, view, or copy."""

    run_id: str
    revision_id: str | None = None
    title: str | None = None
    publish_date: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewExportResult:
    """Rendered Markdown plus the exact provenance it points to."""

    content: str
    content_hash: str
    artifact_id: str | None


class PreviewExport:
    """Render one approved artifact without touching the site checkout."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: PreviewExportInput) -> PreviewExportResult:
        """Render the selected approved artifact for transfer."""
        artifact = _require_approved(
            self._workspace, request.run_id, request.revision_id
        )
        rendered = _render(
            self._workspace,
            request.run_id,
            artifact,
            request.title,
            request.publish_date,
        )
        return PreviewExportResult(
            content=rendered,
            content_hash=artifact.content_hash,
            artifact_id=artifact.artifact_id,
        )


@dataclass(frozen=True, slots=True)
class ExportHistoryInput:
    """Select one run whose export provenance should be listed."""

    run_id: str


class ListExportHistory:
    """List export provenance events for one run in file order."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: ExportHistoryInput) -> tuple[ExportEvent, ...]:
        """Return every recorded export for the selected run."""
        return self._workspace.exports.events_for_run(request.run_id)
