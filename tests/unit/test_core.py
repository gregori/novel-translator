"""Unit and property tests for the pure workflow rules."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from novel_translator.core import (
    PROMPT_TEMPLATE,
    PROMPT_TEMPLATE_VERSION,
    ApprovalEvent,
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
    prompt_manifest_hash,
    read_source,
    render_translation_prompt,
    segment_text,
)
from novel_translator.shared.errors import (
    ApprovalRequired,
    IntegrityError,
    ValidationError,
)
from novel_translator.shared.models import (
    ChapterIdentity,
    RunStatus,
    SegmentPromptManifest,
)
from novel_translator.shared.utils import json_dumps, sha256_text

VALID_RUN_ID = "0" * 32


def test_read_source_extracts_only_kakuyomu_episode_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Kakuyomu URL supplies only its episode title and body to translation."""
    url = "https://kakuyomu.jp/works/123/episodes/456"
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        text="""
        <html><head><title>Episode - Work - Kakuyomu</title></head><body>
          <nav>Navigation must not reach the model.</nav>
          <p class="widget-episodeTitle js-vertical-composition-item">第31話　帰宅、そして……</p>
          <div class="widget-episodeBody js-episode-body">
            <p>　電車が運休した。</p>
            <p class="blank"><br /></p>
            <p>　<ruby><rb>勉</rb><rp>（</rp><rt>つとむ</rt><rp>）</rp></ruby>は帰宅した。</p>
          </div>
          <footer>Footer must not reach the model.</footer>
        </body></html>
        """,
    )
    get = Mock(return_value=response)
    monkeypatch.setattr(httpx, "get", get)

    source = read_source(url)

    assert source == SourceDocument(
        "第31話　帰宅、そして……\n\n　電車が運休した。\n\n　勉（つとむ）は帰宅した。",
        url,
        "第31話　帰宅、そして……",
    )
    get.assert_called_once_with(url, timeout=120.0, follow_redirects=True)


def test_read_source_rejects_non_kakuyomu_hostname() -> None:
    """A hostname containing Kakuyomu's name cannot bypass source validation."""
    with pytest.raises(ValidationError, match="Only Kakuyomu URLs"):
        read_source("https://kakuyomu.jp.example.test/works/123/episodes/456")


def test_read_source_rejects_kakuyomu_page_without_episode_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layout changes fail safely instead of sending the whole page to the model."""
    url = "https://kakuyomu.jp/works/123/episodes/456"
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        text="<html><body><nav>Only navigation</nav></body></html>",
    )
    monkeypatch.setattr(httpx, "get", Mock(return_value=response))

    with pytest.raises(ValidationError, match="episode title and body"):
        read_source(url)


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


def test_translation_sends_a_short_chapter_in_one_request(
    tmp_path: Path,
) -> None:
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


def test_translation_records_safe_terminal_gateway_failure(
    tmp_path: Path,
) -> None:
    """A definitive gateway failure terminates the run without leaking its message."""
    gateway = Mock()
    gateway.translate.side_effect = httpx.ConnectError("api_key=super-secret")
    workspace = Workspace(tmp_path)

    with pytest.raises(ValidationError, match="failed after three attempts") as raised:
        TranslationService(workspace, gateway).translate(
            ChapterIdentity("novel", 1),
            SourceDocument("source", "test"),
            TranslationBible.model_validate({"title": "Novel"}),
            "test",
            "test-model",
        )

    run_path = next((tmp_path / "runs").glob("*/run.json"))
    serialized = run_path.read_text(encoding="utf-8")
    run = json.loads(serialized)
    assert run["status"] == "failed"
    assert run["completed_at"]
    assert run["error"] == {
        "attempt": 3,
        "phase": "translation",
        "segment": 1,
        "timestamp": run["completed_at"],
        "type": "ValidationError",
    }
    assert "super-secret" not in serialized
    assert "super-secret" not in str(raised.value)


def test_translation_records_user_interruption(tmp_path: Path) -> None:
    """A keyboard interruption terminates the run as interrupted."""
    gateway = Mock()
    gateway.translate.side_effect = KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        TranslationService(Workspace(tmp_path), gateway).translate(
            ChapterIdentity("novel", 1),
            SourceDocument("source", "test"),
            TranslationBible.model_validate({"title": "Novel"}),
            "test",
            "test-model",
        )

    run_path = next((tmp_path / "runs").glob("*/run.json"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "interrupted"
    assert run["error"]["type"] == "KeyboardInterrupt"
    assert run["error"]["phase"] == "translation"


def test_translation_records_failure_during_draft_persistence(
    tmp_path: Path,
) -> None:
    """A draft write failure leaves an auditable failed run."""
    workspace = Workspace(tmp_path)
    workspace.save_draft = Mock(side_effect=OSError("api_key=super-secret"))  # type: ignore[method-assign]
    gateway = Mock()
    gateway.translate.return_value = "translated"

    with pytest.raises(OSError, match="super-secret"):
        TranslationService(workspace, gateway).translate(
            ChapterIdentity("novel", 1),
            SourceDocument("source", "test"),
            TranslationBible.model_validate({"title": "Novel"}),
            "test",
            "test-model",
        )

    run_path = next((tmp_path / "runs").glob("*/run.json"))
    serialized = run_path.read_text(encoding="utf-8")
    run = json.loads(serialized)
    assert run["status"] == "failed"
    assert run["error"]["phase"] == "draft_persistence"
    assert "segment" not in run["error"]
    assert "attempt" not in run["error"]
    assert "super-secret" not in serialized


def test_new_segment_clears_attempt_before_recording_prompt(
    tmp_path: Path,
) -> None:
    """A pre-attempt failure cannot inherit the prior segment's attempt."""
    workspace = Workspace(tmp_path)
    original_record_prompt_segment = workspace.record_prompt_segment

    def fail_on_second_segment(run_id: str, segment: SegmentPromptManifest) -> None:
        if segment.segment_index == 2:
            raise OSError("manifest write failed")
        original_record_prompt_segment(run_id, segment)

    workspace.record_prompt_segment = Mock(  # type: ignore[method-assign]
        side_effect=fail_on_second_segment
    )
    gateway = Mock()
    gateway.translate.return_value = "translated"

    with pytest.raises(OSError, match="manifest write failed"):
        TranslationService(workspace, gateway).translate(
            ChapterIdentity("novel", 1),
            SourceDocument("first\nsecond\n", "test"),
            TranslationBible.model_validate({"title": "Novel"}),
            "test",
            "test-model",
            segment_limit=7,
        )

    run_path = next((tmp_path / "runs").glob("*/run.json"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert gateway.translate.call_count == 1
    assert run["error"]["segment"] == 2
    assert "attempt" not in run["error"]


def test_workspace_rejects_a_second_terminal_transition(
    tmp_path: Path,
) -> None:
    """Central lifecycle rules prevent a terminal run from changing again."""
    gateway = Mock()
    gateway.translate.return_value = "translated"
    workspace = Workspace(tmp_path)
    run_id = TranslationService(workspace, gateway).translate(
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    with pytest.raises(IntegrityError, match="Only a started run"):
        workspace.transition_run(run_id, RunStatus.FAILED, datetime.now(UTC))


def test_extract_draft_title_ignores_unmatched_heading() -> None:
    """A misleading opening line cannot override the matching episode title."""
    draft = "Chapter 3\n\nEpisode 27: A Rainy Day\n\nBody"

    assert extract_draft_title(draft, 27) == "Episode 27: A Rainy Day"


def test_export_uses_an_inferred_draft_title(tmp_path: Path) -> None:
    """Export uses a matching draft heading when no explicit title is supplied."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Episode 7: Rainy Day\n\nDraft", encoding="utf-8")
    (run_dir / "run.json").write_text('{"identity": {"chapter": 7}}', encoding="utf-8")
    approve(workspace, VALID_RUN_ID)

    exported = export_draft(workspace, VALID_RUN_ID, tmp_path / "out.md")

    assert 'chapterTitle: "Episode 7: Rainy Day"' in exported.read_text(encoding="utf-8")


def test_translation_supplies_previous_passage_when_segmented(
    tmp_path: Path,
) -> None:
    """Later segments receive translated continuity context without repeating it."""
    gateway = Mock()
    gateway.translate.side_effect = [
        "First translated passage.",
        "Second translated passage.",
    ]
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


def test_translation_records_exact_ordered_prompt_provenance(
    tmp_path: Path,
) -> None:
    """Every gateway call is linked to its exact UTF-8 rendered prompt."""
    gateway = Mock()
    gateway.translate.side_effect = [
        "First translation.",
        "Second translation.",
    ]
    workspace = Workspace(tmp_path)

    run_id = TranslationService(workspace, gateway).translate(
        ChapterIdentity("novel", 1),
        SourceDocument("first\nsecond\n", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        segment_limit=7,
    )

    run = json.loads((tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
    manifest = run["segment_manifest"]
    prompts = [call.args[0] for call in gateway.translate.call_args_list]
    assert run["schema_version"] == 2
    assert run["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert run["prompt_template_hash"] == sha256_text(PROMPT_TEMPLATE)
    assert run["context_hash"] == sha256_text(build_context(TranslationBible.model_validate({"title": "Novel"})))
    assert [item["segment_index"] for item in manifest] == [1, 2]
    assert [item["rendered_prompt_hash"] for item in manifest] == [sha256_text(prompt) for prompt in prompts]
    assert manifest[0]["source_segment_hash"] == sha256_text("first\n")
    assert manifest[0]["continuity_context_hash"] == sha256_text("")
    assert manifest[1]["continuity_context_hash"] != sha256_text("")
    assert manifest[0]["gateway_calls"] == [{"attempt": 1, "rendered_prompt_hash": sha256_text(prompts[0])}]
    assert run["prompt_hash"] == prompt_manifest_hash(manifest)


def test_rendered_prompt_hash_is_deterministic_and_sensitive() -> None:
    """Template, context, source, index, and continuity affect prompt hashes."""
    inputs = ("context", "continuity", 1, "source")
    baseline = render_translation_prompt(*inputs)
    assert sha256_text(render_translation_prompt(*inputs)) == sha256_text(baseline)
    variants = [
        render_translation_prompt("changed", *inputs[1:]),
        render_translation_prompt(inputs[0], "changed", *inputs[2:]),
        render_translation_prompt(*inputs[:2], 2, inputs[3]),
        render_translation_prompt(*inputs[:3], "changed"),
        render_translation_prompt(*inputs, template="changed {context}"),
    ]
    assert all(sha256_text(variant) != sha256_text(baseline) for variant in variants)


def test_gateway_retries_are_all_associated_with_the_prompt(
    tmp_path: Path,
) -> None:
    """Repeated calls remain auditable even though their prompt is identical."""
    gateway = Mock()
    gateway.translate.side_effect = [
        httpx.ConnectError("offline"),
        "translated",
    ]

    run_id = TranslationService(Workspace(tmp_path), gateway).translate(
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    run = json.loads((tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
    calls = run["segment_manifest"][0]["gateway_calls"]
    assert [call["attempt"] for call in calls] == [1, 2]
    assert len({call["rendered_prompt_hash"] for call in calls}) == 1


def test_translation_reports_transport_errors_before_retrying(
    tmp_path: Path,
) -> None:
    """Transport failures are exposed before the next attempt begins."""
    gateway = Mock()
    gateway.translate.side_effect = [
        httpx.ConnectError("offline"),
        "translated",
    ]
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


def test_example_bible_fields_are_rendered_in_translation_prompt(
    tmp_path: Path,
) -> None:
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


def test_workspace_requires_current_approval_for_export(
    tmp_path: Path,
) -> None:
    """Export does not occur before an exact hash approval."""
    workspace = Workspace(tmp_path)
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    with pytest.raises(ApprovalRequired):
        export_draft(workspace, VALID_RUN_ID, tmp_path / "out.md", "Title")


def test_latest_matching_approval_event_controls_eligibility(
    tmp_path: Path,
) -> None:
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
    run_dir = tmp_path / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text("Draft", encoding="utf-8")
    (run_dir / "run.json").write_text('{"volume": 2}', encoding="utf-8")
    approve(workspace, VALID_RUN_ID)

    exported = export_draft(
        workspace,
        VALID_RUN_ID,
        tmp_path / "chapter.md",
        "Chapter 1",
        publish_date="2026-08-24",
    )

    assert 'chapterTitle: "Chapter 1"' in exported.read_text(encoding="utf-8")
    assert "publishDate: 2026-08-24" in exported.read_text(encoding="utf-8")
    assert "volume: 2" in exported.read_text(encoding="utf-8")
