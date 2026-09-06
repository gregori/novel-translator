"""Tests for local and Kakuyomu translation source adapters."""

from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from novel_translator.domain.errors import ValidationError
from novel_translator.domain.translation import SourceDocument
from novel_translator.infrastructure.source import load_bible, read_source


def test_read_source_extracts_only_kakuyomu_episode_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Kakuyomu URL supplies only its episode title
    and body to translation."""
    url = "https://kakuyomu.jp/works/123/episodes/456"
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        text=(
            "\n"
            "        <html><head><title>Episode - Work - Kakuyomu"
            "</title></head><body>\n"
            "          <nav>Navigation must not reach the model.</nav>\n"
            '          <p class="widget-episodeTitle '
            'js-vertical-composition-item">第31話　帰宅、そして……</p>\n'
            '          <div class="widget-episodeBody js-episode-body">\n'
            "            <p>　電車が運休した。</p>\n"
            '            <p class="blank"><br /></p>\n'
            "            <p>　<ruby><rb>勉</rb><rp>（</rp>"
            "<rt>つとむ</rt><rp>）</rp></ruby>は帰宅した。</p>\n"
            "          </div>\n"
            "          <footer>Footer must not reach the model.</footer>\n"
            "        </body></html>\n"
            "        "
        ),
    )
    get = Mock(return_value=response)
    monkeypatch.setattr(httpx, "get", get)
    source = read_source(url)

    assert source == SourceDocument(
        "第31話　帰宅、そして……\n\n　電車が運休した。\n\n"
        "　勉（つとむ）は帰宅した。",
        url,
        "第31話　帰宅、そして……",
    )
    get.assert_called_once_with(url, timeout=120.0, follow_redirects=True)


def test_read_source_rejects_non_kakuyomu_hostname() -> None:
    """A hostname containing Kakuyomu's name
    cannot bypass source validation."""
    with pytest.raises(ValidationError, match="Only Kakuyomu URLs"):
        read_source("https://kakuyomu.jp.example.test/works/123/episodes/456")


def test_read_source_rejects_kakuyomu_page_without_episode_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layout changes fail safely instead of
    sending the whole page to the model."""
    url = "https://kakuyomu.jp/works/123/episodes/456"
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        text="<html><body><nav>Only navigation</nav></body></html>",
    )
    monkeypatch.setattr(httpx, "get", Mock(return_value=response))

    with pytest.raises(ValidationError, match="episode title and body"):
        read_source(url)


def test_gariben_translation_bible_loads() -> None:
    """The published-chapter bible remains valid against the strict schema."""
    bible = load_bible(
        Path("config/gariben-kun-to-uraaka-san.translation-bible.yaml")
    )

    assert bible.version == "chapters-01-26"
