"""CLI boundary tests."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from novel_translator.cli.app import app, load_environment
from novel_translator.providers import ProviderSelection

VALID_RUN_ID = "a" * 32


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


def create_inspect_run(workspace: Path) -> None:
    """Create a minimal valid run fixture for CLI inspection."""
    run_dir = workspace / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": VALID_RUN_ID}), encoding="utf-8"
    )
    (run_dir / "draft.md").write_text("Draft text", encoding="utf-8")


def test_inspect_reads_valid_run_with_optional_draft(tmp_path: Path) -> None:
    """Valid metadata is shown while draft content remains opt-in."""
    workspace = tmp_path / "workspace"
    create_inspect_run(workspace)
    runner = CliRunner()

    metadata_result = runner.invoke(
        app, ["inspect", VALID_RUN_ID, "--workspace", str(workspace)]
    )
    draft_result = runner.invoke(
        app,
        [
            "inspect",
            VALID_RUN_ID,
            "--workspace",
            str(workspace),
            "--include-draft",
        ],
    )

    assert metadata_result.exit_code == 0
    assert "draft" not in json.loads(metadata_result.output)
    assert draft_result.exit_code == 0
    assert json.loads(draft_result.output)["draft"] == "Draft text"


@pytest.mark.parametrize(
    "run_id",
    [
        "../outside",
        "..\\outside",
        "/absolute",
        "C:\\absolute",
        "a" * 31 + "/x",
        "A" * 32,
    ],
)
def test_inspect_rejects_path_shaped_run_ids(
    tmp_path: Path, run_id: str
) -> None:
    """Traversal, separators, and absolute paths fail as domain errors."""
    result = CliRunner().invoke(
        app, ["inspect", run_id, "--workspace", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert "Run ID must be 32 lowercase hexadecimal characters" in result.output
    assert "Traceback" not in result.output


def test_inspect_rejects_symlinked_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink in the resolved run path is rejected before reading files."""
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path.name == VALID_RUN_ID or original_is_symlink(path),
    )

    result = CliRunner().invoke(
        app, ["inspect", VALID_RUN_ID, "--workspace", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert "is a symlink" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (None, "Run metadata was not found"),
        ("not-json", "invalid JSON"),
        ('{"run_id": "wrong"}', "does not match"),
    ],
)
def test_inspect_reports_missing_or_corrupt_metadata(
    tmp_path: Path, metadata: str | None, message: str
) -> None:
    """Missing and corrupt metadata produce controlled CLI failures."""
    workspace = tmp_path / "workspace"
    if metadata is not None:
        run_dir = workspace / "runs" / VALID_RUN_ID
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(metadata, encoding="utf-8")

    result = CliRunner().invoke(
        app, ["inspect", VALID_RUN_ID, "--workspace", str(workspace)]
    )

    assert result.exit_code == 2
    assert message in result.output
    assert "Traceback" not in result.output


def test_inspect_reports_missing_draft_when_requested(tmp_path: Path) -> None:
    """Draft opt-in reports a controlled error when the artifact is absent."""
    workspace = tmp_path / "workspace"
    run_dir = workspace / "runs" / VALID_RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": VALID_RUN_ID}), encoding="utf-8"
    )

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            VALID_RUN_ID,
            "--workspace",
            str(workspace),
            "--include-draft",
        ],
    )

    assert result.exit_code == 2
    assert "Run draft was not found" in result.output
    assert "Traceback" not in result.output
