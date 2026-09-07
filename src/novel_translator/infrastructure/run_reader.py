"""Read-only filesystem queries over persisted translation runs."""

import json
from pathlib import Path
from typing import cast

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import (
    RUN_ID_PATTERN,
    RunCatalog,
    RunEntryError,
    RunEntryIssue,
)
from novel_translator.domain.translation import extract_draft_title
from novel_translator.infrastructure.filesystem import WorkspaceStorage


def _safe_entry_name(name: str) -> str:
    """Bound a directory name to printable characters for issue reports."""
    printable = "".join(
        character for character in name if character.isprintable()
    )
    return printable[:80] or "<unprintable>"


class RunReader:
    """Inspect persisted run metadata and immutable source content."""

    def __init__(self, storage: WorkspaceStorage) -> None:
        self._storage = storage

    def draft(self, run_id: str) -> str:
        """Read the current immutable draft."""
        return self._storage.run_path(run_id, "draft.md").read_text(
            encoding="utf-8"
        )

    def draft_title(self, run_id: str) -> str | None:
        """Read the stored title or infer one for a legacy raw draft."""
        path = self._storage.run_path(run_id, "run.json")
        payload = cast(
            dict[str, object], json.loads(path.read_text(encoding="utf-8"))
        )
        title = payload.get("draft_title")
        if isinstance(title, str) and title.strip():
            return title
        identity = cast(dict[str, object], payload["identity"])
        chapter = identity.get("chapter")
        if type(chapter) is not int:
            raise IntegrityError("Run chapter must be an integer.")
        return extract_draft_title(self.draft(run_id), chapter)

    def volume(self, run_id: str) -> int | None:
        """Read the optional positive volume persisted with a run."""
        path = self._storage.run_path(run_id, "run.json")
        payload = cast(
            dict[str, object], json.loads(path.read_text(encoding="utf-8"))
        )
        value = payload.get("volume")
        if value is None:
            return None
        if type(value) is not int or value < 1:
            raise IntegrityError(
                "Run volume must be a positive integer when present."
            )
        return value

    def chapter(self, run_id: str) -> int:
        """Read the run chapter for title derivation, not the draft."""
        try:
            payload = cast(
                dict[str, object],
                json.loads(
                    self._storage.run_path(run_id, "run.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            identity = cast(dict[str, object], payload["identity"])
            chapter = identity.get("chapter")
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            raise IntegrityError("Run chapter must be an integer.") from error
        if type(chapter) is not int:
            raise IntegrityError("Run chapter must be an integer.")
        return chapter

    def run_catalog(self) -> RunCatalog:
        """List readable runs while typing every skipped directory entry."""
        root = self._storage.safe(Path("runs"))
        if not root.exists():
            return RunCatalog((), ())
        run_ids: list[str] = []
        issues: list[RunEntryIssue] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            name = entry.name
            if (
                entry.is_symlink()
                or not entry.is_dir()
                or RUN_ID_PATTERN.fullmatch(name) is None
            ):
                issues.append(
                    RunEntryIssue(
                        _safe_entry_name(name), RunEntryError.FOREIGN
                    )
                )
                continue
            if not self._storage.run_path(name, "run.json").exists():
                issues.append(RunEntryIssue(name, RunEntryError.INCOMPLETE))
                continue
            run_ids.append(name)
        return RunCatalog(tuple(run_ids), tuple(issues))

    def source(self, run_id: str) -> str:
        """Read the immutable source text for a run."""
        try:
            return self._storage.run_path(run_id, "source.txt").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise ValidationError("Run source was not found.") from error
        except (OSError, UnicodeError) as error:
            raise ValidationError("Run source could not be read.") from error

    def inspect_run(
        self, run_id: str, include_draft: bool = False
    ) -> dict[str, object]:
        """Read validated run metadata and optionally its draft."""
        try:
            serialized = self._storage.run_path(run_id, "run.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise ValidationError("Run metadata was not found.") from error
        except (OSError, UnicodeError) as error:
            raise ValidationError("Run metadata could not be read.") from error
        try:
            loaded: object = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise IntegrityError(
                "Run metadata contains invalid JSON."
            ) from error
        if not isinstance(loaded, dict):
            raise IntegrityError("Run metadata must be a JSON object.")
        data = cast(dict[str, object], loaded)
        if data.get("run_id") != run_id:
            raise IntegrityError(
                "Run metadata does not match the requested run ID."
            )
        if include_draft:
            try:
                data["draft"] = self._storage.run_path(
                    run_id, "draft.md"
                ).read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise ValidationError("Run draft was not found.") from error
            except (OSError, UnicodeError) as error:
                raise ValidationError(
                    "Run draft could not be read."
                ) from error
        return data
