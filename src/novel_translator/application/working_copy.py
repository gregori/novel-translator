"""Mutable working copies for in-progress editorial review."""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from novel_translator.application.review import create_revision_from_artifact
from novel_translator.domain.errors import (
    IntegrityError,
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import (
    ArtifactKind,
    EditorialArtifact,
    RevisionRecord,
    WorkingCopy,
)
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text


class WorkingCopyRepository(Protocol):
    """Persistence contract for mutable editorial working copies."""

    def get_by_id(self, working_copy_id: str) -> WorkingCopy | None:
        """Return the working copy with the given identifier."""
        ...

    def get_by_run(self, run_id: str) -> WorkingCopy | None:
        """Return the single active working copy for a run."""
        ...

    def insert(self, working_copy: WorkingCopy) -> None:
        """Persist a new working copy; one active copy per run."""
        ...

    def update_content(
        self, working_copy_id: str, expected_version: int, content: str
    ) -> WorkingCopy:
        """Atomically save content for one expected version."""
        ...

    def delete(self, working_copy_id: str) -> None:
        """Remove only the working copy; all artifacts stay untouched."""
        ...

    def active_run_ids(self) -> frozenset[str]:
        """Return the run identifiers that currently hold a copy."""
        ...


@dataclass(frozen=True, slots=True)
class GetWorkingCopyInput:
    """Select one run's active working copy."""

    run_id: str


@dataclass(frozen=True, slots=True)
class StartWorkingCopyInput:
    """Start one working copy for a run."""

    run_id: str


@dataclass(frozen=True, slots=True)
class SaveWorkingCopyInput:
    """Save content for one expected optimistic version."""

    working_copy_id: str
    expected_version: int
    content: str


@dataclass(frozen=True, slots=True)
class DiscardWorkingCopyInput:
    """Remove one working copy without touching any artifact."""

    working_copy_id: str


@dataclass(frozen=True, slots=True)
class GetWorkingCopyDiffInput:
    """Select one working copy to diff against its base."""

    working_copy_id: str


@dataclass(frozen=True, slots=True)
class CreateRevisionFromWorkingCopyInput:
    """Freeze one working copy into an immutable revision."""

    run_id: str
    working_copy_id: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class WorkingCopyDiff:
    """Rendered unified diff against the verified base artifact."""

    content: str


def _base_artifact(
    workspace: Workspace,
    run_id: str,
    kind: ArtifactKind,
    artifact_id: str | None,
) -> EditorialArtifact:
    """Read the verified artifact a working copy is based on."""
    if kind is ArtifactKind.GENERATED_DRAFT:
        if artifact_id is not None:
            raise ValidationError(
                "Generated draft working copies have no base artifact ID."
            )
        return workspace.runs.generated_draft(run_id)
    if kind is ArtifactKind.REVISION:
        if artifact_id is None:
            raise ValidationError(
                "Revision working copies require a base artifact ID."
            )
        _, artifact = workspace.revisions.revision(run_id, artifact_id)
        return artifact
    raise ValidationError(f"Unsupported base artifact kind: {kind.value}.")


def _verified_base(
    workspace: Workspace, working_copy: WorkingCopy
) -> EditorialArtifact:
    """Return the base artifact when it still matches its recorded hash."""
    artifact = _base_artifact(
        workspace,
        working_copy.run_id,
        working_copy.base_artifact_kind,
        working_copy.base_artifact_id,
    )
    if artifact.content_hash != working_copy.base_content_hash:
        raise IntegrityError(
            "Working copy base no longer matches its recorded hash."
        )
    return artifact


def _base_label(working_copy: WorkingCopy) -> str:
    """Return the diff label of the base artifact."""
    if working_copy.base_artifact_id is None:
        return working_copy.base_artifact_kind.value
    return working_copy.base_artifact_id


def _existing(
    working_copies: WorkingCopyRepository, working_copy_id: str
) -> WorkingCopy:
    """Return one existing working copy or fail with a typed error."""
    working_copy = working_copies.get_by_id(working_copy_id)
    if working_copy is None:
        raise IntegrityError("Working copy no longer exists for this run.")
    return working_copy


class GetWorkingCopy:
    """Read a run's active working copy without loading its base."""

    def __init__(self, working_copies: WorkingCopyRepository) -> None:
        self._working_copies = working_copies

    def execute(self, request: GetWorkingCopyInput) -> WorkingCopy | None:
        """Return the active working copy or None."""
        return self._working_copies.get_by_run(request.run_id)


class StartWorkingCopy:
    """Start one mutable working copy for a run's latest artifact."""

    def __init__(
        self, workspace: Workspace, working_copies: WorkingCopyRepository
    ) -> None:
        self._workspace = workspace
        self._working_copies = working_copies

    def execute(self, request: StartWorkingCopyInput) -> WorkingCopy:
        """Seed a new working copy from the latest verified artifact."""
        if self._working_copies.get_by_run(request.run_id) is not None:
            raise IntegrityError("A working copy already exists for this run.")
        records = self._workspace.revisions.revision_records(request.run_id)
        if records:
            kind = ArtifactKind.REVISION
            base_artifact_id: str | None = records[-1].revision_id
        else:
            kind = ArtifactKind.GENERATED_DRAFT
            base_artifact_id = None
        base = _base_artifact(
            self._workspace, request.run_id, kind, base_artifact_id
        )
        now = datetime.now(UTC).isoformat()
        working_copy = WorkingCopy(
            id=uuid.uuid4().hex,
            run_id=request.run_id,
            base_artifact_kind=kind,
            base_artifact_id=base_artifact_id,
            base_content_hash=base.content_hash,
            content=base.content,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._working_copies.insert(working_copy)
        return working_copy


class SaveWorkingCopy:
    """Save working copy content under optimistic version control."""

    def __init__(self, working_copies: WorkingCopyRepository) -> None:
        self._working_copies = working_copies

    def execute(self, request: SaveWorkingCopyInput) -> WorkingCopy:
        """Persist the content when the expected version is current."""
        if request.expected_version < 1:
            raise ValidationError(
                "Working copy version must be a positive integer."
            )
        normalized = request.content.replace("\r\n", "\n").replace("\r", "\n")
        return self._working_copies.update_content(
            request.working_copy_id, request.expected_version, normalized
        )


class DiscardWorkingCopy:
    """Remove only the run's active working copy."""

    def __init__(self, working_copies: WorkingCopyRepository) -> None:
        self._working_copies = working_copies

    def execute(self, request: DiscardWorkingCopyInput) -> None:
        """Delete the working copy and keep every artifact intact."""
        self._working_copies.delete(request.working_copy_id)


class GetWorkingCopyDiff:
    """Diff the working copy against its verified base artifact."""

    def __init__(
        self, workspace: Workspace, working_copies: WorkingCopyRepository
    ) -> None:
        self._workspace = workspace
        self._working_copies = working_copies

    def execute(self, request: GetWorkingCopyDiffInput) -> WorkingCopyDiff:
        """Return the derived unified diff."""
        working_copy = _existing(self._working_copies, request.working_copy_id)
        base = _verified_base(self._workspace, working_copy)
        diff = "".join(
            difflib.unified_diff(
                base.content.splitlines(keepends=True),
                working_copy.content.splitlines(keepends=True),
                fromfile=_base_label(working_copy),
                tofile="working_copy",
            )
        )
        return WorkingCopyDiff(diff)


class CreateRevisionFromWorkingCopy:
    """Freeze one working copy into an immutable revision."""

    def __init__(
        self, workspace: Workspace, working_copies: WorkingCopyRepository
    ) -> None:
        self._workspace = workspace
        self._working_copies = working_copies

    def execute(
        self, request: CreateRevisionFromWorkingCopyInput
    ) -> RevisionRecord:
        """Create the revision and then discard the working copy.

        The frozen revision deterministically reuses the working copy
        identifier, so a retry after a failure between the filesystem
        and SQLite writes returns the same revision instead of
        duplicating it.
        """
        working_copy = self._working_copies.get_by_id(request.working_copy_id)
        if working_copy is None:
            try:
                record, _ = self._workspace.revisions.revision(
                    request.run_id, request.working_copy_id
                )
            except NovelTranslatorError as error:
                raise IntegrityError(
                    "Working copy no longer exists for this run."
                ) from error
            return record
        if working_copy.run_id != request.run_id:
            raise ValidationError(
                "Working copy does not belong to the requested run."
            )
        records = self._workspace.revisions.revision_records(
            working_copy.run_id
        )
        frozen = next(
            (
                record
                for record in records
                if record.revision_id == working_copy.id
            ),
            None,
        )
        if frozen is not None:
            if frozen.content_hash != sha256_text(working_copy.content):
                raise IntegrityError(
                    "The working copy changed after its revision was frozen."
                )
            self._working_copies.delete(working_copy.id)
            return frozen
        base = _verified_base(self._workspace, working_copy)
        self._reject_superseded_base(working_copy, records)
        record = create_revision_from_artifact(
            self._workspace,
            working_copy.run_id,
            working_copy.content,
            working_copy.base_artifact_kind,
            working_copy.base_artifact_id,
            base.content_hash,
            request.note,
            working_copy.id,
        )
        self._working_copies.delete(working_copy.id)
        return record

    def _reject_superseded_base(
        self, working_copy: WorkingCopy, records: list[RevisionRecord]
    ) -> None:
        """Refuse to freeze on a base that newer artifacts replaced."""
        if working_copy.base_artifact_kind is ArtifactKind.GENERATED_DRAFT:
            superseded = bool(records)
        else:
            superseded = (
                not records
                or records[-1].revision_id != working_copy.base_artifact_id
            )
        if superseded:
            raise IntegrityError(
                "Working copy base is no longer the latest artifact; "
                "discard it and start a new working copy."
            )
