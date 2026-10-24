"""Bundle routes: download and import run bundles for sync."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from novel_translator.application.bundles import (
    ExportRunBundleInput,
    ImportRunBundleInput,
)
from novel_translator.domain.errors import NovelTranslatorError
from novel_translator.web.routes.support import (
    parse_choice,
    redirect_done,
    require_novel,
    run_id_for,
)
from novel_translator.web.services import Services

router = APIRouter()

MAX_BUNDLE_BYTES = 50_000_000
"""Largest accepted bundle upload; runs are tens of megabytes at most."""


def _bundle_filename(
    services: Services, novel: str, chapter: int, run_choice: int | None
) -> tuple[bytes, str]:
    """Export one run and return its payload plus download filename."""
    run_id = run_id_for(services, novel, chapter, run_choice)
    result = services.export_run_bundle.execute(ExportRunBundleInput(run_id))
    return result.payload, result.filename


@router.get(
    "/novels/{novel}/chapters/{chapter}/bundle",
    name="bundle-download",
)
def bundle_download(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[int | None, Query()] = None,
) -> Response:
    """Download one verified run as a portable bundle file."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    payload, filename = _bundle_filename(services, novel, chapter, run_choice)
    return Response(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/bundles/import",
    response_class=HTMLResponse,
    name="bundle-import-novel",
)
def bundle_import_for_novel(
    request: Request,
    novel: Annotated[str, Form()],
    bundle: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """Verify and store one uploaded bundle, then show its novel page."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    if bundle is None or not bundle.filename:
        raise NovelTranslatorError("Select a bundle file to import.")
    raw = bundle.file.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise NovelTranslatorError("Bundle must be at most 50 MB.")
    result = services.import_run_bundle.execute(ImportRunBundleInput(raw))
    require_novel(services, result.novel)
    return RedirectResponse(
        f"/novels/{result.novel}/chapters/{result.chapter}", status_code=303
    )


@router.post(
    "/novels/{novel}/chapters/{chapter}/bundle/import",
    response_class=HTMLResponse,
    name="bundle-import",
)
def bundle_import(
    request: Request,
    novel: str,
    chapter: int,
    run_choice: Annotated[str | None, Form()] = None,
    bundle: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """Verify and store one uploaded run bundle, then show its chapter."""
    services: Services = request.app.state.services
    require_novel(services, novel)
    if bundle is None or not bundle.filename:
        raise NovelTranslatorError("Select a bundle file to import.")
    raw = bundle.file.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise NovelTranslatorError("Bundle must be at most 50 MB.")
    # Zip bytes are binary; validate the container, not text decoding.
    # Identity is checked against the manifest before any persist.
    services.import_run_bundle.execute(
        ImportRunBundleInput(
            raw, expected_novel=novel, expected_chapter=chapter
        )
    )
    choice = parse_choice(run_choice)
    return redirect_done(novel, chapter, choice, "bundle-imported")
