"""Chapter routes: the review room page and its HTML fragments."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from novel_translator.application.catalog import ChapterSummary
from novel_translator.application.export import ExportHistoryInput
from novel_translator.application.inspect import ReadChapterForReviewInput
from novel_translator.application.review import GetDiffInput
from novel_translator.application.working_copy import GetWorkingCopyDiffInput
from novel_translator.domain.errors import IntegrityError, NovelTranslatorError
from novel_translator.domain.models import ExportEvent, WorkingCopy
from novel_translator.web.routes.support import (
    FLASH_MESSAGES,
    active_copy,
    chapter_urls,
    require_novel,
    revision_id_for,
    run_id_for,
)
from novel_translator.web.services import Services
from novel_translator.web.viewmodels import (
    RevisionView,
    diff_html,
    format_timestamp,
    render_markdown,
    revision_views,
    state_label,
)

router = APIRouter()

_TECHNICAL_KEYS = (
    "status",
    "timestamp",
    "provider",
    "model",
    "volume",
    "source_hash",
    "bible_version",
    "prompt_version",
)


@dataclass(frozen=True, slots=True)
class ChapterView:
    """Everything the chapter template renders, already display-safe."""

    novel: str
    title: str
    chapter: int
    state: str
    state_key: str
    run_choice: int | None
    source: str | None
    draft: str | None
    working_copy: WorkingCopy | None
    revisions: tuple[RevisionView, ...]
    technical: tuple[tuple[str, str], ...]
    run_status: str
    urls: dict[str, str]


def technical_rows(
    run_id: str | None,
    details: dict[str, object],
    copy: WorkingCopy | None,
    revisions: tuple[RevisionView, ...],
    last_export: ExportEvent | None = None,
) -> tuple[tuple[str, str], ...]:
    """Collect identifiers and every available hash for the details panel."""
    rows: list[tuple[str, str]] = []
    if run_id:
        rows.append(("run_id", run_id))
    for key, value in details.items():
        if key not in _TECHNICAL_KEYS and not key.endswith("_hash"):
            continue
        if value in (None, ""):
            continue
        if key == "timestamp" and isinstance(value, str):
            rows.append((key, format_timestamp(value)))
        else:
            rows.append((key, str(value)))
    if copy is not None:
        rows.extend(
            (
                ("working_copy_id", copy.id),
                ("base_artifact", copy.base_artifact_kind.value),
                ("base_artifact_id", copy.base_artifact_id or "—"),
                ("base_content_hash", copy.base_content_hash),
                ("working_copy_version", str(copy.version)),
                ("working_copy_updated_at", format_timestamp(copy.updated_at)),
            )
        )
    for revision in revisions:
        rows.extend(
            (
                (f"revision_{revision.ordinal}_id", revision.revision_id),
                (
                    f"revision_{revision.ordinal}_content_hash",
                    revision.content_hash,
                ),
            )
        )
    if last_export is not None:
        rows.extend(
            (
                ("last_export_content_hash", last_export.content_hash),
                ("last_export_destination", last_export.destination),
                (
                    "last_exported_at",
                    format_timestamp(last_export.exported_at),
                ),
            )
        )
    return tuple(rows)


def _chapter_summary(
    services: Services, novel: str, chapter: int
) -> ChapterSummary:
    """Return the catalog summary for one configured chapter."""
    catalog = services.chapter_catalog(novel)
    summary = next(
        (item for item in catalog.chapters if item.chapter == chapter), None
    )
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail="This chapter is not configured in the novel catalog. "
            "Add a chapter source file or translate it first.",
        )
    return summary


@router.get(
    "/novels/{novel}/chapters/{chapter}",
    response_class=HTMLResponse,
    name="chapter",
)
def chapter_page(
    request: Request, novel: str, chapter: int, run_choice: int | None = None
) -> HTMLResponse:
    """Render the review room for one chapter."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    summary = _chapter_summary(services, novel, chapter)
    if summary.run_selection_required and run_choice is None:
        return templates.TemplateResponse(
            request,
            "run_picker.html",
            {
                "novel": novel,
                "title": services.novel_title(novel),
                "chapter": chapter,
                "runs": summary.runs,
            },
        )
    result = services.read_chapter_for_review.execute(
        ReadChapterForReviewInput(
            novel=novel, chapter=chapter, run_choice=run_choice
        )
    )
    revisions = revision_views(result.revisions)
    last_export: ExportEvent | None = None
    last_pull_request_url: str | None = None
    if result.run_id is not None:
        with suppress(NovelTranslatorError):
            history = services.list_export_history.execute(
                ExportHistoryInput(run_id=result.run_id)
            )
            last_export = history[-1] if history else None
            for event in reversed(history):
                if event.pull_request_url is not None:
                    last_pull_request_url = event.pull_request_url
                    break
    view = ChapterView(
        novel=novel,
        title=services.novel_title(novel),
        chapter=chapter,
        state=state_label(result.state),
        state_key=result.state.value,
        run_choice=result.run_choice,
        source=result.source,
        draft=result.draft,
        working_copy=result.working_copy,
        revisions=revisions,
        technical=technical_rows(
            result.run_id,
            result.details,
            result.working_copy,
            revisions,
            last_export,
        ),
        run_status=result.run_status,
        urls=chapter_urls(novel, chapter, result.run_choice),
    )
    has_draft = result.draft is not None
    flash_key = request.query_params.get("done")
    export_config = services.registry.novel(novel).export
    return templates.TemplateResponse(
        request,
        "chapter.html",
        {
            "view": view,
            "has_run": result.run_id is not None,
            "has_draft": has_draft,
            "draft_approved": result.draft_approved,
            "flash": FLASH_MESSAGES.get(flash_key) if flash_key else None,
            "last_export": last_export,
            "export_enabled": services.site_root is not None,
            "export_repository": export_config.repository,
            "export_path": (
                f"{export_config.directory.as_posix()}/"
                f"{services.export_filename(novel, chapter)}"
            ),
            "publish_enabled": services.publish_export is not None,
            "last_pull_request_url": last_pull_request_url,
        },
    )


@router.get(
    "/novels/{novel}/chapters/{chapter}/working-copy/diff",
    response_class=HTMLResponse,
    name="working-copy-diff",
)
def working_copy_diff(
    request: Request, novel: str, chapter: int, run_choice: int | None = None
) -> HTMLResponse:
    """Show the working copy diff against its verified base artifact."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    run_id = run_id_for(services, novel, chapter, run_choice)
    copy = active_copy(services, run_id)
    result = services.get_working_copy_diff.execute(
        GetWorkingCopyDiffInput(working_copy_id=copy.id)
    )
    return templates.TemplateResponse(
        request,
        "partials/diff.html",
        {"diff": diff_html(result.content), "title": "Working copy vs base"},
    )


@router.get(
    "/novels/{novel}/chapters/{chapter}/working-copy/preview",
    response_class=HTMLResponse,
    name="working-copy-preview",
)
def working_copy_preview(
    request: Request, novel: str, chapter: int, run_choice: int | None = None
) -> HTMLResponse:
    """Render the reviewable content as safe Markdown HTML."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    result = services.read_chapter_for_review.execute(
        ReadChapterForReviewInput(
            novel=novel, chapter=chapter, run_choice=run_choice
        )
    )
    content = (
        result.working_copy.content
        if result.working_copy is not None
        else result.draft
    )
    if content is None:
        return templates.TemplateResponse(
            request,
            "partials/notice.html",
            {"message": "Nothing to preview yet.", "kind": "muted"},
        )
    return templates.TemplateResponse(
        request,
        "partials/preview.html",
        {"preview": render_markdown(content)},
    )


@router.get(
    "/novels/{novel}/chapters/{chapter}/revisions/{ordinal}/diff",
    response_class=HTMLResponse,
    name="revision-diff",
)
def revision_diff(
    request: Request,
    novel: str,
    chapter: int,
    ordinal: int,
    run_choice: int | None = None,
) -> HTMLResponse:
    """Show one immutable revision diff against its declared parent."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    run_id = run_id_for(services, novel, chapter, run_choice)
    revision_id = revision_id_for(services, run_id, ordinal)
    if revision_id is None:
        raise IntegrityError("The selected revision no longer exists.")
    result = services.get_diff.execute(
        GetDiffInput(run_id=run_id, revision_id=revision_id)
    )
    return templates.TemplateResponse(
        request,
        "partials/diff.html",
        {
            "diff": diff_html(result.content),
            "title": f"Revision {ordinal} vs parent",
        },
    )
