"""Offline integration tests for the complete CLI and provider boundary."""

import json
from pathlib import Path
from threading import Event
from typing import Any

import httpx2
from openai import DefaultHttpxClient, OpenAI
from typer.testing import CliRunner, Result

from novel_translator.cli.app import app


def completion_response() -> httpx2.Response:
    """Return a complete draft from an in-process OpenAI-compatible endpoint."""
    return httpx2.Response(
        200,
        json={
            "id": "completion-1",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Episode 1: Test\n\nTranslated body.",
                    },
                }
            ],
        },
    )


def install_mock_provider(monkeypatch: Any, transport: httpx2.BaseTransport) -> None:
    """Route the production SDK through an in-process transport."""

    def build_client(**_: object) -> OpenAI:
        return OpenAI(
            api_key="test-secret",
            base_url="https://provider.test/v1",
            max_retries=0,
            http_client=DefaultHttpxClient(transport=transport),
        )

    monkeypatch.setattr("novel_translator.providers.OpenAI", build_client)


def translation_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create source, bible, and workspace paths for one CLI translation."""
    source = tmp_path / "source.txt"
    source.write_text("日本語", encoding="utf-8")
    bible = tmp_path / "bible.yaml"
    bible.write_text("title: Test Novel\n", encoding="utf-8")
    return source, bible, tmp_path / "workspace"


def invoke_translate(
    runner: CliRunner,
    source: Path,
    bible: Path,
    workspace: Path,
    *extra_args: str,
) -> Result:
    """Invoke translate with deterministic local provider settings."""
    return runner.invoke(
        app,
        [
            "translate",
            "--novel",
            "test-novel",
            "--chapter",
            "1",
            "--source",
            str(source),
            "--bible",
            str(bible),
            "--workspace",
            str(workspace),
            "--base-url",
            "https://provider.test/v1",
            "--model",
            "test-model",
            "--api-key",
            "test-secret",
            "--json",
            *extra_args,
        ],
    )


def test_complete_translate_approve_export_inspect_workflow(tmp_path: Path, monkeypatch: Any) -> None:
    """The complete CLI workflow runs against an offline provider transport."""
    captured_requests: list[httpx2.Request] = []

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        return completion_response()

    install_mock_provider(monkeypatch, httpx2.MockTransport(handle_request))
    source, bible, workspace = translation_inputs(tmp_path)
    runner = CliRunner()

    translated = invoke_translate(runner, source, bible, workspace)
    assert translated.exit_code == 0
    run_id = json.loads(translated.stdout)["run_id"]

    inspected = runner.invoke(app, ["inspect", run_id, "--workspace", str(workspace)])
    approved = runner.invoke(app, ["approve", run_id, "--workspace", str(workspace)])
    destination = tmp_path / "exported.md"
    exported = runner.invoke(
        app,
        [
            "export",
            run_id,
            "--workspace",
            str(workspace),
            "--destination",
            str(destination),
            "--publish-date",
            "2026-09-02",
        ],
    )
    inspected_with_draft = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--workspace",
            str(workspace),
            "--include-draft",
        ],
    )

    assert len(captured_requests) == 1
    assert json.loads(inspected.stdout)["status"] == "draft_completed"
    assert approved.exit_code == 0
    assert exported.exit_code == 0
    assert "Translated body." in destination.read_text(encoding="utf-8")
    assert json.loads(inspected_with_draft.stdout)["draft"].endswith("Translated body.")


def test_translate_reports_provider_http_error(tmp_path: Path, monkeypatch: Any) -> None:
    """An HTTP provider failure remains controlled at the CLI boundary."""
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(503, json={"error": {"message": "Provider unavailable"}})
    )
    install_mock_provider(monkeypatch, transport)
    source, bible, workspace = translation_inputs(tmp_path)

    result = invoke_translate(CliRunner(), source, bible, workspace)

    assert result.exit_code == 2
    assert "HTTP 503: Provider unavailable" in result.output
    assert "Traceback" not in result.output


def test_translate_reports_total_timeout(tmp_path: Path, monkeypatch: Any) -> None:
    """A stalled provider is retried and ends as a controlled CLI error."""
    release_request = Event()

    def delayed_response(_: httpx2.Request) -> httpx2.Response:
        release_request.wait()
        return completion_response()

    install_mock_provider(monkeypatch, httpx2.MockTransport(delayed_response))
    source, bible, workspace = translation_inputs(tmp_path)
    try:
        result = invoke_translate(
            CliRunner(),
            source,
            bible,
            workspace,
            "--request-timeout",
            "1",
        )
    finally:
        release_request.set()

    assert result.exit_code == 2
    assert "Translation failed after three attempts" in result.output
    assert result.output.count("Request failed for segment") == 3
    assert "Traceback" not in result.output


def test_export_without_approval_is_rejected(tmp_path: Path, monkeypatch: Any) -> None:
    """A translated draft cannot be exported before explicit approval."""
    install_mock_provider(monkeypatch, httpx2.MockTransport(lambda _: completion_response()))
    source, bible, workspace = translation_inputs(tmp_path)
    runner = CliRunner()
    translated = invoke_translate(runner, source, bible, workspace)
    run_id = json.loads(translated.stdout)["run_id"]

    result = runner.invoke(
        app,
        [
            "export",
            run_id,
            "--workspace",
            str(workspace),
            "--destination",
            str(tmp_path / "unapproved.md"),
        ],
    )

    assert result.exit_code == 2
    assert "has not been approved" in result.output
    assert "Traceback" not in result.output
