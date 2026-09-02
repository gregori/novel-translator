"""Application services for local, auditable novel translation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from asyncio import CancelledError
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from math import ceil
from pathlib import Path
from typing import Any, Final, Protocol, cast

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_translator.shared.errors import (
    ApprovalRequired,
    CollisionRequired,
    IntegrityError,
    ValidationError,
)
from novel_translator.shared.models import (
    ChapterIdentity,
    PromptCall,
    RunPhase,
    RunRecord,
    RunStatus,
    SegmentPromptManifest,
)
from novel_translator.shared.utils import json_dumps, sha256_text

DEFAULT_SEGMENT_LIMIT = 60_000
PREVIOUS_TRANSLATION_CONTEXT_CHARS = 12_000
RUN_SCHEMA_VERSION = 2
RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
PROMPT_TEMPLATE_VERSION = "v1"
PROMPT_TEMPLATE = (
    "{context}{continuity_context}\n\nSegment {segment_index}:\n{source_segment}\n\nReturn only English translation."
)
TERMINAL_RUN_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {RunStatus.DRAFT_COMPLETED, RunStatus.FAILED, RunStatus.INTERRUPTED}
)


class PageTitleParser(HTMLParser):
    """Extract the Open Graph or document title from a fetched HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.open_graph_title: str | None = None
        self.document_title: list[str] = []
        self._inside_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track title-bearing tags."""
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("property") == "og:title":
            self.open_graph_title = attributes.get("content")
        if tag == "title":
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        """Stop collecting document-title text."""
        if tag == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        """Collect plain text within a document title."""
        if self._inside_title:
            self.document_title.append(data)

    def title(self) -> str | None:
        """Return a non-empty preferred page title."""
        candidate = self.open_graph_title or "".join(self.document_title)
        return candidate.strip() or None


class BibleCharacter(BaseModel):
    """A canonical character name and optional aliases."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    aliases: list[str] = Field(default_factory=list)


class TranslationBible(BaseModel):
    """Strict translation-bible schema used to build deterministic context."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str
    source_language: str = "ja"
    target_language: str = "en"
    characters: list[BibleCharacter] = Field(default_factory=list[BibleCharacter])
    terminology: dict[str, str] = Field(default_factory=dict)
    honorific_rules: list[str] = Field(default_factory=list)
    naming_conventions: list[str] = Field(default_factory=list)
    style_instructions: list[str] = Field(default_factory=list)
    version: str | None = None

    @model_validator(mode="after")
    def validate_canonical_names(self) -> TranslationBible:
        """Reject duplicate names and aliases that collide with canonical names."""
        names = [character.name.casefold() for character in self.characters]
        aliases = [alias.casefold() for character in self.characters for alias in character.aliases]
        if len(names) != len(set(names)) or set(names).intersection(aliases):
            raise ValueError("Character canonical names and aliases must be unambiguous.")
        return self


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Normalized source text with provenance metadata."""

    content: str
    origin: str
    extracted_title: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalEvent:
    """Append-only event recording approval state for an exact draft hash."""

    run_id: str
    draft_hash: str
    approved: bool
    timestamp: str


class TranslatorGateway(Protocol):
    """Port for an interchangeable translation provider."""

    def translate(self, prompt: str) -> str:
        """Translate one prompt and return non-empty text."""
        ...


def load_bible(path: Path) -> TranslationBible:
    """Load and validate a UTF-8 YAML translation bible."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TranslationBible.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ValidationError(f"Invalid translation bible: {error}") from error


def read_source(value: str) -> SourceDocument:
    """Read a local UTF-8 file or supported Kakuyomu URL."""
    if value.startswith(("http://", "https://")):
        if "kakuyomu.jp" not in value:
            raise ValidationError("Only Kakuyomu URLs are supported in v1.")
        response = httpx.get(value, timeout=120.0)
        response.raise_for_status()
        title_parser = PageTitleParser()
        title_parser.feed(response.text)
        text = re.sub(r"<[^>]+>", "", response.text).strip()
        if not text:
            raise ValidationError("Kakuyomu page did not contain readable text.")
        return SourceDocument(text, value, title_parser.title())
    path = Path(value)
    if not path.is_file():
        raise ValidationError("Source must be a readable file or Kakuyomu URL.")
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValidationError("Source file must be valid UTF-8.") from error
    if not text:
        raise ValidationError("Source file must not be empty.")
    return SourceDocument(text, str(path.resolve()))


def build_context(bible: TranslationBible) -> str:
    """Build a stable, bounded context section from a validated bible."""
    lines = [
        f"Title: {bible.title}",
        f"Translate {bible.source_language} to {bible.target_language}.",
    ]
    for character in sorted(bible.characters, key=lambda item: item.name.casefold()):
        lines.append(f"Character: {character.name}")
        if character.aliases:
            aliases = ", ".join(sorted(character.aliases, key=str.casefold))
            lines.append(f"Aliases: {aliases}")
    lines.extend(f"Term: {source} => {target}" for source, target in sorted(bible.terminology.items()))
    lines.extend(f"Honorific rule: {item}" for item in bible.honorific_rules)
    lines.extend(f"Naming convention: {item}" for item in bible.naming_conventions)
    lines.extend(f"Style: {item}" for item in bible.style_instructions)
    return "\n".join(lines)


def estimate_tokens(text: str, language: str) -> int:
    """Estimate tokens when the provider does not expose model-tokenizer usage."""
    characters_per_token = 1 if language == "ja" else 4
    return ceil(len(text) / characters_per_token)


def extract_draft_title(draft: str, chapter: int) -> str | None:
    """Extract a matching English episode heading from a raw translation draft."""
    pattern = re.compile(
        rf"^(?:#+\s*)?(?:Chapter|Episode)\s+{chapter}\s*[:–-]\s*.+$",
        re.IGNORECASE,
    )
    for line in (line.strip() for line in draft.splitlines() if line.strip()):
        if pattern.fullmatch(line):
            return line.lstrip("#").strip()
    return None


def segment_text(text: str, limit: int = DEFAULT_SEGMENT_LIMIT) -> list[str]:
    """Pack paragraphs into bounded segments without losing source characters."""
    if len(text) <= limit:
        return [text]
    segments: list[str] = []
    current = ""
    for paragraph in text.splitlines(keepends=True):
        if len(paragraph) <= limit:
            if current and len(current) + len(paragraph) > limit:
                segments.append(current)
                current = paragraph
            else:
                current += paragraph
            continue
        if current:
            segments.append(current)
            current = ""
        sentences = re.split(r"(?<=[。！？.!?])", paragraph)
        for sentence in sentences:
            if len(sentence) > limit:
                raise ValidationError("A sentence exceeds the configured segment limit.")
            if current and len(current) + len(sentence) > limit:
                segments.append(current)
                current = sentence
            else:
                current += sentence
    if current:
        segments.append(current)
    if "".join(segments) != text:
        raise IntegrityError("Segmentation must reconstruct the normalized source exactly.")
    return segments


def render_translation_prompt(
    context: str,
    continuity_context: str,
    segment_index: int,
    source_segment: str,
    template: str = PROMPT_TEMPLATE,
) -> str:
    """Render the exact UTF-8 text passed to the translation gateway."""
    return template.format(
        context=context,
        continuity_context=continuity_context,
        segment_index=segment_index,
        source_segment=source_segment,
    )


def prompt_manifest_hash(
    manifest: list[SegmentPromptManifest] | list[dict[str, object]],
) -> str:
    """Hash the ordered rendered-prompt hashes for a run."""
    rendered_hashes = [
        item.rendered_prompt_hash
        if isinstance(item, SegmentPromptManifest)
        else cast(str, item["rendered_prompt_hash"])
        for item in manifest
    ]
    return sha256_text(json.dumps(rendered_hashes, separators=(",", ":")))


class Workspace:
    """Filesystem adapter preserving immutable run artifacts and editorial events."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, relative: Path) -> Path:
        unresolved = self.root / relative
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValidationError("Path escapes the workspace or is a symlink.")
        target = unresolved.resolve()
        if os.path.commonpath([self.root, target]) != str(self.root):
            raise ValidationError("Path escapes the workspace or is a symlink.")
        return target

    def _run_path(self, run_id: str, *parts: str) -> Path:
        """Return a safe path below a validated application-generated run ID."""
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValidationError("Run ID must be 32 lowercase hexadecimal characters.")
        return self._safe(Path("runs") / run_id / Path(*parts))

    def _atomic_write(self, path: Path, content: str) -> None:
        if path.exists():
            raise IntegrityError(f"Immutable artifact already exists: {path.name}")
        self._atomic_replace(path, content)

    def _atomic_replace(self, path: Path, content: str) -> None:
        """Durably replace one file without exposing partial content."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                with suppress(OSError):
                    temporary.unlink()

    def create_run(
        self,
        record: RunRecord,
        source: SourceDocument,
        bible: TranslationBible,
    ) -> Path:
        """Create immutable source, bible snapshot and run metadata."""
        run_dir = self._run_path(record.run_id)
        if run_dir.exists():
            raise IntegrityError("Run identifier collision.")
        run_dir.mkdir(parents=True)
        self._atomic_write(run_dir / "source.txt", source.content)
        self._atomic_write(run_dir / "bible.json", bible.model_dump_json(indent=2))
        self._atomic_write(run_dir / "run.json", json_dumps(asdict(record)))
        return run_dir

    def save_draft(self, run_id: str, draft: str) -> str:
        """Persist a complete draft and atomically update its current projection."""
        run_dir = self._run_path(run_id)
        draft_path = run_dir / "draft.md"
        self._atomic_write(draft_path, draft)
        draft_hash = sha256_text(draft)
        self._atomic_write(run_dir / "draft.sha256", draft_hash)
        current = self._safe(Path("current") / f"{run_id}.json")
        current.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_replace(current, json_dumps({"run_id": run_id, "draft_hash": draft_hash}))
        return draft_hash

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
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        if payload.get("status") != RunStatus.STARTED:
            raise IntegrityError("Only a started run can transition to a terminal status.")
        payload.update(updates or {})
        payload.update({"status": status, "completed_at": completed_at.isoformat()})
        self._atomic_replace(path, json_dumps(payload))

    def record_prompt_segment(self, run_id: str, segment: SegmentPromptManifest) -> None:
        """Append ordered hash provenance before a segment reaches the gateway."""
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        manifest = cast(list[dict[str, object]], payload["segment_manifest"])
        expected_index = len(manifest) + 1
        if segment.segment_index != expected_index:
            raise IntegrityError("Prompt segments must be recorded in order.")
        manifest.append(cast(dict[str, object], asdict(segment)))
        payload["prompt_hash"] = prompt_manifest_hash(manifest)
        self._atomic_replace(path, json_dumps(payload))

    def record_prompt_call(self, run_id: str, segment_index: int, call: PromptCall) -> None:
        """Associate one gateway attempt with its exact rendered prompt hash."""
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        manifest = cast(list[dict[str, object]], payload["segment_manifest"])
        if segment_index < 1 or segment_index > len(manifest):
            raise IntegrityError("Gateway call references an unknown segment.")
        segment = manifest[segment_index - 1]
        if call.rendered_prompt_hash != segment["rendered_prompt_hash"]:
            raise IntegrityError("Gateway call prompt hash does not match segment.")
        calls = cast(list[dict[str, object]], segment["gateway_calls"])
        if call.attempt != len(calls) + 1:
            raise IntegrityError("Gateway attempts must be recorded in order.")
        calls.append(cast(dict[str, object], asdict(call)))
        self._atomic_replace(path, json_dumps(payload))

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
        """Record bounded failure metadata without persisting exception messages."""
        if status not in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            raise IntegrityError("A terminated run must be failed or interrupted.")
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
        duration_seconds: float,
        source: SourceDocument,
        draft: str,
        bible: TranslationBible,
    ) -> None:
        """Record final audit metrics after an immutable draft has been persisted."""
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        self.transition_run(
            run_id,
            RunStatus.DRAFT_COMPLETED,
            completed_at,
            {
                "duration_seconds": round(duration_seconds, 3),
                "character_counts": {
                    "source": len(source.content),
                    "draft": len(draft),
                },
                "token_estimates": {
                    "source": estimate_tokens(source.content, bible.source_language),
                    "draft": estimate_tokens(draft, bible.target_language),
                    "method": "characters_per_token: ja=1, other_languages=4",
                },
                "draft_title": extract_draft_title(draft, cast(dict[str, int], payload["identity"])["chapter"]),
            },
        )

    def draft(self, run_id: str) -> str:
        """Read the current immutable draft."""
        return self._run_path(run_id, "draft.md").read_text(encoding="utf-8")

    def draft_title(self, run_id: str) -> str | None:
        """Read the stored title or infer one for a legacy raw draft."""
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
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
        path = self._run_path(run_id, "run.json")
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        value = payload.get("volume")
        if value is None:
            return None
        if type(value) is not int or value < 1:
            raise IntegrityError("Run volume must be a positive integer when present.")
        return value

    def inspect_run(
        self, run_id: str, include_draft: bool = False
    ) -> dict[str, object]:
        """Read validated run metadata and optionally its draft."""
        try:
            serialized = self._run_path(run_id, "run.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise ValidationError("Run metadata was not found.") from error
        except (OSError, UnicodeError) as error:
            raise ValidationError("Run metadata could not be read.") from error
        try:
            loaded: object = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise IntegrityError("Run metadata contains invalid JSON.") from error
        if not isinstance(loaded, dict):
            raise IntegrityError("Run metadata must be a JSON object.")
        data = cast(dict[str, object], loaded)
        if data.get("run_id") != run_id:
            raise IntegrityError("Run metadata does not match the requested run ID.")
        if include_draft:
            try:
                data["draft"] = self._run_path(run_id, "draft.md").read_text(
                    encoding="utf-8"
                )
            except FileNotFoundError as error:
                raise ValidationError("Run draft was not found.") from error
            except (OSError, UnicodeError) as error:
                raise ValidationError("Run draft could not be read.") from error
        return data

    def append_approval(self, event: ApprovalEvent) -> None:
        """Append an approval event without modifying prior events."""
        path = self._safe(Path("editorial") / "approvals.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")

    def is_approved(self, run_id: str, draft_hash: str) -> bool:
        """Return the latest matching approval decision for a run and hash."""
        path = self._safe(Path("editorial") / "approvals.jsonl")
        latest: dict[str, Any] | None = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event["run_id"] == run_id and event["draft_hash"] == draft_hash:
                    latest = event
        return bool(latest and latest["approved"])


class TranslationService:
    """Coordinates validated translation without coupling to a provider."""

    def __init__(self, workspace: Workspace, gateway: TranslatorGateway) -> None:
        self._workspace = workspace
        self._gateway = gateway

    def translate(
        self,
        identity: ChapterIdentity,
        source: SourceDocument,
        bible: TranslationBible,
        provider: str,
        model: str,
        volume: int | None = None,
        progress: Callable[[int, int, int], None] | None = None,
        retry_notice: Callable[[int, int, int, httpx.TransportError], None] | None = None,
        segment_limit: int = DEFAULT_SEGMENT_LIMIT,
    ) -> str:
        """Create a run, translate each segment and persist a complete draft."""
        context = build_context(bible)
        run_id = uuid.uuid4().hex
        started_at = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            identity=identity,
            source_hash=sha256_text(source.content),
            provider=provider,
            model=model,
            schema_version=RUN_SCHEMA_VERSION,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            prompt_hash=prompt_manifest_hash([]),
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_template_hash=sha256_text(PROMPT_TEMPLATE),
            context_hash=sha256_text(context),
            segment_manifest=[],
            bible_hash=sha256_text(bible.model_dump_json()),
            timestamp=started_at,
            status=RunStatus.STARTED,
            bible_version=bible.version,
            volume=volume,
            source_title=source.extracted_title,
        )
        self._workspace.create_run(record, source, bible)
        phase = RunPhase.TRANSLATION
        current_segment: int | None = None
        current_attempt: int | None = None
        try:
            segments = segment_text(source.content, segment_limit)
            translations: list[str] = []
            previous_translation = ""
            for index, segment in enumerate(segments, start=1):
                current_segment = index
                continuity_context = ""
                if previous_translation:
                    continuity_context = (
                        "\n\nPrevious translated passage for continuity only; do not repeat it:\n"
                        f"{previous_translation[-PREVIOUS_TRANSLATION_CONTEXT_CHARS:]}"
                    )
                prompt = render_translation_prompt(context, continuity_context, index, segment)
                rendered_prompt_hash = sha256_text(prompt)
                self._workspace.record_prompt_segment(
                    run_id,
                    SegmentPromptManifest(
                        segment_index=index,
                        source_segment_hash=sha256_text(segment),
                        continuity_context_hash=sha256_text(continuity_context),
                        rendered_prompt_hash=rendered_prompt_hash,
                        gateway_calls=[],
                    ),
                )
                for attempt in range(1, 4):
                    current_attempt = attempt
                    if progress is not None:
                        progress(index, len(segments), attempt)
                    try:
                        self._workspace.record_prompt_call(
                            run_id,
                            index,
                            PromptCall(attempt, rendered_prompt_hash),
                        )
                        translation = self._gateway.translate(prompt)
                        translations.append(translation)
                        previous_translation = translation
                        break
                    except httpx.TransportError as error:
                        if retry_notice is not None:
                            retry_notice(index, len(segments), attempt, error)
                else:
                    raise ValidationError("Translation failed after three attempts.")
            draft = "".join(translations)
            phase = RunPhase.DRAFT_PERSISTENCE
            current_segment = None
            current_attempt = None
            self._workspace.save_draft(run_id, draft)
            phase = RunPhase.FINALIZATION
            completed_at = datetime.now(UTC)
            self._workspace.complete_run(
                run_id,
                completed_at,
                (completed_at - started_at).total_seconds(),
                source,
                draft,
                bible,
            )
        except (KeyboardInterrupt, CancelledError) as error:
            self._record_termination(
                run_id,
                RunStatus.INTERRUPTED,
                error,
                phase,
                current_segment,
                current_attempt,
            )
            raise
        except Exception as error:
            self._record_termination(
                run_id,
                RunStatus.FAILED,
                error,
                phase,
                current_segment,
                current_attempt,
            )
            raise
        return run_id

    def _record_termination(
        self,
        run_id: str,
        status: RunStatus,
        error: BaseException,
        phase: RunPhase,
        segment: int | None,
        attempt: int | None,
    ) -> None:
        """Best-effort terminal recording that never masks the original failure."""
        try:
            self._workspace.terminate_run(
                run_id,
                status,
                error,
                phase,
                segment,
                attempt,
                datetime.now(UTC),
            )
        except Exception as lifecycle_error:
            error.add_note(f"Could not persist terminal run state: {type(lifecycle_error).__name__}")


def approve(workspace: Workspace, run_id: str, approved: bool = True) -> ApprovalEvent:
    """Append the current approval decision for a complete draft."""
    draft = workspace.draft(run_id)
    event = ApprovalEvent(run_id, sha256_text(draft), approved, datetime.now(UTC).isoformat())
    workspace.append_approval(event)
    return event


def export_draft(
    workspace: Workspace,
    run_id: str,
    destination: Path,
    title: str | None = None,
    overwrite: bool = False,
    publish_date: str | None = None,
) -> Path:
    """Export an approved draft as Markdown without invoking publication tools."""
    draft = workspace.draft(run_id)
    draft_hash = sha256_text(draft)
    if not workspace.is_approved(run_id, draft_hash):
        raise ApprovalRequired("The current draft hash has not been approved.")
    title = title or workspace.draft_title(run_id)
    if title is None:
        raise ValidationError("No draft title found; pass --title to export this run.")
    if publish_date is None:
        rendered_publish_date = date.today().isoformat()
    else:
        try:
            rendered_publish_date = date.fromisoformat(publish_date).isoformat()
        except ValueError as error:
            raise ValidationError("publish_date must use the YYYY-MM-DD format.") from error
    destination = destination.resolve()
    volume = workspace.volume(run_id)
    front_matter = [
        "---",
        f'chapterTitle: "{title}"',
        f"publishDate: {rendered_publish_date}",
    ]
    if volume is not None:
        front_matter.append(f"volume: {volume}")
    rendered = "\n".join([*front_matter, "---", "", draft, ""])
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered and not overwrite:
        raise CollisionRequired("Destination differs; pass explicit overwrite confirmation.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_suffix(destination.suffix + ".bak")
    try:
        if destination.exists():
            shutil.copy2(destination, backup)
        destination.write_text(rendered, encoding="utf-8")
        return destination
    except OSError:
        if backup.exists():
            backup.replace(destination)
        raise
    finally:
        if backup.exists():
            backup.unlink()
