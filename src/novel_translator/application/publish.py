"""Typed publication use case: approved artifacts as site pull requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from novel_translator.application.approve import resolve_artifact
from novel_translator.application.export import (
    PreviewExport,
    PreviewExportInput,
)
from novel_translator.domain.errors import ApprovalRequired
from novel_translator.domain.models import ExportEvent
from novel_translator.infrastructure.catalog import NovelRegistry
from novel_translator.infrastructure.workspace import Workspace


class SitePublisher(Protocol):
    """Persistence port for publication branches and pull requests."""

    def publish(
        self,
        *,
        repository: str,
        path: str,
        content: str,
        branch: str,
        title: str,
        body: str,
    ) -> PublishOutcome:
        """Create or reuse a branch and pull request for rendered content."""
        ...

    def read(self, *, repository: str, path: str) -> str | None:
        """Return the base branch file content, if it exists."""
        ...


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    """Result of one publisher call without workspace side effects."""

    git_commit: str
    pull_request_url: str | None
    branch: str
    created: bool


@dataclass(frozen=True, slots=True)
class PublishExportInput:
    """Typed publication selection for one approved artifact."""

    run_id: str
    novel: str
    chapter: int
    revision_id: str | None = None
    title: str | None = None
    publish_date: str | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Branch, commit, and pull request of one publication."""

    branch: str
    git_commit: str
    pull_request_url: str | None
    path: str
    content_hash: str
    created: bool


def _branch_for(novel: str, chapter: int, content_hash: str) -> str:
    """Derive one deterministic branch per exact artifact content."""
    return f"novel-translator/{novel}-ch{chapter}-{content_hash[:8]}"


_PUBLISH_DATE_PATTERN = re.compile(
    r"^publishDate: (\d{4}-\d{2}-\d{2})$", re.MULTILINE
)


def _pinned_publish_date(
    explicit: str | None, existing: str | None
) -> str | None:
    """Reuse the live file date so retries render identical bytes."""
    if explicit is not None:
        return explicit
    if existing is None:
        return None
    match = _PUBLISH_DATE_PATTERN.search(existing)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


class PublishExport:
    """Open a novels-site pull request for one explicitly approved artifact."""

    def __init__(
        self,
        workspace: Workspace,
        registry: NovelRegistry,
        publisher: SitePublisher,
    ) -> None:
        self._workspace = workspace
        self._registry = registry
        self._publisher = publisher

    def execute(self, request: PublishExportInput) -> PublishResult:
        """Render the approved artifact and publish it as a pull request."""
        artifact = resolve_artifact(
            self._workspace, request.run_id, request.revision_id
        )
        if not self._workspace.approvals.is_artifact_approved(
            artifact, request.run_id
        ):
            raise ApprovalRequired(
                "The selected artifact hash has not been approved."
            )
        export_config = self._registry.novel(request.novel).export
        repo_path = (
            f"{export_config.directory.as_posix()}/"
            f"{export_config.filename_template.format(chapter=request.chapter)}"
        )
        existing = self._publisher.read(
            repository=export_config.repository, path=repo_path
        )
        preview = PreviewExport(self._workspace).execute(
            PreviewExportInput(
                run_id=request.run_id,
                revision_id=request.revision_id,
                title=request.title,
                publish_date=_pinned_publish_date(
                    request.publish_date, existing
                ),
            )
        )
        branch = _branch_for(
            request.novel, request.chapter, artifact.content_hash
        )
        outcome = self._publisher.publish(
            repository=export_config.repository,
            path=repo_path,
            content=preview.content,
            branch=branch,
            title=f"Publish {request.novel} chapter {request.chapter}",
            body=(
                f"Approved {artifact.kind.value} {preview.content_hash} "
                f"for run {request.run_id}."
            ),
        )
        pull_request_url = outcome.pull_request_url or self._reuse_pr_url(
            request.run_id,
            artifact.content_hash,
            f"{export_config.repository}/{repo_path}",
        )
        self._workspace.exports.append(
            ExportEvent(
                schema_version=1,
                run_id=request.run_id,
                artifact_kind=artifact.kind,
                artifact_id=artifact.artifact_id,
                content_hash=artifact.content_hash,
                destination=f"{export_config.repository}/{repo_path}",
                exported_at=datetime.now(UTC).isoformat(),
                git_commit=outcome.git_commit,
                pull_request_url=pull_request_url,
            )
        )
        return PublishResult(
            branch=outcome.branch,
            git_commit=outcome.git_commit,
            pull_request_url=pull_request_url,
            path=repo_path,
            content_hash=artifact.content_hash,
            created=outcome.created,
        )

    def _reuse_pr_url(
        self, run_id: str, content_hash: str, destination: str
    ) -> str | None:
        """Reuse a prior pull request link on idempotent retry."""
        for event in reversed(self._workspace.exports.events_for_run(run_id)):
            if (
                event.content_hash == content_hash
                and event.destination == destination
                and event.pull_request_url is not None
            ):
                return event.pull_request_url
        return None
