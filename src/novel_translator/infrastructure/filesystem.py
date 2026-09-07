"""Safe atomic filesystem primitives for workspace repositories."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import RUN_ID_PATTERN


class WorkspaceStorage:
    """Resolve safe workspace paths and perform atomic writes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def safe(self, relative: Path) -> Path:
        """Resolve a path that cannot escape the workspace."""
        unresolved = self.root / relative
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValidationError(
                    "Path escapes the workspace or is a symlink."
                )
        target = unresolved.resolve()
        if os.path.commonpath([self.root, target]) != str(self.root):
            raise ValidationError(
                "Path escapes the workspace or is a symlink."
            )
        return target

    def run_path(self, run_id: str, *parts: str) -> Path:
        """Return a safe path under a validated application run ID."""
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValidationError(
                "Run ID must be 32 lowercase hexadecimal characters."
            )
        return self.safe(Path("runs") / run_id / Path(*parts))

    def revision_path(
        self, run_id: str, revision_id: str, *parts: str
    ) -> Path:
        """Return a safe path below a validated revision identifier."""
        if RUN_ID_PATTERN.fullmatch(revision_id) is None:
            raise ValidationError(
                "Revision ID must be 32 lowercase hexadecimal characters."
            )
        return self.run_path(run_id, "revisions", revision_id, *parts)

    def atomic_write(self, path: Path, content: str) -> None:
        """Create one immutable artifact atomically."""
        if path.exists():
            raise IntegrityError(
                f"Immutable artifact already exists: {path.name}"
            )
        self.atomic_replace(path, content)

    def atomic_replace(self, path: Path, content: str) -> None:
        """Durably replace one file without exposing partial content."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                with suppress(OSError):
                    temporary.unlink()
