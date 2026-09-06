"""Filesystem repository for translation runs and generated drafts."""

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import (
    ArtifactKind,
    EditorialArtifact,
    PromptCall,
    RunCompletion,
    RunPhase,
    RunRecord,
    RunStatus,
    SegmentPromptManifest,
)
from novel_translator.domain.translation import (
    SourceDocument,
    TranslationBible,
    prompt_manifest_hash,
)
from novel_translator.infrastructure.filesystem import WorkspaceStorage
from novel_translator.shared.utils import json_dumps, sha256_text

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.DRAFT_COMPLETED, RunStatus.FAILED, RunStatus.INTERRUPTED}
)


class RunRepository:
    """Persist and inspect translation runs and generated drafts."""

    def __init__(self, storage: WorkspaceStorage) -> None:
        self._storage = storage

    def create_run(
        self,
        record: RunRecord,
        source: SourceDocument,
        bible: TranslationBible,
    ) -> Path:
        """Create immutable source, bible snapshot and run metadata."""
        run_dir = self._storage.run_path(record.run_id)
        if run_dir.exists():
            raise IntegrityError("Run identifier collision.")
        run_dir.mkdir(parents=True)
        self._storage.atomic_write(run_dir / "source.txt", source.content)
        self._storage.atomic_write(
            run_dir / "bible.json", bible.model_dump_json(indent=2)
        )
        self._storage.atomic_write(
            run_dir / "run.json", json_dumps(asdict(record))
        )
        return run_dir

    def save_draft(self, run_id: str, draft: str) -> str:
        """Persist a complete draft and atomically update its projection."""
        run_dir = self._storage.run_path(run_id)
        draft_path = run_dir / "draft.md"
        self._storage.atomic_write(draft_path, draft)
        draft_hash = sha256_text(draft)
        self._storage.atomic_write(run_dir / "draft.sha256", draft_hash)
        current = self._storage.safe(Path("current") / f"{run_id}.json")
        current.parent.mkdir(parents=True, exist_ok=True)
        self._storage.atomic_replace(
            current, json_dumps({"run_id": run_id, "draft_hash": draft_hash})
        )
        return draft_hash

    def generated_draft(self, run_id: str) -> EditorialArtifact:
        """Read and verify the immutable generated draft for a run."""
        try:
            content = self._storage.run_path(run_id, "draft.md").read_text(
                encoding="utf-8"
            )
            expected_hash = (
                self._storage.run_path(run_id, "draft.sha256")
                .read_text(encoding="utf-8")
                .strip()
            )
        except FileNotFoundError as error:
            raise IntegrityError(
                "Generated draft is unavailable; "
                "use a migrated revision instead."
            ) from error
        except (OSError, UnicodeError) as error:
            raise ValidationError(
                "Generated draft could not be read."
            ) from error
        actual_hash = sha256_text(content)
        if expected_hash != actual_hash:
            raise IntegrityError(
                "Generated draft integrity check failed; "
                "use a migrated revision when applicable."
            )
        current = self._storage.safe(Path("current") / f"{run_id}.json")
        if current.exists():
            try:
                projection = cast(
                    dict[str, object],
                    json.loads(current.read_text(encoding="utf-8")),
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise IntegrityError(
                    "Generated draft projection is invalid."
                ) from error
            if (
                projection.get("run_id") != run_id
                or projection.get("draft_hash") != actual_hash
            ):
                raise IntegrityError(
                    "Generated draft projection integrity check failed."
                )
        return EditorialArtifact(
            ArtifactKind.GENERATED_DRAFT, None, content, actual_hash
        )

    def recorded_draft_hash(self, run_id: str) -> str:
        """Read the persisted draft hash without loading draft content."""
        try:
            recorded = (
                self._storage.run_path(run_id, "draft.sha256")
                .read_text(encoding="utf-8")
                .strip()
            )
        except FileNotFoundError as error:
            raise IntegrityError(
                "Recorded draft hash is unavailable."
            ) from error
        except (OSError, UnicodeError) as error:
            raise IntegrityError(
                "Recorded draft hash could not be read."
            ) from error
        if _SHA256_PATTERN.fullmatch(recorded) is None:
            raise IntegrityError("Recorded draft hash is invalid.")
        return recorded

    def legacy_draft_snapshot(self, run_id: str) -> tuple[str, str]:
        """Read legacy draft bytes and its recorded hash, unverified."""
        try:
            content = self._storage.run_path(run_id, "draft.md").read_text(
                encoding="utf-8"
            )
            original_hash = (
                self._storage.run_path(run_id, "draft.sha256")
                .read_text(encoding="utf-8")
                .strip()
            )
        except FileNotFoundError as error:
            raise ValidationError("Legacy draft was not found.") from error
        except (OSError, UnicodeError) as error:
            raise ValidationError("Legacy draft could not be read.") from error
        return content, original_hash

    def transition_run(
        self,
        run_id: str,
        status: RunStatus,
        completed_at: datetime,
        updates: dict[str, object] | None = None,
    ) -> None:
        """Atomically apply one valid terminal transition to a started run."""
        if status not in TERMINAL_RUN_STATUSES:
            raise IntegrityError(f"Invalid terminal run status: {status}.")
        path = self._storage.run_path(run_id, "run.json")
        payload = cast(
            dict[str, object], json.loads(path.read_text(encoding="utf-8"))
        )
        if payload.get("status") != RunStatus.STARTED:
            raise IntegrityError(
                "Only a started run can transition to a terminal status."
            )
        payload.update(updates or {})
        payload.update(
            {"status": status, "completed_at": completed_at.isoformat()}
        )
        self._storage.atomic_replace(path, json_dumps(payload))

    def record_prompt_segment(
        self, run_id: str, segment: SegmentPromptManifest
    ) -> None:
        """Append hash provenance before a segment reaches the gateway."""
        path = self._storage.run_path(run_id, "run.json")
        payload = cast(
            dict[str, object], json.loads(path.read_text(encoding="utf-8"))
        )
        manifest = cast(list[dict[str, object]], payload["segment_manifest"])
        expected_index = len(manifest) + 1
        if segment.segment_index != expected_index:
            raise IntegrityError("Prompt segments must be recorded in order.")
        manifest.append(cast(dict[str, object], asdict(segment)))
        payload["prompt_hash"] = prompt_manifest_hash(manifest)
        self._storage.atomic_replace(path, json_dumps(payload))

    def record_prompt_call(
        self, run_id: str, segment_index: int, call: PromptCall
    ) -> None:
        """Associate a gateway attempt with its exact rendered prompt hash."""
        path = self._storage.run_path(run_id, "run.json")
        payload = cast(
            dict[str, object], json.loads(path.read_text(encoding="utf-8"))
        )
        manifest = cast(list[dict[str, object]], payload["segment_manifest"])
        if segment_index < 1 or segment_index > len(manifest):
            raise IntegrityError("Gateway call references an unknown segment.")
        segment = manifest[segment_index - 1]
        if call.rendered_prompt_hash != segment["rendered_prompt_hash"]:
            raise IntegrityError(
                "Gateway call prompt hash does not match segment."
            )
        calls = cast(list[dict[str, object]], segment["gateway_calls"])
        if call.attempt != len(calls) + 1:
            raise IntegrityError("Gateway attempts must be recorded in order.")
        calls.append(cast(dict[str, object], asdict(call)))
        self._storage.atomic_replace(path, json_dumps(payload))

    def terminate_run(
        self,
        run_id: str,
        status: RunStatus,
        error: BaseException,
        phase: RunPhase,
        segment: int | None,
        attempt: int | None,
        completed_at: datetime,
    ) -> None:
        """Record bounded failure metadata without exception messages."""
        if status not in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            raise IntegrityError(
                "A terminated run must be failed or interrupted."
            )
        failure: dict[str, object] = {
            "type": type(error).__name__[:100],
            "phase": phase,
            "timestamp": completed_at.isoformat(),
        }
        if segment is not None:
            failure["segment"] = segment
        if attempt is not None:
            failure["attempt"] = attempt
        self.transition_run(run_id, status, completed_at, {"error": failure})

    def complete_run(
        self,
        run_id: str,
        completed_at: datetime,
        completion: RunCompletion,
    ) -> None:
        """Persist application-computed metrics for a completed run."""
        self.transition_run(
            run_id,
            RunStatus.DRAFT_COMPLETED,
            completed_at,
            {
                "duration_seconds": round(completion.duration_seconds, 3),
                "character_counts": {
                    "source": completion.source_characters,
                    "draft": completion.draft_characters,
                },
                "token_estimates": {
                    "source": completion.source_tokens,
                    "draft": completion.draft_tokens,
                    "method": (
                        "characters_per_token: ja=1, other_languages=4"
                    ),
                },
                "draft_title": completion.draft_title,
            },
        )
