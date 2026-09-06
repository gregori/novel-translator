"""Typed translation preparation resolving catalog defaults."""

from dataclasses import dataclass
from pathlib import Path

from novel_translator.application.catalog import select_candidate
from novel_translator.domain.errors import ValidationError
from novel_translator.infrastructure.catalog import NovelRegistry


@dataclass(frozen=True, slots=True)
class PrepareTranslationInput:
    """Chapter selection plus explicit overrides for every default."""

    novel: str
    chapter: int
    source: str | None = None
    episode: str | None = None
    source_choice: int | None = None
    bible: Path | None = None
    provider: str | None = None
    model: str | None = None
    volume: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedTranslation:
    """Fully resolved typed inputs for one new translation run."""

    novel: str
    chapter: int
    source: str
    bible: Path
    provider: str
    model: str
    volume: int | None


class PrepareTranslation:
    """Resolve catalog defaults and explicit overrides into typed inputs."""

    def __init__(self, registry: NovelRegistry) -> None:
        self._registry = registry

    def execute(self, request: PrepareTranslationInput) -> PreparedTranslation:
        """Apply override precedence without touching the workspace."""
        if request.chapter < 1:
            raise ValidationError("Chapter must be positive.")
        novel = request.novel.strip()
        config = self._registry.novel(novel)
        return PreparedTranslation(
            novel=novel,
            chapter=request.chapter,
            source=self._source(novel, request),
            bible=(
                request.bible
                if request.bible is not None
                else self._registry.resolve_path(config.bible)
            ),
            provider=request.provider or config.translation.provider,
            model=request.model or config.translation.model,
            volume=(
                request.volume
                if request.volume is not None
                else config.translation.default_volume
            ),
        )

    def _source(self, novel: str, request: PrepareTranslationInput) -> str:
        """Resolve one source; explicit input ignores configured ambiguity."""
        if request.source is not None:
            if request.episode is not None:
                raise ValidationError(
                    "Use either --source or --episode, not both."
                )
            return request.source
        if request.episode is not None:
            return self._registry.episode_url(novel, request.episode)
        sources = self._registry.source_candidates(novel).get(
            request.chapter, ()
        )
        selected = select_candidate(sources, request.source_choice, "source")
        if selected is None:
            raise ValidationError(
                "The chapter has no configured source; provide --source."
            )
        return str(selected)
