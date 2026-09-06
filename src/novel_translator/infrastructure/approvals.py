"""Filesystem repository for append-only editorial approvals."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from novel_translator.domain.errors import IntegrityError
from novel_translator.domain.models import (
    ApprovalEvent,
    ArtifactKind,
    EditorialApproval,
    EditorialArtifact,
)
from novel_translator.infrastructure.filesystem import WorkspaceStorage


class ApprovalRepository:
    """Persist and query approval decisions for immutable artifacts."""

    def __init__(self, storage: WorkspaceStorage) -> None:
        self._storage = storage

    def append_approval(self, event: ApprovalEvent) -> None:
        """Append an approval event without modifying prior events."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)
                + "\n"
            )

    def append_editorial_approval(self, event: EditorialApproval) -> None:
        """Append a schema-v2 decision for an exact editorial artifact."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)
                + "\n"
            )

    def approval_events(self, run_id: str) -> list[dict[str, object]]:
        """Read append-only approval records for a run, without rewriting."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        if not path.exists():
            return []
        events: list[dict[str, object]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                loaded: object = json.loads(line)
                if isinstance(loaded, dict):
                    raw = cast(dict[str, object], loaded)
                    if raw.get("run_id") == run_id:
                        events.append(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise IntegrityError("Approval events are invalid.") from error
        return events

    def is_approved(self, run_id: str, draft_hash: str) -> bool:
        """Return the latest matching approval decision for a run and hash."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        latest: dict[str, Any] | None = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if (
                    event["run_id"] == run_id
                    and event["draft_hash"] == draft_hash
                ):
                    latest = event
        return bool(latest and latest["approved"])

    def is_artifact_approved(
        self, artifact: EditorialArtifact, run_id: str
    ) -> bool:
        """Return the latest approval for an exact artifact and hash."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        latest: dict[str, object] | None = None
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = cast(dict[str, object], json.loads(line))
            if raw.get("run_id") != run_id:
                continue
            if raw.get("schema_version") == 2:
                if (
                    raw.get("artifact_kind") == artifact.kind
                    and raw.get("artifact_id") == artifact.artifact_id
                    and raw.get("content_hash") == artifact.content_hash
                ):
                    latest = raw
            elif (
                artifact.kind is ArtifactKind.GENERATED_DRAFT
                and raw.get("draft_hash") == artifact.content_hash
            ):
                latest = raw
        return bool(latest and latest.get("approved"))
