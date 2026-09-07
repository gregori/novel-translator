"""Approval, revocation, and export routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from novel_translator.application.approve import ArtifactApprovalInput
from novel_translator.application.export import ExportArtifactInput
from novel_translator.web.routes.support import (
    parse_choice,
    redirect_done,
    require_novel,
    revision_id_for,
    run_id_for,
)
from novel_translator.web.services import Services

router = APIRouter()


def _approval(
    services: Services,
    novel: str,
    chapter: int,
    run_choice: str | None,
    revision: str | None,
    *,
    approve: bool,
) -> Response:
    """Record one approval decision for a revision or the draft."""
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    revision_id = revision_id_for(services, run_id, parse_choice(revision))
    request_input = ArtifactApprovalInput(run_id, revision_id)
    if approve:
        services.approve_artifact.execute(request_input)
    else:
        services.revoke_approval.execute(request_input)
    return redirect_done(
        novel, chapter, choice, "approved" if approve else "revoked"
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/approval",
    response_class=HTMLResponse,
    name="approve",
)
def approve(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    revision: Annotated[str | None, Form()] = None,
) -> Response:
    """Approve the selected revision or generated draft."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    return _approval(
        services, novel, chapter, run_choice, revision, approve=True
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/approval/revoke",
    response_class=HTMLResponse,
    name="revoke",
)
def revoke(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    revision: Annotated[str | None, Form()] = None,
) -> Response:
    """Revoke approval for the selected revision or generated draft."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    return _approval(
        services, novel, chapter, run_choice, revision, approve=False
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/export",
    response_class=HTMLResponse,
    name="export",
)
def export(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    revision: Annotated[str | None, Form()] = None,
    overwrite: Annotated[str | None, Form()] = None,
) -> Response:
    """Export the approved revision or draft into the site checkout."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    choice = parse_choice(run_choice)
    run_id = run_id_for(services, novel, chapter, choice)
    revision_id = revision_id_for(services, run_id, parse_choice(revision))
    services.export_artifact.execute(
        ExportArtifactInput(
            run_id=run_id,
            destination=services.export_destination(novel, chapter),
            revision_id=revision_id,
            overwrite=overwrite == "on",
        )
    )
    return redirect_done(novel, chapter, choice, "exported")
