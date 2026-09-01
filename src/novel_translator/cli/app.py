"""Command-line entry point for the Novel Translator workflow."""

import json
from pathlib import Path
from typing import NoReturn

import typer
from dotenv import load_dotenv

from novel_translator.core import (
    OpenAICompatibleGateway,
    TranslationService,
    Workspace,
    export_draft,
    load_bible,
    read_source,
)
from novel_translator.core import (
    approve as approve_draft,
)
from novel_translator.shared.errors import NovelTranslatorError
from novel_translator.shared.models import ChapterIdentity

app = typer.Typer(add_completion=False, no_args_is_help=True)


def load_environment() -> None:
    """Load a local .env file without replacing exported environment values."""
    load_dotenv(Path.cwd() / ".env", override=False)


def fail(error: NovelTranslatorError) -> NoReturn:
    """Render an expected error without exposing secrets."""
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(2)


@app.command()
def translate(
    novel: str = typer.Option(...),
    chapter: int = typer.Option(..., min=1),
    source: str = typer.Option(...),
    bible: Path = typer.Option(..., exists=True, readable=True),
    workspace: Path = typer.Option(Path(".novel-translator")),
    base_url: str = typer.Option(..., envvar="NOVEL_TRANSLATOR_BASE_URL"),
    model: str = typer.Option(..., envvar="NOVEL_TRANSLATOR_MODEL"),
    api_key: str = typer.Option(..., envvar="NOVEL_TRANSLATOR_API_KEY", hide_input=True),
    provider: str = typer.Option("opencode-go"),
    volume: int | None = typer.Option(None, min=1),
    request_timeout: float = typer.Option(90.0, min=1.0),
    segment_limit: int = typer.Option(60_000, min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Translate a UTF-8 file or Kakuyomu URL into an immutable draft."""
    try:
        run_id = TranslationService(
            Workspace(workspace),
            OpenAICompatibleGateway(base_url, model, api_key, request_timeout),
        ).translate(
            ChapterIdentity(novel, chapter),
            read_source(source),
            load_bible(bible),
            provider,
            model,
            volume,
            lambda index, total, attempt: typer.echo(
                f"Translating segment {index}/{total} (attempt {attempt}/3)...", err=True
            ),
            lambda index, total, attempt, error: typer.echo(
                f"Request failed for segment {index}/{total} (attempt {attempt}/3): "
                f"{type(error).__name__}: {error}",
                err=True,
            ),
            segment_limit,
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps({"run_id": run_id}) if json_output else f"Draft created: {run_id}")


@app.command()
def approve(
    run_id: str,
    workspace: Path = typer.Option(Path(".novel-translator")),
    revoke: bool = False,
) -> None:
    """Append an approval or revocation event for a current draft."""
    try:
        event = approve_draft(Workspace(workspace), run_id, not revoke)
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(f"Approval recorded: {event.approved}")


@app.command("export")
def export_command(
    run_id: str,
    destination: Path = typer.Option(...),
    title: str | None = typer.Option(None),
    publish_date: str | None = typer.Option(None, "--publish-date"),
    workspace: Path = typer.Option(Path(".novel-translator")),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Export an approved draft without building, pushing or publishing."""
    try:
        path = export_draft(
            Workspace(workspace),
            run_id,
            destination,
            title,
            overwrite,
            publish_date,
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(f"Exported: {path}")


@app.command()
def inspect(
    run_id: str,
    workspace: Path = typer.Option(Path(".novel-translator")),
    include_draft: bool = False,
) -> None:
    """Inspect run metadata; draft content is opt-in."""
    try:
        root = Workspace(workspace).root / "runs" / run_id
        data = json.loads((root / "run.json").read_text(encoding="utf-8"))
        if include_draft:
            data["draft"] = (root / "draft.md").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as error:
        fail(NovelTranslatorError(f"Cannot inspect run: {error}"))
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    """Run the CLI application."""
    load_environment()
    app()
