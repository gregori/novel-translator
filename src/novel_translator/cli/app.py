"""Command-line entry point for the Novel Translator workflow."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import typer
from dotenv import load_dotenv

from novel_translator.core import (
    TranslationService,
    Workspace,
    export_draft,
    load_bible,
    read_source,
)
from novel_translator.core import approve as approve_draft
from novel_translator.editorial import (
    create_revision,
    migrate_legacy_draft,
    read_revision_input,
    revision_diff,
    revision_summary,
)
from novel_translator.providers import OpenCodeGoConfig, resolve_provider
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
        selection = resolve_provider(
            provider,
            OpenCodeGoConfig(base_url, model, api_key, request_timeout),
        )
        run_id = TranslationService(
            Workspace(workspace),
            selection.gateway,
        ).translate(
            ChapterIdentity(novel, chapter),
            read_source(source),
            load_bible(bible),
            selection.name,
            selection.model,
            volume,
            lambda index, total, attempt: typer.echo(
                f"Translating segment {index}/{total} (attempt {attempt}/3)...",
                err=True,
            ),
            lambda index, total, attempt, error: typer.echo(
                f"Request failed for segment {index}/{total} (attempt {attempt}/3): {type(error).__name__}",
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
    revision: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append an approval or revocation event for one verified artifact."""
    try:
        event = approve_draft(Workspace(workspace), run_id, not revoke, revision)
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps(asdict(event)) if json_output else f"Approval recorded: {event.approved}")


@app.command("export")
def export_command(
    run_id: str,
    destination: Path = typer.Option(...),
    title: str | None = typer.Option(None),
    publish_date: str | None = typer.Option(None, "--publish-date"),
    workspace: Path = typer.Option(Path(".novel-translator")),
    overwrite: bool = typer.Option(False, "--overwrite"),
    revision: str | None = typer.Option(None),
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
            revision,
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(f"Exported: {path}")


@app.command()
def inspect(
    run_id: str,
    workspace: Path = typer.Option(Path(".novel-translator")),
    include_draft: bool = False,
    revision: str | None = typer.Option(None),
    include_content: bool = typer.Option(False),
) -> None:
    """Inspect run metadata or one immutable revision; content is opt-in."""
    try:
        store = Workspace(workspace)
        if revision is None:
            data = store.inspect_run(run_id, include_draft)
        else:
            record, artifact = store.revision(run_id, revision)
            data = asdict(record)
            data["approved"] = store.is_artifact_approved(artifact, run_id)
            if include_content:
                data["content"] = artifact.content
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def revise(
    run_id: str,
    input: Path = typer.Option(..., exists=True, readable=True),
    workspace: Path = typer.Option(Path(".novel-translator")),
    parent: str | None = typer.Option(None),
    note: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create an immutable human revision from a verified parent artifact."""
    try:
        record = create_revision(Workspace(workspace), run_id, read_revision_input(input), parent, note)
    except NovelTranslatorError as error:
        fail(error)
    payload = {"revision_id": record.revision_id, "content_hash": record.content_hash, "parent": asdict(record.parent)}
    typer.echo(json.dumps(payload) if json_output else f"Revision created: {record.revision_id}")


@app.command()
def revisions(
    run_id: str,
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """List immutable revisions without exposing their content."""
    try:
        payload = revision_summary(Workspace(workspace), run_id)
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("diff")
def diff_command(
    run_id: str,
    revision: str = typer.Option(...),
    against: str | None = typer.Option(None),
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """Render a unified diff for one revision and its declared or selected parent."""
    try:
        typer.echo(revision_diff(Workspace(workspace), run_id, revision, against), nl=False)
    except NovelTranslatorError as error:
        fail(error)


@app.command("migrate-legacy-draft")
def migrate_legacy_draft_command(
    run_id: str,
    as_published: bool = typer.Option(False, "--as-published"),
    workspace: Path = typer.Option(Path(".novel-translator")),
    note: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Snapshot a legacy published draft without claiming it is the generated output."""
    try:
        record = migrate_legacy_draft(Workspace(workspace), run_id, as_published, note)
    except NovelTranslatorError as error:
        fail(error)
    payload = {"revision_id": record.revision_id, "content_hash": record.content_hash, "parent": asdict(record.parent)}
    typer.echo(json.dumps(payload) if json_output else f"Legacy revision created: {record.revision_id}")


def main() -> None:
    """Run the CLI application."""
    load_environment()
    app()
