"""CLI boundary tests."""

from typer.testing import CliRunner

from novel_translator.cli.app import app, load_environment


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
