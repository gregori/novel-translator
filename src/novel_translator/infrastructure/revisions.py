"""Filesystem repository for immutable editorial revisions."""

import json
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import cast

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import (
    ArtifactKind,
    EditorialArtifact,
    RevisionKind,
    RevisionParent,
    RevisionParentKind,
    RevisionRecord,
)
from novel_translator.infrastructure.filesystem import WorkspaceStorage
from novel_translator.shared.utils import json_dumps, sha256_text


class RevisionRepository:
    """Persist and verify immutable editorial revisions."""

    def __init__(self, storage: WorkspaceStorage) -> None:
        self._storage = storage

    def create_revision(self, record: RevisionRecord, content: str) -> None:
        """Atomically create immutable revision content and metadata."""
        if sha256_text(content) != record.content_hash:
            raise IntegrityError(
                "Revision content hash does not match its metadata."
            )
        target = self._storage.revision_path(record.run_id, record.revision_id)
        if target.exists():
            raise IntegrityError("Revision identifier collision.")
        revisions_root = self._storage.run_path(record.run_id, "revisions")
        revisions_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=revisions_root))
        try:
            self._storage.atomic_write(temporary / "content.md", content)
            self._storage.atomic_write(
                temporary / "revision.json", json_dumps(asdict(record))
            )
            temporary.replace(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def revision(
        self, run_id: str, revision_id: str
    ) -> tuple[RevisionRecord, EditorialArtifact]:
        """Read a revision and verify metadata and immutable content hash."""
        record = self._record(run_id, revision_id)
        try:
            content = self._storage.revision_path(
                run_id, revision_id, "content.md"
            ).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValidationError("Revision was not found.") from error
        except (OSError, UnicodeError) as error:
            raise ValidationError(
                "Revision content could not be read."
            ) from error
        artifact = EditorialArtifact(
            ArtifactKind.REVISION, revision_id, content, sha256_text(content)
        )
        if artifact.content_hash != record.content_hash:
            raise IntegrityError("Revision content integrity check failed.")
        return record, artifact

    def revision_records(self, run_id: str) -> list[RevisionRecord]:
        """List validated revision metadata without reading content."""
        root = self._storage.run_path(run_id, "revisions")
        if not root.exists():
            return []
        if root.is_symlink():
            raise ValidationError(
                "Path escapes the workspace or is a symlink."
            )
        records: list[RevisionRecord] = []
        for entry in root.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                raise IntegrityError("Revision directory is invalid.")
            records.append(self._record(run_id, entry.name))
        return sorted(records, key=lambda item: item.created_at)

    def _record(self, run_id: str, revision_id: str) -> RevisionRecord:
        """Parse and validate one revision's immutable metadata."""
        try:
            serialized = self._storage.revision_path(
                run_id, revision_id, "revision.json"
            ).read_text(encoding="utf-8")
            raw = cast(dict[str, object], json.loads(serialized))
            parent_raw = cast(dict[str, object], raw["parent"])
            parent = RevisionParent(
                RevisionParentKind(cast(str, parent_raw["kind"])),
                cast(str | None, parent_raw.get("revision_id")),
                cast(str | None, parent_raw.get("content_hash")),
                cast(bool, parent_raw["content_available"]),
            )
            record = RevisionRecord(
                schema_version=cast(int, raw["schema_version"]),
                revision_id=cast(str, raw["revision_id"]),
                run_id=cast(str, raw["run_id"]),
                content_hash=cast(str, raw["content_hash"]),
                parent=parent,
                author_type=cast(str, raw["author_type"]),
                revision_kind=RevisionKind(cast(str, raw["revision_kind"])),
                created_at=cast(str, raw["created_at"]),
                note=cast(str | None, raw.get("note")),
            )
        except FileNotFoundError as error:
            raise ValidationError("Revision was not found.") from error
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise IntegrityError("Revision metadata is invalid.") from error
        if record.run_id != run_id or record.revision_id != revision_id:
            raise IntegrityError("Revision metadata does not match its path.")
        return record
