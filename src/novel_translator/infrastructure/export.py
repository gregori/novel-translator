"""Filesystem adapter for exported Markdown artifacts."""

import shutil
from pathlib import Path

from novel_translator.domain.errors import CollisionRequired


class FilesystemArtifactWriter:
    """Write an export with explicit collision handling and rollback."""

    def write(self, destination: Path, content: str, overwrite: bool) -> Path:
        """Persist content without silently replacing different bytes."""
        destination = destination.resolve()
        if (
            destination.exists()
            and destination.read_text(encoding="utf-8") != content
            and not overwrite
        ):
            raise CollisionRequired(
                "Destination differs; explicit overwrite "
                "confirmation is required."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = destination.with_suffix(destination.suffix + ".bak")
        try:
            if destination.exists():
                shutil.copy2(destination, backup)
            destination.write_text(content, encoding="utf-8")
            return destination
        except OSError:
            if backup.exists():
                backup.replace(destination)
            raise
        finally:
            if backup.exists():
                backup.unlink()
