"""Unit and property tests for the pure workflow rules."""

import json
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from novel_translator.core import (
    ApprovalEvent,
    OpenAICompatibleGateway,
    SourceDocument,
    TranslationBible,
    TranslationService,
    Workspace,
    approve,
    build_context,
    estimate_tokens,
    export_draft,
    extract_draft_title,
    load_bible,
    segment_text,
)
from novel_translator.shared.errors import ApprovalRequired, ValidationError
from novel_translator.shared.models import ChapterIdentity
from novel_translator.shared.utils import json_dumps, sha256_text


@given(st.lists(st.text(max_size=20), min_size=1, max_size=20).map("\n".join))
def test_segment_text_round_trips_source(text: str) -> None:
    """Segmentation must preserve every source character."""
    assert "".join(segment_text(text, 50)) == text


def test_segment_text_packs_short_paragraphs() -> None:
    """Short paragraphs share a request until the segment limit is reached."""
    assert segment_text("one\ntwo\nthree\n", 8) == ["one\ntwo\n", "three\n"]


def test_translation_reports_progress_for_each_segment(tmp_path: Path) -> None:
    """Translation reports each segment before it invokes the provider."""
    gateway = Mock()
    gateway.translate.return_value = "translated"
    progress = Mock()
    service = TranslationService(Workspace(tmp_path), gateway)
    bible = TranslationBible.model_validate({"title": "Novel"})

    service.translate(
        ChapterIdentity("novel", 1),
        SourceDocument("one\ntwo\n", "test"),
        bible,
        "test",
        "test-model",
        progress=progress,
    )

    progress.assert_called_once_with(1, 1, 1)


def test_translation_sends_a_short_chapter_in_one_request(tmp_path: Path) -> None:
    """The default limit preserves full-chapter context for ordinary chapters."""
    gateway = Mock()
    gateway.translate.return_value = "translated"
    service = TranslationService(Workspace(tmp_path), gateway)

    service.translate(
        ChapterIdentity("novel", 1),
        SourceDocument("x" * 5_000, "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    gateway.translate.assert_called_once()


def test_translation_records_completion_metrics(tmp_path: Path) -> None:
    """A completed run stores its finish time, duration, and analysis metrics."""
    gateway = Mock()
    gateway.translate.return_value = "English draft"
    workspace = Workspace(tmp_path)
    bible = TranslationBible.model_validate({"title": "Novel"})
    source = SourceDocument("日本語", "test")

    run_id = TranslationService(workspace, gateway).translate(
        ChapterIdentity("novel", 1), source, bible, "test", "test-model"
    )

    run = json.loads((tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "draft_completed"
    assert run["completed_at"]
    assert run["duration_seconds"] >= 0
    assert run["character_counts"] == {"source": 3, "draft": 13}
    assert run["token_estimates"]["source"] == 3
    assert run["token_estimates"]["draft"] == estimate_tokens("English draft", "en")


def test_extract_draft_title_ignores_unmatched_heading() -> None:
    """A misleading opening line cannot override the matching episode title."""
    draft = "Chapter 3\n\nEpisode 27: A Rainy Day\n\nBody"

    assert extract_draft_title(draft, 27) == "Episode 27: A Rainy Day"


def test_export_uses_an_inferred_draft_title(tmp_path: Path) -> None:
    """Export uses a matching draft heading when no explicit title is supplied."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Episode 7: Rainy Day\n\nDraft", encoding="utf-8")
    (run_dir / "run.json").write_text('{"identity": {"chapter": 7}}', encoding="utf-8")
    approve(workspace, "run")

    exported = export_draft(workspace, "run", tmp_path / "out.md")

    assert 'chapterTitle: "Episode 7: Rainy Day"' in exported.read_text(encoding="utf-8")


def test_translation_supplies_previous_passage_when_segmented(tmp_path: Path) -> None:
    """Later segments receive translated continuity context without repeating it."""
    gateway = Mock()
    gateway.translate.side_effect = ["First translated passage.", "Second translated passage."]
    service = TranslationService(Workspace(tmp_path), gateway)

    service.translate(
        ChapterIdentity("novel", 1),
        SourceDocument("first\nsecond\n", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        segment_limit=7,
    )

    second_prompt = gateway.translate.call_args_list[1].args[0]
    assert "Previous translated passage for continuity only; do not repeat it:" in second_prompt
    assert "First translated passage." in second_prompt


def test_translation_reports_transport_errors_before_retrying(tmp_path: Path) -> None:
    """Transport failures are exposed before the next attempt begins."""
    gateway = Mock()
    gateway.translate.side_effect = [httpx.ConnectError("offline"), "translated"]
    retry_notice = Mock()
    service = TranslationService(Workspace(tmp_path), gateway)

    service.translate(
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        retry_notice=retry_notice,
    )

    error = retry_notice.call_args.args[3]
    assert isinstance(error, httpx.ConnectError)
    assert str(error) == "offline"


def test_gateway_enforces_a_total_request_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider that keeps sending data cannot block the CLI indefinitely."""
    release_request = Event()

    def delayed_post(*_: object, **__: object) -> httpx.Response:
        release_request.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "translated"}}]})

    monkeypatch.setattr("novel_translator.core.httpx.post", delayed_post)
    gateway = OpenAICompatibleGateway("https://example.test/v1", "model", "key", timeout_seconds=0.01)

    try:
        with pytest.raises(httpx.ReadTimeout, match="did not complete"):
            gateway.translate("prompt")
    finally:
        release_request.set()


def test_gateway_reports_safe_provider_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider status errors retain a useful, bounded diagnostic message."""

    def forbidden_post(*_: object, **__: object) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid API key"}},
            headers={"x-request-id": "request-123"},
            request=request,
        )

    monkeypatch.setattr("novel_translator.core.httpx.post", forbidden_post)
    gateway = OpenAICompatibleGateway("https://example.test/v1", "model", "key")

    with pytest.raises(ValidationError, match="HTTP 401: Invalid API key. Request ID: request-123"):
        gateway.translate("prompt")


def test_bible_rejects_alias_matching_canonical_name() -> None:
    """Bible identifiers cannot be ambiguous."""
    with pytest.raises(ValueError):
        TranslationBible.model_validate({"title": "Novel", "characters": [{"name": "A", "aliases": ["a"]}]})


def test_gariben_translation_bible_loads() -> None:
    """The published-chapter bible remains valid against the strict schema."""
    bible = load_bible(Path("config/gariben-kun-to-uraaka-san.translation-bible.yaml"))

    assert bible.version == "chapters-01-26"


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


def test_example_bible_fields_are_rendered_in_translation_prompt(tmp_path: Path) -> None:
    """Every functional field in the example bible reaches the provider prompt."""
    bible = load_bible(Path("config/translation-bible.example.yaml"))
    gateway = Mock()
    gateway.translate.return_value = "translated"

    TranslationService(Workspace(tmp_path), gateway).translate(
        ChapterIdentity("example", 1),
        SourceDocument("source", "test"),
        bible,
        "test",
        "test-model",
    )

    prompt = gateway.translate.call_args.args[0]
    assert "Title: Example Novel" in prompt
    assert "Translate ja to en." in prompt
    assert "Character: Haru\nAliases: Haru-kun" in prompt
    assert "Term: 魔法 => magic" in prompt
    assert "Honorific rule: Preserve meaningful honorifics." in prompt
    assert "Naming convention: Use canonical character names." in prompt
    assert "Style: Use natural English prose." in prompt


def test_workspace_requires_current_approval_for_export(tmp_path: Path) -> None:
    """Export does not occur before an exact hash approval."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    with pytest.raises(ApprovalRequired):
        export_draft(workspace, "run", tmp_path / "out.md", "Title")


def test_latest_matching_approval_event_controls_eligibility(tmp_path: Path) -> None:
    """The latest append-only event wins for exactly one draft hash."""
    workspace = Workspace(tmp_path)
    event = ApprovalEvent("run", sha256_text("Draft"), True, "2026-01-01T00:00:00+00:00")
    workspace.append_approval(event)
    workspace.append_approval(ApprovalEvent("run", event.draft_hash, False, "2026-01-02T00:00:00+00:00"))
    assert not workspace.is_approved("run", event.draft_hash)


def test_json_serialization_redacts_api_key() -> None:
    """Serializable output never contains secrets."""
    assert "visible" not in json_dumps({"api_key": "visible"})


def test_workspace_rejects_paths_outside_root(tmp_path: Path) -> None:
    """Workspace adapter prevents path traversal."""
    with pytest.raises(ValidationError):
        Workspace(tmp_path)._safe(Path("..") / "escape")


def test_export_uses_volume_persisted_in_run_metadata(tmp_path: Path) -> None:
    """Export preserves the optional run volume in the Markdown front matter."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "run.json").write_text('{"volume": 2}', encoding="utf-8")
    approve(workspace, "run")

    exported = export_draft(
        workspace,
        "run",
        tmp_path / "chapter.md",
        "Chapter 1",
        publish_date="2026-08-24",
    )

    assert 'chapterTitle: "Chapter 1"' in exported.read_text(encoding="utf-8")
    assert "publishDate: 2026-08-24" in exported.read_text(encoding="utf-8")
    assert "volume: 2" in exported.read_text(encoding="utf-8")
