"""Register a new novel with its bible and source directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from novel_translator.domain.errors import ValidationError
from novel_translator.domain.translation import TranslationBible
from novel_translator.infrastructure.catalog import (
    ExportConfig,
    NovelConfig,
    NovelRegistry,
    TranslationConfig,
)

_NOVEL_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_SOURCE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:md|txt)")
"""Plain source filenames accepted for a new novel's source directory."""
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
"""Windows device names refused with or without an extension."""
_BIBLE_DIR = "config"
_SOURCES_DIR = "novel-sources"


@dataclass(frozen=True, slots=True)
class RegisterNovelInput:
    """Typed fields for one novel registration without web or CLI types."""

    novel_id: str
    title: str
    model: str
    export_repository: str
    bible_text: str | None = None
    bible_path: Path | None = None
    source_files: dict[str, str] | None = None
    kakuyomu_episode_root: str | None = None
    provider: str = "opencode-go"
    default_volume: int | None = None
    export_directory: str | None = None
    export_filename_template: str = "{chapter:03}.md"


@dataclass(frozen=True, slots=True)
class RegisterNovelResult:
    """Absolute novel paths plus the reloaded registry."""

    novel_id: str
    bible: Path
    source_directory: Path
    registry: NovelRegistry


def _require_text(value: str, label: str) -> str:
    """Strip one required field or raise an orienting error."""
    normalized = value.strip()
    if not normalized:
        raise ValidationError(f"Novel {label} must be non-empty.")
    return normalized


def _read_bible_text(request: RegisterNovelInput) -> str:
    """Return normalized bible text from exactly one bible source."""
    if request.bible_text is not None and request.bible_path is not None:
        raise ValidationError(
            "Provide either bible_text or bible_path, not both."
        )
    if request.bible_text is not None:
        raw = request.bible_text
    elif request.bible_path is not None:
        try:
            raw = request.bible_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValidationError(
                f"Bible file could not be read: {error}"
            ) from error
    else:
        raise ValidationError(
            "Provide a translation bible via bible_text or bible_path."
        )
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    try:
        TranslationBible.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValueError) as error:
        raise ValidationError(f"Invalid translation bible: {error}") from error
    if not text.endswith("\n"):
        text += "\n"
    return text


def validate_source_filename(name: str) -> None:
    """Reject generated-source filenames outside the allowlist."""
    if _SOURCE_FILENAME.fullmatch(name) is None:
        raise ValidationError(
            f"Invalid source filename: '{name}'. "
            "Use a plain filename such as 'chapter-1.md'."
        )
    if name != name.strip() or name != name.strip("."):
        raise ValidationError(
            f"Invalid source filename: '{name}'. "
            "Use a plain filename such as 'chapter-1.md'."
        )
    stem = name.split(".", 1)[0].upper()
    if stem in _RESERVED_NAMES:
        raise ValidationError(
            f"Invalid source filename: '{name}'. "
            "Use a plain filename such as 'chapter-1.md'."
        )


class RegisterNovel:
    """Write one novel's bible and sources, then persist the catalog."""

    def __init__(self, registry: NovelRegistry) -> None:
        self._registry = registry

    def execute(self, request: RegisterNovelInput) -> RegisterNovelResult:
        """Validate inputs, write novel files, and append the catalog."""
        registry = self._registry.reload()
        novel_id = request.novel_id.strip()
        if _NOVEL_ID.fullmatch(novel_id) is None:
            raise ValidationError(
                f"Invalid novel identifier '{novel_id or '<empty>'}'. "
                "Use lowercase letters, digits, and hyphens."
            )
        title = _require_text(request.title, "title")
        model = _require_text(request.model, "model")
        provider = _require_text(request.provider, "provider")
        repository = _require_text(
            request.export_repository, "export repository"
        )
        bible_text = _read_bible_text(request)
        if novel_id in registry.all_run_identities():
            raise ValidationError(
                f"Novel is already registered: {novel_id}. "
                "Remove it from novels.yaml before registering it again."
            )
        catalog_dir = registry.path.parent
        bible_relative = (
            Path(_BIBLE_DIR) / f"{novel_id}.translation-bible.yaml"
        )
        source_relative = Path(_SOURCES_DIR) / novel_id
        bible_path = catalog_dir / bible_relative
        if bible_path.exists():
            raise ValidationError(
                f"Bible file already exists: {bible_path}. "
                "Remove it before registering this novel."
            )
        if request.export_directory is None:
            export_directory = f"src/content/titles/{novel_id}"
        else:
            export_directory = _require_text(
                request.export_directory, "export directory"
            )
        try:
            config = NovelConfig(
                title=title,
                bible=bible_relative,
                source_directory=source_relative,
                export=ExportConfig(
                    repository=repository,
                    directory=Path(export_directory),
                    filename_template=request.export_filename_template,
                ),
                kakuyomu_episode_root=request.kakuyomu_episode_root,
                translation=TranslationConfig(
                    provider=provider,
                    model=model,
                    default_volume=request.default_volume,
                ),
            )
        except ValueError as error:
            raise ValidationError(
                f"Invalid novel registration: {error}"
            ) from error
        normalized_sources: dict[str, str] = {}
        for name, content in (request.source_files or {}).items():
            validate_source_filename(name)
            normalized_sources[name] = content.replace("\r\n", "\n").replace(
                "\r", "\n"
            )
        reloaded = registry.register_novel(
            novel_id, config, bible_text, normalized_sources
        )
        return RegisterNovelResult(
            novel_id=novel_id,
            bible=reloaded.resolve_path(bible_relative),
            source_directory=reloaded.resolve_path(source_relative),
            registry=reloaded,
        )
