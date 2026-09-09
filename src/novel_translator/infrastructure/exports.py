"""Append-only provenance repository for completed exports."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

from novel_translator.domain.errors import IntegrityError
from novel_translator.domain.models import (
    ArtifactKey,
    ArtifactKind,
    ExportEvent,
)
from novel_translator.infrastructure.filesystem import WorkspaceStorage


class ExportRepository:
    """Persist and query successful exports without rewriting history."""

    def __init__(self, storage: WorkspaceStorage) -> None:
        self._storage = storage

    def append(self, event: ExportEvent) -> None:
        """Append provenance after the destination write succeeds."""
        path = self._storage.safe(Path("editorial") / "exports.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)
                + "\n"
            )

    def exported_keys_by_run(
        self,
    ) -> dict[str, frozenset[ArtifactKey]]:
        """Group every exported artifact key per run in one pass."""
        path = self._storage.safe(Path("editorial") / "exports.jsonl")
        if not path.exists():
            return {}
        keys: dict[str, set[ArtifactKey]] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                loaded: object = json.loads(line)
                if not isinstance(loaded, dict):
                    raise IntegrityError("Export events are invalid.")
                event = cast(dict[str, object], loaded)
                run_id = event.get("run_id")
                if not isinstance(run_id, str):
                    continue
                kind = event.get("artifact_kind")
                artifact_id = event.get("artifact_id")
                content_hash = event.get("content_hash")
                if (
                    not isinstance(kind, str)
                    or not isinstance(content_hash, str)
                    or (
                        artifact_id is not None
                        and not isinstance(artifact_id, str)
                    )
                ):
                    continue
                try:
                    key: ArtifactKey = (
                        ArtifactKind(kind),
                        artifact_id,
                        content_hash,
                    )
                except ValueError:
                    continue
                keys.setdefault(run_id, set()).add(key)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise IntegrityError("Export events are invalid.") from error
        return {
            run_id: frozenset(run_keys) for run_id, run_keys in keys.items()
        }

    def events_for_run(self, run_id: str) -> tuple[ExportEvent, ...]:
        """Return every export provenance event for one run in file order."""
        path = self._storage.safe(Path("editorial") / "exports.jsonl")
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise IntegrityError("Export events are invalid.") from error
        events: list[ExportEvent] = []
        for line in lines:
            try:
                loaded: object = json.loads(line)
            except json.JSONDecodeError as error:
                raise IntegrityError("Export events are invalid.") from error
            if not isinstance(loaded, dict):
                raise IntegrityError("Export events are invalid.")
            event = cast(dict[str, object], loaded)
            if event.get("run_id") != run_id:
                continue
            parsed = self._parse_event(event)
            if parsed is not None:
                events.append(parsed)
        return tuple(events)

    @staticmethod
    def _parse_event(event: dict[str, object]) -> ExportEvent | None:
        """Parse one export event, tolerating pre-phase-6 payloads."""
        kind = event.get("artifact_kind")
        content_hash = event.get("content_hash")
        destination = event.get("destination")
        exported_at = event.get("exported_at")
        if (
            not isinstance(kind, str)
            or not isinstance(content_hash, str)
            or not isinstance(destination, str)
            or not isinstance(exported_at, str)
        ):
            return None
        try:
            artifact_kind = ArtifactKind(kind)
        except ValueError:
            return None
        artifact_id = event.get("artifact_id")
        git_commit = event.get("git_commit")
        pull_request_url = event.get("pull_request_url")
        schema_version = event.get("schema_version")
        version = schema_version if isinstance(schema_version, int) else 1
        return ExportEvent(
            schema_version=version,
            run_id=str(event.get("run_id")),
            artifact_kind=artifact_kind,
            artifact_id=artifact_id if isinstance(artifact_id, str) else None,
            content_hash=content_hash,
            destination=destination,
            exported_at=exported_at,
            git_commit=git_commit if isinstance(git_commit, str) else None,
            pull_request_url=pull_request_url
            if isinstance(pull_request_url, str)
            else None,
        )
