"""Command-line entry point for the Novel Translator workflow."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import typer
from dotenv import load_dotenv

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
    RevokeApproval,
)
from novel_translator.application.bundles import (
    ExportRunBundle,
    ExportRunBundleInput,
    ImportRunBundle,
    ImportRunBundleInput,
)
from novel_translator.application.catalog import (
    ListChapters,
    ListChaptersInput,
    ListNovels,
    ResolveChapter,
    ResolveChapterInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
)
from novel_translator.application.inspect import GetChapter, GetChapterInput
from novel_translator.application.novels import (
    RegisterNovel,
    RegisterNovelInput,
    validate_source_filename,
)
from novel_translator.application.prepare import (
    PrepareTranslation,
    PrepareTranslationInput,
)
from novel_translator.application.publish import (
    PublishExport,
    PublishExportInput,
)
from novel_translator.application.review import (
    CreateRevision,
    CreateRevisionInput,
    GetDiff,
    GetDiffInput,
    ListRevisions,
    ListRevisionsInput,
    MigrateLegacyDraft,
    MigrateLegacyDraftInput,
)
from novel_translator.application.translate import (
    StartTranslation,
    StartTranslationInput,
)
from novel_translator.domain.errors import (
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import ChapterIdentity
from novel_translator.infrastructure.catalog import load_catalog
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.github import GitHubSitePublisher
from novel_translator.infrastructure.providers import (
    OpenCodeGoConfig,
    resolve_provider,
)
from novel_translator.infrastructure.source import (
    load_bible,
    read_revision_input,
    read_source,
)
from novel_translator.infrastructure.working_copies import (
    SqlAlchemyWorkingCopyRepository,
)
from novel_translator.infrastructure.workspace import Workspace

app = typer.Typer(add_completion=False, no_args_is_help=True)


def load_environment() -> None:
    """Load a local .env file without replacing exported environment values."""
    load_dotenv(Path.cwd() / ".env", override=False)


def fail(error: NovelTranslatorError) -> NoReturn:
    """Render an expected error without exposing secrets."""
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(2)


def _working_copies(
    workspace: Path,
) -> SqlAlchemyWorkingCopyRepository:
    """Open the workspace's working copy store, migrating as needed."""
    database = Database(str(workspace / "working-copies.sqlite"))
    database.prepare()
    return SqlAlchemyWorkingCopyRepository(database)


def resolve_run_id(
    run_id: str | None,
    novel: str | None,
    chapter: int | None,
    run_choice: int | None,
    config: Path,
    workspace: Path,
) -> str:
    """Resolve either an explicit technical ID or a friendly chapter choice."""
    if run_id is not None:
        if novel is not None or chapter is not None or run_choice is not None:
            raise ValidationError(
                "Use either RUN_ID or --novel/--chapter, not both."
            )
        return run_id
    if novel is None or chapter is None:
        raise ValidationError("Provide RUN_ID or both --novel and --chapter.")
    resolved = ResolveChapter(
        load_catalog(config),
        Workspace(workspace),
        _working_copies(workspace),
    ).execute(ResolveChapterInput(novel, chapter, run_choice))
    if resolved.run_id is None:
        raise ValidationError("The selected chapter has no translation run.")
    return resolved.run_id


@app.command()
def novels(
    config: Path = typer.Option(
        Path("novels.yaml"), exists=True, readable=True
    ),
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """List registered novels without exposing run identifiers."""
    try:
        catalog = ListNovels(
            load_catalog(config),
            Workspace(workspace),
            _working_copies(workspace),
        ).execute()
    except NovelTranslatorError as error:
        fail(error)
    for novel in catalog.novels:
        typer.echo(
            f"{novel.novel}: {novel.title} "
            f"({novel.chapter_count} chapters, {novel.run_count} runs)"
        )
    for issue in catalog.issues:
        typer.echo(
            f"Skipped run entry {issue.entry} ({issue.error.value})",
            err=True,
        )


novel_app = typer.Typer(no_args_is_help=True)
app.add_typer(novel_app, name="novel")


@novel_app.command("register")
def novel_register_command(
    novel_id: str = typer.Option(..., "--novel-id"),
    title: str = typer.Option(...),
    provider: str = typer.Option("opencode-go"),
    model: str = typer.Option(...),
    volume: int | None = typer.Option(None, min=1),
    kakuyomu_work: str | None = typer.Option(None, "--kakuyomu-work"),
    bible: Path | None = typer.Option(None, exists=True, readable=True),
    bible_text: str | None = typer.Option(None, "--bible-text"),
    export_repo: str = typer.Option("gregori/novels-site", "--export-repo"),
    export_dir: str | None = typer.Option(None, "--export-dir"),
    export_template: str = typer.Option(
        "{chapter:03}.md", "--export-template"
    ),
    config: Path = typer.Option(
        Path("novels.yaml"), exists=True, readable=True
    ),
    source_dir: Path | None = typer.Option(None, "--source-dir"),
) -> None:
    """Register a novel with its bible and an empty source directory."""
    try:
        if kakuyomu_work is not None:
            stripped = kakuyomu_work.strip().rstrip("/")
            root = (
                (
                    stripped
                    if stripped.endswith("/episodes")
                    else f"{stripped}/episodes"
                )
                if stripped
                else None
            )
        else:
            root = None
        sources: dict[str, str] | None = None
        if source_dir is not None:
            if not source_dir.is_dir():
                raise ValidationError(
                    "Source directory for initial chapters is not "
                    f"a directory: {source_dir}."
                )
            collected: dict[str, str] = {}
            for entry in sorted(source_dir.iterdir(), key=lambda p: p.name):
                if entry.is_file() and not entry.is_symlink():
                    validate_source_filename(entry.name)
                    collected[entry.name] = entry.read_text(encoding="utf-8")
            sources = collected or None
        result = RegisterNovel(load_catalog(config)).execute(
            RegisterNovelInput(
                novel_id=novel_id,
                title=title,
                model=model,
                export_repository=export_repo,
                bible_text=bible_text,
                bible_path=bible,
                source_files=sources,
                kakuyomu_episode_root=root,
                provider=provider,
                default_volume=volume,
                export_directory=export_dir,
                export_filename_template=export_template,
            )
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(
        f"Registered: {result.novel_id} "
        f"({result.source_directory} sources, bible {result.bible})"
    )


@app.command()
def chapters(
    novel: str,
    config: Path = typer.Option(
        Path("novels.yaml"), exists=True, readable=True
    ),
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """List chapter states and ordinal choices without full run IDs."""
    try:
        catalog = ListChapters(
            load_catalog(config),
            Workspace(workspace),
            _working_copies(workspace),
        ).execute(ListChaptersInput(novel))
    except NovelTranslatorError as error:
        fail(error)
    for chapter in catalog.chapters:
        typer.echo(
            f"{chapter.chapter}: {chapter.state.value} "
            f"({len(chapter.runs)} runs)"
        )
        if chapter.run_selection_required:
            for run in chapter.runs:
                typer.echo(
                    f"  choice {run.choice}: {run.timestamp} "
                    f"{run.model} [{run.status}]"
                )
        if chapter.source_selection_required:
            for source in chapter.sources:
                typer.echo(f"  source {source.choice}: {source.filename}")
    for issue in catalog.issues:
        typer.echo(
            f"Skipped run entry {issue.entry} ({issue.error.value})",
            err=True,
        )


@app.command()
def translate(
    novel: str = typer.Option(...),
    chapter: int = typer.Option(..., min=1),
    source: str | None = typer.Option(None),
    episode: str | None = typer.Option(None),
    bible: Path | None = typer.Option(None, exists=True, readable=True),
    config: Path = typer.Option(Path("novels.yaml")),
    source_choice: int | None = typer.Option(None, min=1),
    workspace: Path = typer.Option(Path(".novel-translator")),
    base_url: str = typer.Option(..., envvar="NOVEL_TRANSLATOR_BASE_URL"),
    model: str | None = typer.Option(None, envvar="NOVEL_TRANSLATOR_MODEL"),
    api_key: str = typer.Option(
        ..., envvar="NOVEL_TRANSLATOR_API_KEY", hide_input=True
    ),
    provider: str | None = typer.Option(None),
    volume: int | None = typer.Option(None, min=1),
    request_timeout: float = typer.Option(90.0, min=1.0),
    segment_limit: int = typer.Option(60_000, min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Translate a registered chapter into an immutable draft."""
    try:
        prepared = PrepareTranslation(load_catalog(config)).execute(
            PrepareTranslationInput(
                novel=novel,
                chapter=chapter,
                source=source,
                episode=episode,
                source_choice=source_choice,
                bible=bible,
                provider=provider,
                model=model,
                volume=volume,
            )
        )
        selection = resolve_provider(
            prepared.provider,
            OpenCodeGoConfig(
                base_url, prepared.model, api_key, request_timeout
            ),
        )
        result = StartTranslation(
            Workspace(workspace),
            selection.gateway,
        ).execute(
            StartTranslationInput(
                identity=ChapterIdentity(prepared.novel, prepared.chapter),
                source=read_source(prepared.source),
                bible=load_bible(prepared.bible),
                provider=selection.name,
                model=selection.model,
                volume=prepared.volume,
                progress=lambda index, total, attempt: typer.echo(
                    f"Translating segment {index}/{total} "
                    f"(attempt {attempt}/3)...",
                    err=True,
                ),
                retry_notice=lambda index, total, attempt, error: typer.echo(
                    f"Request failed for segment {index}/{total} "
                    f"(attempt {attempt}/3): {type(error).__name__}",
                    err=True,
                ),
                segment_limit=segment_limit,
            )
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(
        json.dumps({"run_id": result.run_id})
        if json_output
        else f"Draft created: {prepared.novel} chapter {prepared.chapter}"
    )


@app.command()
def approve(
    run_id: str | None = typer.Argument(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    revoke: bool = False,
    revision: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append an approval or revocation event for one verified artifact."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        use_case = (
            RevokeApproval(Workspace(workspace))
            if revoke
            else ApproveArtifact(Workspace(workspace))
        )
        event = use_case.execute(
            ArtifactApprovalInput(selected_run_id, revision)
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(
        json.dumps(asdict(event))
        if json_output
        else f"Approval recorded: {event.approved}"
    )


@app.command("export")
def export_command(
    run_id: str | None = typer.Argument(None),
    destination: Path | None = typer.Option(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    title: str | None = typer.Option(None),
    publish_date: str | None = typer.Option(None, "--publish-date"),
    workspace: Path = typer.Option(Path(".novel-translator")),
    overwrite: bool = typer.Option(False, "--overwrite"),
    site_root: Path | None = typer.Option(
        None, "--site-root", envvar="NOVEL_TRANSLATOR_SITE_ROOT"
    ),
    revision: str | None = typer.Option(None),
) -> None:
    """Export an approved draft without building, pushing or publishing."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        if destination is None:
            if novel is None or chapter is None:
                raise ValidationError(
                    "Provide --destination with a technical RUN_ID."
                )
            destination = load_catalog(config).export_destination(
                novel, chapter, site_root
            )
        result = ExportArtifact(
            Workspace(workspace), FilesystemArtifactWriter()
        ).execute(
            ExportArtifactInput(
                run_id=selected_run_id,
                destination=destination,
                revision_id=revision,
                title=title,
                overwrite=overwrite,
                publish_date=publish_date,
            )
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(f"Exported: {result.path}")


@app.command("publish")
def publish_command(
    run_id: str | None = typer.Argument(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    revision: str | None = typer.Option(None),
    title: str | None = typer.Option(None),
    publish_date: str | None = typer.Option(None, "--publish-date"),
    github_token: str | None = typer.Option(
        None, "--github-token", envvar="NOVEL_TRANSLATOR_GITHUB_TOKEN"
    ),
) -> None:
    """Open a novels-site pull request for one approved artifact."""
    try:
        if novel is None or chapter is None:
            raise ValidationError("Provide both --novel and --chapter.")
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        if github_token is None:
            raise ValidationError(
                "Provide --github-token or NOVEL_TRANSLATOR_GITHUB_TOKEN."
            )
        registry = load_catalog(config)
        result = PublishExport(
            Workspace(workspace),
            registry,
            GitHubSitePublisher(github_token),
        ).execute(
            PublishExportInput(
                run_id=selected_run_id,
                novel=novel,
                chapter=chapter,
                revision_id=revision,
                title=title,
                publish_date=publish_date,
            )
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(f"Published: {result.pull_request_url or result.git_commit}")


@app.command()
def inspect(
    run_id: str | None = typer.Argument(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    include_draft: bool = False,
    revision: str | None = typer.Option(None),
    include_content: bool = typer.Option(False),
) -> None:
    """Inspect run metadata or one immutable revision; content is opt-in."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        data = (
            GetChapter(Workspace(workspace))
            .execute(
                GetChapterInput(
                    run_id=selected_run_id,
                    include_draft=include_draft,
                    revision_id=revision,
                    include_content=include_content,
                )
            )
            .data
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def revise(
    run_id: str | None = typer.Argument(None),
    input: Path = typer.Option(..., exists=True, readable=True),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    parent: str | None = typer.Option(None),
    note: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create an immutable human revision from a verified parent artifact."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        record = CreateRevision(Workspace(workspace)).execute(
            CreateRevisionInput(
                selected_run_id, read_revision_input(input), parent, note
            )
        )
    except NovelTranslatorError as error:
        fail(error)
    payload = {
        "revision_id": record.revision_id,
        "content_hash": record.content_hash,
        "parent": asdict(record.parent),
    }
    typer.echo(
        json.dumps(payload)
        if json_output
        else f"Revision created: {record.revision_id}"
    )


@app.command()
def revisions(
    run_id: str | None = typer.Argument(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """List immutable revisions without exposing their content."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        summaries = ListRevisions(Workspace(workspace)).execute(
            ListRevisionsInput(selected_run_id)
        )
        payload: list[dict[str, object]] = []
        for summary in summaries:
            item = asdict(summary.record)
            item["approved"] = summary.approved
            payload.append(item)
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("diff")
def diff_command(
    run_id: str | None = typer.Argument(None),
    revision: str = typer.Option(...),
    against: str | None = typer.Option(None),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
) -> None:
    """Render a unified diff for one revision and its selected parent."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        result = GetDiff(Workspace(workspace)).execute(
            GetDiffInput(selected_run_id, revision, against)
        )
        typer.echo(result.content, nl=False)
    except NovelTranslatorError as error:
        fail(error)


bundle_app = typer.Typer(no_args_is_help=True)
app.add_typer(bundle_app, name="bundle")


@bundle_app.command("export")
def bundle_export_command(
    run_id: str | None = typer.Argument(None),
    output: Path | None = typer.Option(None, "-o", "--output"),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Bundle one verified run for local and web sync."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        result = ExportRunBundle(Workspace(workspace)).execute(
            ExportRunBundleInput(selected_run_id)
        )
        destination = output or Path(result.filename)
        destination.write_bytes(result.payload)
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(
        json.dumps({"run_id": result.run_id, "path": str(destination)})
        if json_output
        else f"Bundle exported: {destination}"
    )


@bundle_app.command("import")
def bundle_import_command(
    bundle: Path = typer.Argument(..., exists=True, readable=True),
    workspace: Path = typer.Option(Path(".novel-translator")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Verify and store one run bundle without touching session state."""
    try:
        result = ImportRunBundle(Workspace(workspace)).execute(
            ImportRunBundleInput(bundle.read_bytes())
        )
    except NovelTranslatorError as error:
        fail(error)
    typer.echo(
        json.dumps(
            {
                "run_id": result.run_id,
                "novel": result.novel,
                "chapter": result.chapter,
                "created": result.created,
            }
        )
        if json_output
        else (
            f"Bundle imported: {result.novel} chapter {result.chapter}"
            + ("" if result.created else " (already present)")
        )
    )


@app.command("migrate-legacy-draft")
def migrate_legacy_draft_command(
    run_id: str | None = typer.Argument(None),
    as_published: bool = typer.Option(False, "--as-published"),
    novel: str | None = typer.Option(None),
    chapter: int | None = typer.Option(None, min=1),
    run_choice: int | None = typer.Option(None, min=1),
    config: Path = typer.Option(Path("novels.yaml")),
    workspace: Path = typer.Option(Path(".novel-translator")),
    note: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Snapshot a legacy published draft without claiming generated output."""
    try:
        selected_run_id = resolve_run_id(
            run_id, novel, chapter, run_choice, config, workspace
        )
        record = MigrateLegacyDraft(Workspace(workspace)).execute(
            MigrateLegacyDraftInput(selected_run_id, as_published, note)
        )
    except NovelTranslatorError as error:
        fail(error)
    payload = {
        "revision_id": record.revision_id,
        "content_hash": record.content_hash,
        "parent": asdict(record.parent),
    }
    typer.echo(
        json.dumps(payload)
        if json_output
        else f"Legacy revision created: {record.revision_id}"
    )


def main() -> None:
    """Run the CLI application."""
    load_environment()
    app()
