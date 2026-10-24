"""Validated YAML configuration and source discovery for registered novels."""

import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator

from novel_translator.domain.errors import ValidationError
from novel_translator.infrastructure.source import load_bible

_NOVEL_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_SOURCE_NAME = re.compile(r"chapter-(?P<chapter>[1-9][0-9]*)\.(?:md|txt)")
_EPISODE_ID = re.compile(r"[0-9]{1,32}")
_EPISODE_ROOT = re.compile(
    r"https://kakuyomu\.jp/works/[0-9]{1,32}/episodes/?"
)


class ExportConfig(BaseModel):
    """Configured publication target for one novel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = Field(min_length=1)
    directory: Path
    filename_template: str = "{chapter:03}.md"

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        """Reject empty repository identifiers after normalization."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("repository must be non-empty")
        return normalized

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, value: Path) -> Path:
        """Keep the content directory inside the repository checkout."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError(
                "export directory must be relative to the checkout root"
            )
        return value

    @field_validator("filename_template")
    @classmethod
    def validate_filename_template(cls, value: str) -> str:
        """Require a relative filename generated from the chapter number."""
        try:
            rendered = value.format(chapter=1)
        except (IndexError, KeyError, ValueError) as error:
            raise ValueError("invalid chapter filename template") from error
        path = Path(rendered)
        if path.is_absolute() or len(path.parts) != 1 or path.name != rendered:
            raise ValueError("filename template must render one filename")
        return value


class TranslationConfig(BaseModel):
    """Default translation provider settings for one novel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    default_volume: int | None = Field(default=None, ge=1)


class NovelConfig(BaseModel):
    """Paths and defaults registered for one novel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    bible: Path
    source_directory: Path
    export: ExportConfig
    run_aliases: tuple[str, ...] = ()
    kakuyomu_episode_root: str | None = None
    translation: TranslationConfig

    @field_validator("kakuyomu_episode_root")
    @classmethod
    def validate_episode_root(cls, value: str | None) -> str | None:
        """Require one canonical Kakuyomu episodes root for the work."""
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if _EPISODE_ROOT.fullmatch(normalized) is None:
            raise ValueError(
                "kakuyomu_episode_root must be "
                "https://kakuyomu.jp/works/<work_id>/episodes"
            )
        return normalized


class CatalogConfig(BaseModel):
    """Top-level catalog schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    novels: dict[str, NovelConfig]

    @field_validator("novels")
    @classmethod
    def validate_novel_ids(
        cls, value: dict[str, NovelConfig]
    ) -> dict[str, NovelConfig]:
        """Require unique, stable URL- and CLI-friendly identities."""
        if not value:
            raise ValueError("at least one novel must be registered")
        owners: dict[str, str] = {}
        for novel_id, config in value.items():
            for identity in (novel_id, *config.run_aliases):
                if _NOVEL_ID.fullmatch(identity) is None:
                    raise ValueError(f"invalid novel identifier: {identity}")
                previous = owners.get(identity)
                if previous is not None:
                    raise ValueError(
                        f"novel identifier {identity} is also used by "
                        f"{previous}"
                    )
                owners[identity] = novel_id
        return value


@dataclass(frozen=True, slots=True)
class NovelRegistry:
    """Validated catalog with paths resolved from its YAML location."""

    path: Path
    config: CatalogConfig
    observed_mtime_ns: int | None = None

    def novel(self, novel_id: str) -> NovelConfig:
        """Return one registered novel or a controlled validation error."""
        normalized = novel_id.strip()
        try:
            return self.config.novels[normalized]
        except KeyError as error:
            raise ValidationError(
                f"Novel is not registered: {normalized or '<empty>'}."
            ) from error

    def episode_url(self, novel_id: str, episode_id: str) -> str:
        """Compose one Kakuyomu episode URL from the registered root."""
        root = self.novel(novel_id).kakuyomu_episode_root
        if root is None:
            raise ValidationError(
                f"Novel {novel_id.strip()} has no registered "
                "kakuyomu_episode_root."
            )
        identifier = episode_id.strip()
        if _EPISODE_ID.fullmatch(identifier) is None:
            raise ValidationError("Episode identifier must be numeric.")
        return f"{root}/{identifier}"

    def run_identities(self, novel_id: str) -> frozenset[str]:
        """Return current and historical identities belonging to a novel."""
        novel = self.novel(novel_id)
        return frozenset((novel_id.strip(), *novel.run_aliases))

    def all_run_identities(self) -> frozenset[str]:
        """Return every identity any registered novel may claim."""
        identities: set[str] = set()
        for novel_id, config in self.config.novels.items():
            identities.add(novel_id.strip())
            identities.update(config.run_aliases)
        return frozenset(identities)

    def resolve_path(self, value: Path) -> Path:
        """Resolve a configured path relative to the catalog file."""
        if value.is_absolute():
            return value.resolve()
        return (self.path.parent / value).resolve()

    def source_candidates(self, novel_id: str) -> dict[int, tuple[Path, ...]]:
        """Index canonical chapter source filenames without reading content."""
        directory = self.resolve_path(self.novel(novel_id).source_directory)
        if not directory.exists():
            return {}
        if not directory.is_dir():
            raise ValidationError(
                f"Source directory is not a directory for novel {novel_id}."
            )
        indexed: dict[int, list[Path]] = {}
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise ValidationError(
                f"Source directory could not be read for novel {novel_id}."
            ) from error
        for entry in entries:
            match = _SOURCE_NAME.fullmatch(entry.name)
            if (
                match is not None
                and entry.is_file()
                and not entry.is_symlink()
            ):
                chapter = int(match.group("chapter"))
                indexed.setdefault(chapter, []).append(entry.resolve())
        return {
            chapter: tuple(paths) for chapter, paths in sorted(indexed.items())
        }

    def export_destination(
        self, novel_id: str, chapter: int, site_root: Path | None
    ) -> Path:
        """Resolve the destination inside an explicit site checkout."""
        novel = self.novel(novel_id)
        if site_root is None:
            raise ValidationError(
                "Provide the novels-site checkout root (--site-root)."
            )
        root = site_root.resolve()
        if not root.is_dir():
            raise ValidationError(
                f"The novels-site checkout root is not a directory: {root}."
            )
        filename = novel.export.filename_template.format(chapter=chapter)
        return root / novel.export.directory / filename

    def reload(self) -> NovelRegistry:
        """Refresh this registry when the file moved since it last saw it."""
        try:
            changed = self.path.stat().st_mtime_ns
        except OSError:
            return self
        if self.observed_mtime_ns == changed:
            return self
        fresh = load_catalog(self.path)
        object.__setattr__(self, "config", fresh.config)
        object.__setattr__(self, "observed_mtime_ns", fresh.observed_mtime_ns)
        return self

    def register_novel(
        self,
        novel_id: str,
        config: NovelConfig,
        bible_text: str | None = None,
        source_files: dict[str, str] | None = None,
    ) -> NovelRegistry:
        """Append one novel atomically, then return a reloaded registry."""
        normalized = novel_id.strip()
        if _NOVEL_ID.fullmatch(normalized) is None:
            raise ValidationError(
                f"Invalid novel identifier '{normalized or '<empty>'}'. "
                "Use lowercase letters, digits, and hyphens."
            )
        if normalized in self.all_run_identities():
            raise ValidationError(
                f"Novel is already registered: {normalized}. "
                "Remove it from novels.yaml before registering it again."
            )
        identities = set(self.all_run_identities())
        for identity in (normalized, *config.run_aliases):
            if _NOVEL_ID.fullmatch(identity) is None:
                raise ValidationError(
                    f"Invalid novel identifier '{identity}'. "
                    "Use lowercase letters, digits, and hyphens."
                )
            if identity in identities:
                raise ValidationError(
                    f"Novel identifier {identity} is already registered."
                )
            identities.add(identity)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with FileLock(str(lock_path)):
            current = load_catalog(self.path)
            if normalized in current.all_run_identities():
                raise ValidationError(
                    f"Novel is already registered: {normalized}. "
                    "Remove it from novels.yaml before registering it again."
                )
            for identity in config.run_aliases:
                if identity in current.all_run_identities():
                    raise ValidationError(
                        f"Novel identifier {identity} is already registered."
                    )
            bible_relative = config.bible
            source_relative = config.source_directory
            bible_path = (
                bible_relative
                if bible_relative.is_absolute()
                else self.path.parent / bible_relative
            )
            if bible_text is not None:
                if bible_path.exists():
                    raise ValidationError(
                        f"Bible file already exists: {bible_path}. "
                        "Remove it before registering this novel."
                    )
            else:
                load_bible(bible_path)
            source_directory = (
                source_relative
                if source_relative.is_absolute()
                else self.path.parent / source_relative
            )
            source_directory.mkdir(parents=True, exist_ok=True)
            created: list[Path] = []
            try:
                if bible_text is not None:
                    bible_path.parent.mkdir(parents=True, exist_ok=True)
                    bible_path.write_text(bible_text, encoding="utf-8")
                    created.append(bible_path)
                for name, content in (source_files or {}).items():
                    target = source_directory / name
                    if (
                        target.exists()
                        and target not in created
                        and target != bible_path
                    ):
                        raise ValidationError(
                            f"Source file already exists: {target}. "
                            "Remove it before registering this novel."
                        )
                    target.write_text(content, encoding="utf-8")
                    created.append(target)
                raw_text = self.path.read_text(encoding="utf-8")
                decoded: object = yaml.safe_load(raw_text)
                if not isinstance(decoded, dict):
                    raise ValidationError(
                        "Invalid novel catalog: 'novels' map."
                    )
                raw = cast(dict[Any, Any], decoded)
                if not isinstance(raw.get("novels"), dict):
                    raise ValidationError(
                        "Invalid novel catalog: 'novels' map."
                    )
                novels_map = cast(dict[str, Any], raw["novels"])
                novels_map[normalized] = config.model_dump(mode="json")
                content = yaml.safe_dump(
                    raw, allow_unicode=True, sort_keys=True
                )
                parent = self.path.parent
                parent.mkdir(parents=True, exist_ok=True)
                descriptor: int | None = None
                temporary: Path | None = None
                try:
                    descriptor, name = tempfile.mkstemp(
                        dir=str(parent), prefix=".novels-", suffix=".yaml"
                    )
                    temporary = Path(name)
                    with os.fdopen(
                        descriptor, "w", encoding="utf-8"
                    ) as handle:
                        descriptor = None
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary.replace(self.path)
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                    if temporary is not None and temporary.exists():
                        with suppress(OSError):
                            temporary.unlink()
            except Exception:
                for path in reversed(created):
                    with suppress(OSError):
                        path.unlink()
                raise
        fresh = load_catalog(self.path)
        object.__setattr__(self, "config", fresh.config)
        object.__setattr__(self, "observed_mtime_ns", fresh.observed_mtime_ns)
        return self


def load_catalog(path: Path) -> NovelRegistry:
    """Load and validate a UTF-8 YAML novel catalog."""
    resolved = path.resolve()
    try:
        loaded: object = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        config = CatalogConfig.model_validate(loaded)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
        raise ValidationError(f"Invalid novel catalog: {error}") from error
    try:
        observed = resolved.stat().st_mtime_ns
    except OSError:
        observed = None
    return NovelRegistry(resolved, config, observed)


def ensure_catalog_seeded(seed: Path, target: Path) -> Path:
    """Copy the baked-in catalog to the volume exactly once."""
    resolved = target if target.is_absolute() else Path.cwd() / target
    resolved = resolved.resolve()
    if resolved.exists():
        return resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        seed_text = seed.resolve().read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return resolved
    try:
        with resolved.open("x", encoding="utf-8") as handle:
            handle.write(seed_text)
    except FileExistsError:
        return resolved
    return resolved
