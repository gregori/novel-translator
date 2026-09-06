"""Pure domain rules for translation input, prompts, and segmentation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import ceil
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.models import SegmentPromptManifest
from novel_translator.shared.utils import sha256_text

DEFAULT_SEGMENT_LIMIT = 60_000
PREVIOUS_TRANSLATION_CONTEXT_CHARS = 12_000
RUN_SCHEMA_VERSION = 2
PROMPT_TEMPLATE_VERSION = "v1"
PROMPT_TEMPLATE = (
    "{context}{continuity_context}\n\nSegment {segment_index}:\n"
    "{source_segment}\n\nReturn only English translation."
)


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
    characters: list[BibleCharacter] = Field(
        default_factory=list[BibleCharacter]
    )
    terminology: dict[str, str] = Field(default_factory=dict)
    honorific_rules: list[str] = Field(default_factory=list)
    naming_conventions: list[str] = Field(default_factory=list)
    style_instructions: list[str] = Field(default_factory=list)
    version: str | None = None

    @model_validator(mode="after")
    def validate_canonical_names(self) -> TranslationBible:
        """Reject duplicate names and aliases that collide with
        canonical names."""
        names = [character.name.casefold() for character in self.characters]
        aliases = [
            alias.casefold()
            for character in self.characters
            for alias in character.aliases
        ]
        if len(names) != len(set(names)) or set(names).intersection(aliases):
            raise ValueError(
                "Character canonical names and aliases must be unambiguous."
            )
        return self


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Normalized source text with provenance metadata."""

    content: str
    origin: str
    extracted_title: str | None = None


class TranslatorGateway(Protocol):
    """Port for an interchangeable translation provider."""

    def translate(self, prompt: str) -> str:
        """Translate one prompt and return non-empty text."""
        ...


def build_context(bible: TranslationBible) -> str:
    """Build a stable, bounded context section from a validated bible."""
    lines = [
        f"Title: {bible.title}",
        f"Translate {bible.source_language} to {bible.target_language}.",
    ]
    for character in sorted(
        bible.characters, key=lambda item: item.name.casefold()
    ):
        lines.append(f"Character: {character.name}")
        if character.aliases:
            aliases = ", ".join(sorted(character.aliases, key=str.casefold))
            lines.append(f"Aliases: {aliases}")
    lines.extend(
        f"Term: {source} => {target}"
        for source, target in sorted(bible.terminology.items())
    )
    lines.extend(f"Honorific rule: {item}" for item in bible.honorific_rules)
    lines.extend(
        f"Naming convention: {item}" for item in bible.naming_conventions
    )
    lines.extend(f"Style: {item}" for item in bible.style_instructions)
    return "\n".join(lines)


def estimate_tokens(text: str, language: str) -> int:
    """Estimate tokens when the provider does not expose
    model-tokenizer usage."""
    characters_per_token = 1 if language == "ja" else 4
    return ceil(len(text) / characters_per_token)


def extract_draft_title(draft: str, chapter: int) -> str | None:
    """Extract a matching English episode heading from a raw
    translation draft."""
    pattern = re.compile(
        rf"^(?:Chapter|Episode)\s+{chapter}\s*[:–-]\s*.+$",
        re.IGNORECASE,
    )
    for line in (line.strip() for line in draft.splitlines() if line.strip()):
        candidate = line.lstrip("#").strip()
        for marker in ("**", "__"):
            if candidate.startswith(marker) and candidate.endswith(marker):
                candidate = (
                    candidate.removeprefix(marker).removesuffix(marker).strip()
                )
                break
        if pattern.fullmatch(candidate):
            return candidate
    return None


def segment_text(text: str, limit: int = DEFAULT_SEGMENT_LIMIT) -> list[str]:
    """Pack paragraphs into bounded segments without losing source
    characters."""
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
                raise ValidationError(
                    "A sentence exceeds the configured segment limit."
                )
            if current and len(current) + len(sentence) > limit:
                segments.append(current)
                current = sentence
            else:
                current += sentence
    if current:
        segments.append(current)
    if "".join(segments) != text:
        raise IntegrityError(
            "Segmentation must reconstruct the normalized source exactly."
        )
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
