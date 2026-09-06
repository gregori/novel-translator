"""Typed artifact approval use cases."""

from dataclasses import dataclass
from datetime import UTC, datetime

from novel_translator.domain.models import EditorialApproval, EditorialArtifact
from novel_translator.infrastructure.workspace import Workspace


def resolve_artifact(
    workspace: Workspace, run_id: str, revision_id: str | None = None
) -> EditorialArtifact:
    """Resolve and verify an explicitly selected editorial artifact."""
    if revision_id is None:
        return workspace.runs.generated_draft(run_id)
    _, artifact = workspace.revisions.revision(run_id, revision_id)
    return artifact


def _record_approval(
    workspace: Workspace,
    run_id: str,
    revision_id: str | None,
    approved: bool,
) -> EditorialApproval:
    """Append a decision for the selected immutable artifact."""
    artifact = resolve_artifact(workspace, run_id, revision_id)
    event = EditorialApproval(
        schema_version=2,
        run_id=run_id,
        artifact_kind=artifact.kind,
        artifact_id=artifact.artifact_id,
        content_hash=artifact.content_hash,
        approved=approved,
        timestamp=datetime.now(UTC).isoformat(),
    )
    workspace.approvals.append_editorial_approval(event)
    return event


@dataclass(frozen=True, slots=True)
class ArtifactApprovalInput:
    """Select one exact immutable artifact."""

    run_id: str
    revision_id: str | None = None


class ApproveArtifact:
    """Append an approval event for a verified artifact."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: ArtifactApprovalInput) -> EditorialApproval:
        """Approve the selected artifact hash."""
        return _record_approval(
            self._workspace, request.run_id, request.revision_id, True
        )


class RevokeApproval:
    """Append a revocation event for a verified artifact."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: ArtifactApprovalInput) -> EditorialApproval:
        """Revoke approval for the selected artifact hash."""
        return _record_approval(
            self._workspace, request.run_id, request.revision_id, False
        )
