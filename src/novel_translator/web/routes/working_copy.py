"""Working copy routes: start, save, discard, and freeze into revisions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from novel_translator.application.working_copy import (
    CreateRevisionFromWorkingCopyInput,
    DiscardWorkingCopyInput,
    SaveWorkingCopyInput,
    StartWorkingCopyInput,
)
from novel_translator.domain.errors import (
    IntegrityError,
    ValidationError,
    WorkingCopyConflict,
)
from novel_translator.web.routes.support import (
    active_copy,
    chapter_urls,
    parse_choice,
    redirect_done,
    require_novel,
    run_id_for,
    stale_session,
)
from novel_translator.web.services import Services
from novel_translator.web.viewmodels import format_timestamp

router = APIRouter()

_RELOAD_MESSAGE = (
    "This working copy no longer exists — it was discarded "
    "or turned into a revision. Reload the page."
)


def _stale_form(
    request: Request,
    templates: Jinja2Templates,
    urls: dict[str, str],
    message: str,
) -> HTMLResponse:
    """Render the reload-orientation partial for a stale editor."""
    return templates.TemplateResponse(
        request,
        "partials/save_error.html",
        {"urls": urls, "message": message},
        status_code=409,
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/working-copy",
    response_class=HTMLResponse,
    name="start-working-copy",
)
def start_working_copy(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
) -> Response:
    """Start a working copy from the draft or the latest revision."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    services.start_working_copy.execute(StartWorkingCopyInput(run_id))
    return redirect_done(novel, chapter, choice, "working-copy")


@router.post(
    "/novels/{novel}/chapters/{chapter}/working-copy/save",
    response_class=HTMLResponse,
    name="save-working-copy",
)
def save_working_copy(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    working_copy_id: Annotated[str | None, Form()] = None,
    version: Annotated[str, Form()] = "",
    content: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Autosave the working copy with optimistic version checking."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    copy = active_copy(services, run_id)
    urls = chapter_urls(novel, chapter, choice)
    if working_copy_id != copy.id:
        return _stale_form(request, templates, urls, str(stale_session()))
    try:
        expected_version = int(version)
    except ValueError as error:
        raise ValidationError("Invalid working copy version.") from error
    try:
        saved = services.save_working_copy.execute(
            SaveWorkingCopyInput(
                working_copy_id=copy.id,
                expected_version=expected_version,
                content=content,
            )
        )
    except WorkingCopyConflict as conflict:
        return templates.TemplateResponse(
            request,
            "partials/conflict.html",
            {
                "conflict": conflict,
                "urls": urls,
                "run_choice": choice,
                "working_copy_id": copy.id,
            },
            status_code=409,
        )
    except IntegrityError:
        return _stale_form(request, templates, urls, _RELOAD_MESSAGE)
    return templates.TemplateResponse(
        request,
        "partials/save_result.html",
        {
            "version": saved.version,
            "saved_at": format_timestamp(saved.updated_at),
        },
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/working-copy/discard",
    response_class=HTMLResponse,
    name="discard-working-copy",
)
def discard_working_copy(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    working_copy_id: Annotated[str | None, Form()] = None,
) -> Response:
    """Discard the working copy; the draft stays untouched."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    copy = active_copy(services, run_id)
    if working_copy_id != copy.id:
        raise stale_session()
    services.discard_working_copy.execute(
        DiscardWorkingCopyInput(working_copy_id=copy.id)
    )
    return redirect_done(novel, chapter, choice, "discarded")


@router.post(
    "/novels/{novel}/chapters/{chapter}/revision",
    response_class=HTMLResponse,
    name="create-revision",
)
def create_revision(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    working_copy_id: Annotated[str | None, Form()] = None,
    note: Annotated[str, Form()] = "",
) -> Response:
    """Create an immutable revision from the working copy."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    copy = active_copy(services, run_id)
    if working_copy_id != copy.id:
        raise stale_session()
    services.create_revision_from_working_copy.execute(
        CreateRevisionFromWorkingCopyInput(
            run_id=run_id,
            working_copy_id=copy.id,
            note=note.strip() or None,
        )
    )
    return redirect_done(novel, chapter, choice, "revision-created")
