"""Filesystem and Kakuyomu HTTP adapters for translation inputs."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

from novel_translator.domain.errors import ValidationError
from novel_translator.domain.translation import (
    SourceDocument,
    TranslationBible,
)


class KakuyomuEpisodeParser(HTMLParser):
    """Extract the episode title and body from a Kakuyomu HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self._title_depth = 0
        self._body_depth = 0
        self._paragraph_depth = 0
        self._title_parts: list[str] = []
        self._paragraph_parts: list[str] = []
        self._paragraphs: list[str] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        """Return the class tokens from one start tag."""
        class_value = dict(attrs).get("class") or ""
        return set(class_value.split())

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Enter the selected title, body, and body paragraphs."""
        classes = self._classes(attrs)
        if self._body_depth:
            if tag == "br":
                if self._paragraph_depth:
                    self._paragraph_parts.append("\n")
                return
            self._body_depth += 1
            if tag == "p" and not self._paragraph_depth:
                self._paragraph_depth = self._body_depth
                self._paragraph_parts = []
            return
        if "js-episode-body" in classes:
            self._body_depth = 1
            return
        if self._title_depth:
            self._title_depth += 1
        elif "widget-episodeTitle" in classes:
            self._title_depth = 1

    def handle_endtag(self, tag: str) -> None:
        """Leave selected elements and finish body paragraphs."""
        if tag == "br":
            return
        if self._body_depth:
            if tag == "p" and self._paragraph_depth == self._body_depth:
                paragraph = "".join(self._paragraph_parts).rstrip("\r\n")
                self._paragraphs.append(paragraph if paragraph.strip() else "")
                self._paragraph_depth = 0
                self._paragraph_parts = []
            self._body_depth -= 1
        elif self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        """Collect text only from the selected episode elements."""
        if self._body_depth and self._paragraph_depth:
            self._paragraph_parts.append(data)
        elif self._title_depth:
            self._title_parts.append(data)

    def title(self) -> str | None:
        """Return the non-empty episode title when present."""
        candidate = "".join(self._title_parts)
        return candidate.strip() or None

    def body(self) -> str | None:
        """Return the episode paragraphs with their blank-line structure."""
        candidate = "\n".join(self._paragraphs).strip("\r\n")
        return candidate if candidate.strip() else None


def load_bible(path: Path) -> TranslationBible:
    """Load and validate a UTF-8 YAML translation bible."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TranslationBible.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ValidationError(f"Invalid translation bible: {error}") from error


def read_revision_input(path: Path) -> str:
    """Read non-empty UTF-8 revision content without changing its bytes."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError("Revision input must be valid UTF-8.") from error
    except OSError as error:
        raise ValidationError("Revision input could not be read.") from error
    if not content.strip():
        raise ValidationError("Revision input must not be empty.")
    return content


def read_source(value: str) -> SourceDocument:
    """Read a local UTF-8 file or supported Kakuyomu URL."""
    if value.startswith(("http://", "https://")):
        if urlsplit(value).hostname != "kakuyomu.jp":
            raise ValidationError("Only Kakuyomu URLs are supported in v1.")
        try:
            response = httpx.get(value, timeout=120.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ValidationError(
                f"Could not download Kakuyomu source: {type(error).__name__}."
            ) from error
        parser = KakuyomuEpisodeParser()
        parser.feed(response.text)
        parser.close()
        title = parser.title()
        body = parser.body()
        if title is None or body is None:
            raise ValidationError(
                "Kakuyomu page did not contain an episode title and body."
            )
        return SourceDocument(f"{title}\n\n{body}", value, title)
    path = Path(value)
    if not path.is_file():
        raise ValidationError(
            "Source must be a readable file or Kakuyomu URL."
        )
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValidationError("Source file must be valid UTF-8.") from error
    if not text:
        raise ValidationError("Source file must not be empty.")
    return SourceDocument(text, str(path.resolve()))
