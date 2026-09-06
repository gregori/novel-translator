"""Tests for pure translation domain rules."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from novel_translator.domain.translation import (
    TranslationBible,
    build_context,
    extract_draft_title,
    render_translation_prompt,
    segment_text,
)
from novel_translator.shared.utils import sha256_text


@given(st.lists(st.text(max_size=20), min_size=1, max_size=20).map("\n".join))
def test_segment_text_round_trips_source(text: str) -> None:
    """Segmentation must preserve every source character."""
    assert "".join(segment_text(text, 50)) == text


def test_segment_text_packs_short_paragraphs() -> None:
    """Short paragraphs share a request until the segment limit is reached."""
    assert segment_text("one\ntwo\nthree\n", 8) == ["one\ntwo\n", "three\n"]


def test_extract_draft_title_ignores_unmatched_heading() -> None:
    """A misleading opening line cannot override the matching episode title."""
    draft = "Chapter 3\n\nEpisode 27: A Rainy Day\n\nBody"

    assert extract_draft_title(draft, 27) == "Episode 27: A Rainy Day"


def test_rendered_prompt_hash_is_deterministic_and_sensitive() -> None:
    """Template, context, source, index, and
    continuity affect prompt hashes."""
    inputs = ("context", "continuity", 1, "source")
    baseline = render_translation_prompt(*inputs)
    assert sha256_text(render_translation_prompt(*inputs)) == sha256_text(
        baseline
    )
    variants = [
        render_translation_prompt("changed", *inputs[1:]),
        render_translation_prompt(inputs[0], "changed", *inputs[2:]),
        render_translation_prompt(*inputs[:2], 2, inputs[3]),
        render_translation_prompt(*inputs[:3], "changed"),
        render_translation_prompt(*inputs, template="changed {context}"),
    ]
    assert all(
        sha256_text(variant) != sha256_text(baseline) for variant in variants
    )


def test_bible_rejects_alias_matching_canonical_name() -> None:
    """Bible identifiers cannot be ambiguous."""
    with pytest.raises(ValueError):
        TranslationBible.model_validate(
            {"title": "Novel", "characters": [{"name": "A", "aliases": ["a"]}]}
        )


def test_context_is_deterministic() -> None:
    """Reference-data ordering does not change the rendered context."""
    first = TranslationBible.model_validate(
        {
            "title": "Novel",
            "characters": [
                {"name": "Yuki", "aliases": ["Yuki-chan", "Snow"]},
                {"name": "Akira", "aliases": ["Aki"]},
            ],
            "terminology": {"B": "b", "A": "a"},
        }
    )
    second = TranslationBible.model_validate(
        {
            "title": "Novel",
            "characters": [
                {"name": "Akira", "aliases": ["Aki"]},
                {"name": "Yuki", "aliases": ["Snow", "Yuki-chan"]},
            ],
            "terminology": {"A": "a", "B": "b"},
        }
    )

    assert build_context(first) == build_context(second)
