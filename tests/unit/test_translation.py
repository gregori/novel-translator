"""Tests for translation orchestration and run lifecycle."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from novel_translator.application.translate import (
    StartTranslation,
    StartTranslationInput,
)
from novel_translator.domain.errors import (
    IntegrityError,
    TransientProviderError,
    ValidationError,
)
from novel_translator.domain.models import (
    ChapterIdentity,
    RunStatus,
    SegmentPromptManifest,
)
from novel_translator.domain.translation import (
    PROMPT_TEMPLATE,
    PROMPT_TEMPLATE_VERSION,
    SourceDocument,
    TranslationBible,
    build_context,
    estimate_tokens,
    prompt_manifest_hash,
)
from novel_translator.infrastructure.source import load_bible
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text


def translate(
    workspace: Workspace,
    gateway: Mock,
    identity: ChapterIdentity,
    source: SourceDocument,
    bible: TranslationBible,
    provider: str,
    model: str,
    volume: int | None = None,
    progress: Mock | None = None,
    retry_notice: Mock | None = None,
    segment_limit: int = 60_000,
) -> str:
    """Execute the public translation use case and return its run ID."""
    return (
        StartTranslation(workspace, gateway)
        .execute(
            StartTranslationInput(
                identity,
                source,
                bible,
                provider,
                model,
                volume,
                segment_limit,
                progress,
                retry_notice,
            )
        )
        .run_id
    )


def test_translation_reports_progress_for_each_segment(tmp_path: Path) -> None:
    """Translation reports each segment before it invokes the provider."""
    gateway = Mock()
    gateway.translate.return_value = "translated"
    progress = Mock()
    bible = TranslationBible.model_validate({"title": "Novel"})

    translate(
        Workspace(tmp_path),
        gateway,
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
    """The default limit preserves full-chapter
    context for ordinary chapters."""
    gateway = Mock()
    gateway.translate.return_value = "translated"

    translate(
        Workspace(tmp_path),
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("x" * 5_000, "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    gateway.translate.assert_called_once()


def test_translation_records_completion_metrics(tmp_path: Path) -> None:
    """A completed run stores its finish time,
    duration, and analysis metrics."""
    gateway = Mock()
    gateway.translate.return_value = "English draft"
    workspace = Workspace(tmp_path)
    bible = TranslationBible.model_validate({"title": "Novel"})
    source = SourceDocument("日本語", "test")

    run_id = translate(
        workspace,
        gateway,
        ChapterIdentity("novel", 1),
        source,
        bible,
        "test",
        "test-model",
    )

    run = json.loads(
        (tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8")
    )
    assert run["status"] == "draft_completed"
    assert run["completed_at"]
    assert run["duration_seconds"] >= 0
    assert run["character_counts"] == {"source": 3, "draft": 13}
    assert run["token_estimates"]["source"] == 3
    assert run["token_estimates"]["draft"] == estimate_tokens(
        "English draft", "en"
    )


def test_translation_records_safe_terminal_gateway_failure(
    tmp_path: Path,
) -> None:
    """A definitive gateway failure terminates
    the run without leaking its message."""
    gateway = Mock()
    gateway.translate.side_effect = TransientProviderError(
        "api_key=super-secret"
    )
    workspace = Workspace(tmp_path)

    with pytest.raises(
        ValidationError, match="failed after three attempts"
    ) as raised:
        translate(
            workspace,
            gateway,
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
        translate(
            Workspace(tmp_path),
            gateway,
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
    workspace.runs.save_draft = Mock(  # type: ignore[method-assign]
        side_effect=OSError("api_key=super-secret")
    )
    gateway = Mock()
    gateway.translate.return_value = "translated"

    with pytest.raises(OSError, match="super-secret"):
        translate(
            workspace,
            gateway,
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
    original_record_prompt_segment = workspace.runs.record_prompt_segment

    def fail_on_second_segment(
        run_id: str, segment: SegmentPromptManifest
    ) -> None:
        if segment.segment_index == 2:
            raise OSError("manifest write failed")
        original_record_prompt_segment(run_id, segment)

    workspace.runs.record_prompt_segment = Mock(  # type: ignore[method-assign]
        side_effect=fail_on_second_segment
    )
    gateway = Mock()
    gateway.translate.return_value = "translated"

    with pytest.raises(OSError, match="manifest write failed"):
        translate(
            workspace,
            gateway,
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
    run_id = translate(
        workspace,
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    with pytest.raises(IntegrityError, match="Only a started run"):
        workspace.runs.transition_run(
            run_id, RunStatus.FAILED, datetime.now(UTC)
        )


def test_translation_supplies_previous_passage_when_segmented(
    tmp_path: Path,
) -> None:
    """Later segments receive translated continuity
    context without repeating it."""
    gateway = Mock()
    gateway.translate.side_effect = [
        "First translated passage.",
        "Second translated passage.",
    ]

    translate(
        Workspace(tmp_path),
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("first\nsecond\n", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        segment_limit=7,
    )

    second_prompt = gateway.translate.call_args_list[1].args[0]
    assert (
        "Previous translated passage for continuity only; do not repeat it:"
        in second_prompt
    )
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

    run_id = translate(
        workspace,
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("first\nsecond\n", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        segment_limit=7,
    )

    run = json.loads(
        (tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8")
    )
    manifest = run["segment_manifest"]
    prompts = [call.args[0] for call in gateway.translate.call_args_list]
    assert run["schema_version"] == 2
    assert run["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert run["prompt_template_hash"] == sha256_text(PROMPT_TEMPLATE)
    assert run["context_hash"] == sha256_text(
        build_context(TranslationBible.model_validate({"title": "Novel"}))
    )
    assert [item["segment_index"] for item in manifest] == [1, 2]
    assert [item["rendered_prompt_hash"] for item in manifest] == [
        sha256_text(prompt) for prompt in prompts
    ]
    assert manifest[0]["source_segment_hash"] == sha256_text("first\n")
    assert manifest[0]["continuity_context_hash"] == sha256_text("")
    assert manifest[1]["continuity_context_hash"] != sha256_text("")
    assert manifest[0]["gateway_calls"] == [
        {"attempt": 1, "rendered_prompt_hash": sha256_text(prompts[0])}
    ]
    assert run["prompt_hash"] == prompt_manifest_hash(manifest)


def test_gateway_retries_are_all_associated_with_the_prompt(
    tmp_path: Path,
) -> None:
    """Repeated calls remain auditable even though
    their prompt is identical."""
    gateway = Mock()
    gateway.translate.side_effect = [
        TransientProviderError("offline"),
        "translated",
    ]

    run_id = translate(
        Workspace(tmp_path),
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
    )

    run = json.loads(
        (tmp_path / "runs" / run_id / "run.json").read_text(encoding="utf-8")
    )
    calls = run["segment_manifest"][0]["gateway_calls"]
    assert [call["attempt"] for call in calls] == [1, 2]
    assert len({call["rendered_prompt_hash"] for call in calls}) == 1


def test_translation_reports_transport_errors_before_retrying(
    tmp_path: Path,
) -> None:
    """Transport failures are exposed before the next attempt begins."""
    gateway = Mock()
    gateway.translate.side_effect = [
        TransientProviderError("offline"),
        "translated",
    ]
    retry_notice = Mock()

    translate(
        Workspace(tmp_path),
        gateway,
        ChapterIdentity("novel", 1),
        SourceDocument("source", "test"),
        TranslationBible.model_validate({"title": "Novel"}),
        "test",
        "test-model",
        retry_notice=retry_notice,
    )

    error = retry_notice.call_args.args[3]
    assert isinstance(error, TransientProviderError)
    assert str(error) == "offline"


def test_example_bible_fields_are_rendered_in_translation_prompt(
    tmp_path: Path,
) -> None:
    """Every functional field in the example bible
    reaches the provider prompt."""
    bible = load_bible(Path("config/translation-bible.example.yaml"))
    gateway = Mock()
    gateway.translate.return_value = "translated"

    translate(
        Workspace(tmp_path),
        gateway,
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
