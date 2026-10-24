"""Deterministic run bundles for local and web sync."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import RUN_ID_PATTERN
from novel_translator.domain.translation import TranslationBible
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import json_dumps, sha256_text

if TYPE_CHECKING:
    from novel_translator.infrastructure.catalog import NovelRegistry

BUNDLE_VERSION = 1
"""Schema version embedded in every run bundle manifest."""

_MANIFEST_NAME = "bundle.json"
_EPOCH_DATE = (1980, 1, 1, 0, 0, 0)
MAX_BUNDLE_UNCOMPRESSED_BYTES = 256_000_000
"""Largest total uncompressed bundle content accepted on import."""
_MAX_BUNDLE_ENTRIES = 4096
"""Largest entry count accepted in one run bundle."""
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:$")
_CORE_FILES = (
    "source.txt",
    "draft.md",
    "draft.sha256",
    "run.json",
    "bible.json",
)
_APPROVALS_NAME = "editorial/approvals.jsonl"
_EXPORTS_NAME = "editorial/exports.jsonl"


@dataclass(frozen=True, slots=True)
class ExportRunBundleInput:
    """Select one verified run to bundle."""

    run_id: str


@dataclass(frozen=True, slots=True)
class ExportRunBundleResult:
    """Portable bundle bytes plus its download filename."""

    payload: bytes
    run_id: str
    filename: str


@dataclass(frozen=True, slots=True)
class ImportRunBundleInput:
    """Bundle bytes received from another machine."""

    payload: bytes
    expected_novel: str | None = None
    expected_chapter: int | None = None


@dataclass(frozen=True, slots=True)
class ImportRunBundleResult:
    """Identity of the stored run and whether it is new."""

    run_id: str
    novel: str
    chapter: int
    created: bool


def _canonical(data: bytes, label: str) -> bytes:
    """Decode UTF-8 bytes and normalize line endings to ``\\n``."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IntegrityError(
            f"Run bundle text is invalid: {label}."
        ) from error
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _canonical_lines(data: bytes, label: str) -> list[str]:
    """Split ledger bytes into normalized lines without line breaks."""
    text = _canonical(data, label).decode("utf-8")
    return [line for line in text.split("\n") if line]


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Durably create one file with exact bytes on any platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            with suppress(OSError):
                temporary.unlink()


def _dump_zip(files: dict[str, bytes]) -> bytes:
    """Serialize sorted entries into deterministic zip bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_EPOCH_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _run_metadata(workspace: Workspace, run_id: str) -> dict[str, object]:
    """Read and validate one run's metadata without trusting callers."""
    try:
        serialized = workspace.storage.run_path(run_id, "run.json").read_text(
            encoding="utf-8"
        )
    except FileNotFoundError as error:
        raise ValidationError("Run was not found.") from error
    except (OSError, UnicodeError) as error:
        raise ValidationError("Run metadata could not be read.") from error
    try:
        loaded: object = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise IntegrityError("Run metadata contains invalid JSON.") from error
    if not isinstance(loaded, dict):
        raise IntegrityError("Run metadata must be a JSON object.")
    metadata = cast(dict[str, object], loaded)
    if metadata.get("run_id") != run_id:
        raise IntegrityError(
            "Run metadata does not match the requested run ID."
        )
    return metadata


def _run_identity(metadata: dict[str, object]) -> tuple[str, int]:
    """Extract the validated novel and chapter from run metadata."""
    identity: object = metadata.get("identity")
    if not isinstance(identity, dict):
        raise IntegrityError("Run identity is invalid.")
    typed = cast(dict[str, object], identity)
    novel: object = typed.get("novel")
    chapter: object = typed.get("chapter")
    if (
        not isinstance(novel, str)
        or not novel.strip()
        or not isinstance(chapter, int)
        or isinstance(chapter, bool)
        or chapter < 1
    ):
        raise IntegrityError("Run identity is invalid.")
    return novel, chapter


def _verify_source(
    workspace: Workspace, run_id: str, metadata: dict[str, object]
) -> str:
    """Return normalized source text matching the recorded source hash."""
    try:
        source = workspace.reader.source(run_id)
    except ValidationError:
        raise
    except IntegrityError as error:
        raise IntegrityError("Run source is unavailable.") from error
    expected = metadata.get("source_hash")
    if not isinstance(expected, str):
        raise IntegrityError("Run source hash is invalid.")
    if sha256_text(source) != expected:
        raise IntegrityError("Run source integrity check failed.")
    return source


def _verify_bible(
    workspace: Workspace, run_id: str, metadata: dict[str, object]
) -> None:
    """Require the bible snapshot to match its recorded canonical hash."""
    try:
        bible_path = workspace.storage.run_path(run_id, "bible.json")
        serialized = bible_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise IntegrityError("Run bible is unavailable.") from error
    try:
        bible = TranslationBible.model_validate_json(serialized)
    except ValueError as error:
        raise IntegrityError("Run bible is invalid.") from error
    expected = metadata.get("bible_hash")
    if not isinstance(expected, str):
        raise IntegrityError("Run bible hash is invalid.")
    if sha256_text(bible.model_dump_json()) != expected:
        raise IntegrityError("Run bible integrity check failed.")


def _read_run_file(workspace: Workspace, run_id: str, relative: str) -> bytes:
    """Read one canonical run file, failing when the run is incomplete."""
    try:
        raw = workspace.storage.run_path(run_id, relative).read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrityError(
            f"Run is incomplete; missing {relative}."
        ) from error
    return _canonical(raw, f"runs/{run_id}/{relative}")


def _collect_run_files(workspace: Workspace, run_id: str) -> dict[str, bytes]:
    """Collect canonical run bytes, excluding mutable session state."""
    prefix = f"runs/{run_id}/"
    files = {
        f"{prefix}{name}": _read_run_file(workspace, run_id, name)
        for name in _CORE_FILES
    }
    revisions_root = workspace.storage.run_path(run_id, "revisions")
    if revisions_root.exists():
        for path in sorted(revisions_root.rglob("*")):
            if path.is_dir() or path.is_symlink():
                continue
            if not path.is_file():
                raise IntegrityError("Revision directory is invalid.")
            relative = path.relative_to(revisions_root).as_posix()
            raw = path.read_bytes()
            files[f"{prefix}revisions/{relative}"] = _canonical(
                raw, f"{prefix}revisions/{relative}"
            )
    return files


def _matching_ledger_lines(
    workspace: Workspace, filename: str, run_id: str, label: str
) -> bytes | None:
    """Return canonical ledger lines for one run, if any exist."""
    path = workspace.storage.safe(Path(filename))
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrityError(f"{label} events are invalid.") from error
    kept: list[str] = []
    for line in _canonical_lines(raw, filename):
        try:
            loaded: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise IntegrityError(f"{label} events are invalid.") from error
        if not isinstance(loaded, dict):
            raise IntegrityError(f"{label} events are invalid.")
        entry = cast(dict[str, object], loaded)
        if entry.get("run_id") == run_id:
            kept.append(line)
    if not kept:
        return None
    return ("\n".join(kept) + "\n").encode("utf-8")


class ExportRunBundle:
    """Bundle one verified run into deterministic portable bytes."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, request: ExportRunBundleInput) -> ExportRunBundleResult:
        """Verify and bundle one run, excluding mutable session state."""
        run_id = request.run_id
        metadata = _run_metadata(self._workspace, run_id)
        novel, chapter = _run_identity(metadata)
        artifact = self._workspace.runs.generated_draft(run_id)
        _verify_source(self._workspace, run_id, metadata)
        _verify_bible(self._workspace, run_id, metadata)
        files = _collect_run_files(self._workspace, run_id)
        current = self._workspace.storage.safe(
            Path("current") / f"{run_id}.json"
        )
        if current.exists():
            try:
                raw = current.read_bytes()
            except (OSError, UnicodeError) as error:
                raise IntegrityError(
                    "Generated draft projection is invalid."
                ) from error
            files[f"current/{run_id}.json"] = _canonical(
                raw, f"current/{run_id}.json"
            )
        approvals = _matching_ledger_lines(
            self._workspace, _APPROVALS_NAME, run_id, "Approval"
        )
        if approvals is not None:
            files[_APPROVALS_NAME] = approvals
        exports = _matching_ledger_lines(
            self._workspace, _EXPORTS_NAME, run_id, "Export"
        )
        if exports is not None:
            files[_EXPORTS_NAME] = exports
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "run_id": run_id,
            "novel": novel,
            "chapter": chapter,
            "exported_at": datetime.now(UTC).isoformat(),
            "files": {
                name: hashlib.sha256(data).hexdigest()
                for name, data in sorted(files.items())
            },
        }
        files[_MANIFEST_NAME] = (json_dumps(manifest) + "\n").encode("utf-8")
        payload = _dump_zip(files)
        filename = f"{novel}-ch{chapter}-{artifact.content_hash[:8]}.ntbundle"
        return ExportRunBundleResult(payload, run_id, filename)


def _read_zip(payload: bytes) -> dict[str, bytes]:
    """Unpack bundle entries while rejecting traversal and absolute paths."""
    if not payload:
        raise ValidationError("Run bundle must not be empty.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as error:
        raise ValidationError("Bundle is not a valid run bundle.") from error
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > _MAX_BUNDLE_ENTRIES:
            raise ValidationError("Run bundle holds too many files.")
        total = sum(info.file_size for info in infos)
        if total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise ValidationError("Run bundle is too large when unpacked.")
        entries: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            if (
                "\\" in name
                or ":" in name
                or not name
                or name.startswith("/")
                or "//" in name
                or "/./" in name
                or name.startswith("./")
                or name.endswith("/.")
                or name in (".", "..")
                or PurePosixPath(name).is_absolute()
            ):
                raise ValidationError("Bundle is not a valid run bundle.")
            parts = PurePosixPath(name).parts
            if not parts:
                raise ValidationError("Bundle is not a valid run bundle.")
            if any(
                segment in ("", ".", "..") or _DRIVE_LETTER.match(segment)
                for segment in parts
            ):
                raise ValidationError("Bundle is not a valid run bundle.")
            if name in entries:
                raise IntegrityError("Run bundle contains a duplicate file.")
            try:
                entries[name] = archive.read(info.filename)
            except (zipfile.BadZipFile, OSError) as error:
                raise ValidationError(
                    "Bundle is not a valid run bundle."
                ) from error
    return entries


def _bundle_manifest(entries: dict[str, bytes]) -> dict[str, object]:
    """Parse and validate the bundle manifest."""
    raw = entries.get(_MANIFEST_NAME)
    if raw is None:
        raise ValidationError("Run bundle is incomplete: bundle.json.")
    try:
        loaded: object = json.loads(_canonical(raw, _MANIFEST_NAME))
    except json.JSONDecodeError as error:
        raise IntegrityError("Run bundle manifest is invalid.") from error
    if not isinstance(loaded, dict):
        raise IntegrityError("Run bundle manifest is invalid.")
    manifest = cast(dict[str, object], loaded)
    if manifest.get("bundle_version") != BUNDLE_VERSION:
        raise ValidationError("Unsupported run bundle version.")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValidationError("Run bundle carries an invalid run ID.")
    return manifest


def _bundle_ledger(
    entries: dict[str, bytes], name: str, run_id: str
) -> list[str]:
    """Validate bundled ledger lines belong to the bundled run."""
    raw = entries.get(name)
    if raw is None:
        return []
    lines = _canonical_lines(raw, name)
    for line in lines:
        try:
            loaded: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise IntegrityError("Run bundle ledger is invalid.") from error
        if not isinstance(loaded, dict):
            raise IntegrityError("Run bundle ledger is invalid.")
        ledger = cast(dict[str, object], loaded)
        if ledger.get("run_id") != run_id:
            raise IntegrityError("Run bundle ledger is invalid.")
    return lines


class ImportRunBundle:
    """Verify and store one run bundle without touching session state."""

    def __init__(
        self, workspace: Workspace, registry: NovelRegistry | None = None
    ) -> None:
        self._workspace = workspace
        self._registry = registry

    def execute(self, request: ImportRunBundleInput) -> ImportRunBundleResult:
        """Verify bundle bytes and store missing artifacts idempotently."""
        entries = _read_zip(request.payload)
        manifest = _bundle_manifest(entries)
        run_id = cast(str, manifest.get("run_id"))
        prefix = f"runs/{run_id}/"
        current_name = f"current/{run_id}.json"
        allowed = {
            _MANIFEST_NAME,
            _APPROVALS_NAME,
            _EXPORTS_NAME,
            current_name,
        }
        for name in entries:
            if name == _MANIFEST_NAME or name.startswith(prefix):
                continue
            if name in allowed:
                continue
            raise ValidationError(
                f"Run bundle contains an unexpected file: {name}."
            )
        run_files = {
            name[len(prefix) :]: _canonical(data, name)
            for name, data in entries.items()
            if name.startswith(prefix)
        }
        for name in _CORE_FILES:
            if name not in run_files:
                raise ValidationError(f"Run bundle is incomplete: {name}.")
        listed: object = manifest.get("files")
        if not isinstance(listed, dict):
            raise IntegrityError("Run bundle manifest is invalid.")
        files_map = cast(dict[str, str], listed)
        for name, data in entries.items():
            if name == _MANIFEST_NAME:
                continue
            canonical = (
                run_files[name[len(prefix) :]]
                if name.startswith(prefix)
                else _canonical(data, name)
            )
            expected = files_map.get(name)
            if (
                not isinstance(expected, str)
                or hashlib.sha256(canonical).hexdigest() != expected
            ):
                raise IntegrityError(
                    f"Run bundle integrity check failed: {name}."
                )
        for listed_name in files_map:
            if listed_name not in entries:
                raise IntegrityError("Run bundle manifest is invalid.")
        try:
            metadata_raw: object = json.loads(run_files["run.json"])
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise IntegrityError("Run metadata is invalid.") from error
        if not isinstance(metadata_raw, dict):
            raise IntegrityError("Run metadata is invalid.")
        metadata = cast(dict[str, object], metadata_raw)
        if metadata.get("run_id") != run_id:
            raise IntegrityError("Run metadata is invalid.")
        novel, chapter = _run_identity(metadata)
        if (
            manifest.get("novel") != novel
            or manifest.get("chapter") != chapter
        ):
            raise IntegrityError("Run bundle manifest is invalid.")
        expected_novel = request.expected_novel
        if expected_novel is not None and novel != expected_novel:
            raise ValidationError(
                "Run bundle does not match the requested novel and chapter."
            )
        expected_chapter = request.expected_chapter
        if expected_chapter is not None and chapter != expected_chapter:
            raise ValidationError(
                "Run bundle does not match the requested novel and chapter."
            )
        if self._registry is not None:
            self._registry.novel(novel)
        self._verify_content(run_files, metadata)
        created = self._store_run_files(run_id, run_files)
        self._store_current(run_id, current_name, entries.get(current_name))
        approvals_blob = entries.get(_APPROVALS_NAME)
        self._merge_ledger(_APPROVALS_NAME, run_id, approvals_blob)
        exports_blob = entries.get(_EXPORTS_NAME)
        self._merge_ledger(_EXPORTS_NAME, run_id, exports_blob)
        return ImportRunBundleResult(run_id, novel, chapter, created)

    @staticmethod
    def _verify_content(
        run_files: dict[str, bytes], metadata: dict[str, object]
    ) -> None:
        """Verify bundled draft, source, and bible against run metadata."""
        try:
            draft = run_files["draft.md"].decode("utf-8")
            recorded = run_files["draft.sha256"].decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise IntegrityError(
                "Run bundle draft integrity check failed."
            ) from error
        if sha256_text(draft) != recorded:
            raise IntegrityError("Run bundle draft integrity check failed.")
        try:
            source = run_files["source.txt"].decode("utf-8")
        except UnicodeDecodeError as error:
            raise IntegrityError(
                "Run bundle source integrity check failed."
            ) from error
        expected_source = metadata.get("source_hash")
        if (
            not isinstance(expected_source, str)
            or sha256_text(source) != expected_source
        ):
            raise IntegrityError("Run bundle source integrity check failed.")
        try:
            bible = TranslationBible.model_validate_json(
                run_files["bible.json"].decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise IntegrityError(
                "Run bundle bible integrity check failed."
            ) from error
        expected_bible = metadata.get("bible_hash")
        if (
            not isinstance(expected_bible, str)
            or sha256_text(bible.model_dump_json()) != expected_bible
        ):
            raise IntegrityError("Run bundle bible integrity check failed.")

    def _store_run_files(
        self, run_id: str, run_files: dict[str, bytes]
    ) -> bool:
        """Store missing run files; refuse divergent bytes on collision."""
        storage = self._workspace.storage
        anchor = storage.run_path(run_id)
        created = not anchor.exists()
        anchor_resolved = anchor.resolve()
        for relative in sorted(run_files):
            target = storage.run_path(run_id, *PurePosixPath(relative).parts)
            if os.path.commonpath([anchor_resolved, target.resolve()]) != str(
                anchor_resolved
            ):
                raise ValidationError(
                    f"Run bundle contains an unsafe path: {relative}."
                )
            if target.exists():
                try:
                    existing = _canonical(target.read_bytes(), relative)
                except (OSError, UnicodeError) as error:
                    raise IntegrityError(
                        f"Stored run file is unreadable: {relative}."
                    ) from error
                if existing != run_files[relative]:
                    raise IntegrityError(
                        f"Run {run_id} already exists with different "
                        f"content in {relative}; refusing to overwrite it."
                    )
                continue
            _atomic_write_bytes(target, run_files[relative])
        return created

    def _store_current(
        self, run_id: str, name: str, data: bytes | None
    ) -> None:
        """Store a missing draft projection; refuse divergent projections."""
        if data is None:
            return
        canonical = _canonical(data, name)
        target = self._workspace.storage.safe(
            Path("current") / f"{run_id}.json"
        )
        if target.exists():
            try:
                existing = _canonical(target.read_bytes(), name)
            except (OSError, UnicodeError) as error:
                raise IntegrityError(
                    "Generated draft projection is invalid."
                ) from error
            if existing != canonical:
                raise IntegrityError(
                    f"Run {run_id} already exists with different "
                    "content in current projection; "
                    "refusing to overwrite it."
                )
            return
        _atomic_write_bytes(target, canonical)

    def _merge_ledger(
        self, name: str, run_id: str, data: bytes | None
    ) -> None:
        """Append bundled ledger lines that are not already stored."""
        bundle = {name: data} if data is not None else {}
        incoming: list[str] = []
        for line in _bundle_ledger(bundle, name, run_id):
            if line not in incoming:
                incoming.append(line)
        if not incoming:
            return
        target = self._workspace.storage.safe(Path(name))
        present: set[str] = set()
        if target.exists():
            try:
                raw = target.read_bytes()
            except (OSError, UnicodeError) as error:
                raise IntegrityError(f"{name} events are invalid.") from error
            present = set(_canonical_lines(raw, name))
        missing = [line for line in incoming if line not in present]
        if not missing:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            for line in missing:
                handle.write(line + "\n")
