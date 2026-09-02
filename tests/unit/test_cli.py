"""CLI boundary tests."""

import json
from unittest.mock import Mock

from typer.testing import CliRunner

from novel_translator.cli.app import app, load_environment
from novel_translator.providers import ProviderSelection


def test_cli_lists_commands() -> None:
    """The local CLI exposes its four workflows."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("translate", "approve", "export", "inspect"):
        assert command in result.output


def test_load_environment_reads_dotenv_without_overriding_exported_values(tmp_path, monkeypatch) -> None:
    """The local .env provides missing values but never replaces process values."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "NOVEL_TRANSLATOR_BASE_URL=https://dotenv.example/v1\nNOVEL_TRANSLATOR_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVEL_TRANSLATOR_MODEL", "exported-model")
    monkeypatch.delenv("NOVEL_TRANSLATOR_BASE_URL", raising=False)

    load_environment()

    assert __import__("os").environ["NOVEL_TRANSLATOR_BASE_URL"] == "https://dotenv.example/v1"
    assert __import__("os").environ["NOVEL_TRANSLATOR_MODEL"] == "exported-model"


def test_translate_rejects_unknown_provider_before_creating_run(tmp_path) -> None:
    """Provider validation happens before the workspace or run is created."""
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    bible = tmp_path / "bible.yaml"
    bible.write_text("title: Novel\n", encoding="utf-8")
    workspace = tmp_path / "workspace"

    result = CliRunner().invoke(
        app,
        [
            "translate",
            "--novel",
            "novel",
            "--chapter",
            "1",
            "--source",
            str(source),
            "--bible",
            str(bible),
            "--workspace",
            str(workspace),
            "--base-url",
            "https://example.test/v1",
            "--model",
            "model",
            "--api-key",
            "secret",
            "--provider",
            "unknown",
        ],
    )

    assert result.exit_code == 2
    assert "Unsupported provider 'unknown'" in result.output
    assert not workspace.exists()


def test_translate_records_resolved_provider_and_model(tmp_path, monkeypatch) -> None:
    """Run metadata uses the provider and model attached to the selected adapter."""
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    bible = tmp_path / "bible.yaml"
    bible.write_text("title: Novel\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    gateway = Mock()
    gateway.translate.return_value = "translated"
    monkeypatch.setattr(
        "novel_translator.cli.app.resolve_provider",
        lambda *_: ProviderSelection("opencode-go", "resolved-model", gateway),
    )

    result = CliRunner().invoke(
        app,
        [
            "translate",
            "--novel",
            "novel",
            "--chapter",
            "1",
            "--source",
            str(source),
            "--bible",
            str(bible),
            "--workspace",
            str(workspace),
            "--base-url",
            "https://example.test/v1",
            "--model",
            "requested-model",
            "--api-key",
            "secret",
        ],
    )

    assert result.exit_code == 0
    run_dir = next((workspace / "runs").iterdir())
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "opencode-go"
    assert metadata["model"] == "resolved-model"
