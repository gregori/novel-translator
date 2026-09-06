"""Filesystem repository for append-only editorial approvals."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from novel_translator.domain.errors import IntegrityError
from novel_translator.domain.models import (
    ApprovalEvent,
    ArtifactKey,
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

    def latest_approvals(self, run_id: str) -> dict[ArtifactKey, bool]:
        """Return the latest decision per artifact for one run."""
        return self.latest_approvals_by_run().get(run_id, {})

    def latest_approvals_by_run(
        self,
    ) -> dict[str, dict[ArtifactKey, bool]]:
        """Group the latest decision per run and artifact in one pass."""
        path = self._storage.safe(Path("editorial") / "approvals.jsonl")
        if not path.exists():
            return {}
        latest: dict[str, dict[ArtifactKey, bool]] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                loaded: object = json.loads(line)
                if not isinstance(loaded, dict):
                    raise IntegrityError("Approval events are invalid.")
                raw = cast(dict[str, object], loaded)
                run_id = raw.get("run_id")
                if not isinstance(run_id, str):
                    continue
                if raw.get("schema_version") == 2:
                    key = self._v2_key(
                        raw.get("artifact_kind"),
                        raw.get("artifact_id"),
                        raw.get("content_hash"),
                    )
                    if key is not None:
                        latest.setdefault(run_id, {})[key] = bool(
                            raw.get("approved")
                        )
                else:
                    draft_hash = raw.get("draft_hash")
                    if isinstance(draft_hash, str):
                        decisions = latest.setdefault(run_id, {})
                        decisions[
                            (ArtifactKind.GENERATED_DRAFT, None, draft_hash)
                        ] = bool(raw.get("approved"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise IntegrityError("Approval events are invalid.") from error
        return latest

    @staticmethod
    def _v2_key(
        kind: object, artifact_id: object, content_hash: object
    ) -> ArtifactKey | None:
        """Return one schema-v2 approval key or None when unusable."""
        if not isinstance(kind, str) or not isinstance(content_hash, str):
            return None
        if artifact_id is not None and not isinstance(artifact_id, str):
            return None
        try:
            return (ArtifactKind(kind), artifact_id, content_hash)
        except ValueError:
            return None
