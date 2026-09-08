"""Catalog routes: the dashboard and per-novel chapter listings."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from novel_translator.web.routes.support import (
    require_novel,
    state_or_none,
    wants_partial,
)
from novel_translator.web.services import Services
from novel_translator.web.viewmodels import (
    ChapterFilter,
    dashboard_groups,
    filter_chapters,
    recent_chapters,
    state_counts,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request) -> HTMLResponse:
    """Show novels, recent chapters, state groups, and active jobs."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    catalog = services.dashboard()
    jobs = [
        job
        for job in services.list_translation_jobs.execute()
        if job.status.value in ("queued", "running", "cancel_requested")
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "novels": catalog.novels,
            "issues": catalog.issues,
            "recent": recent_chapters(catalog.chapters),
            "groups": dashboard_groups(catalog.chapters),
            "active_jobs": jobs,
        },
    )


@router.get("/novels/{novel}", response_class=HTMLResponse, name="novel")
def novel_page(
    request: Request, novel: str, q: str = "", state: str = ""
) -> HTMLResponse:
    """List chapters with friendly search and state filtering."""
    services: Services = request.app.state.services
    templates = request.app.state.templates
    require_novel(services, novel)
    catalog = services.chapter_catalog(novel)
    chapter_filter = ChapterFilter(q.strip(), state_or_none(state))
    chapters = filter_chapters(catalog.chapters, chapter_filter)
    context = {
        "novel": novel,
        "title": services.novel_title(novel),
        "chapters": chapters,
        "total": len(catalog.chapters),
        "counts": state_counts(catalog.chapters),
        "query": chapter_filter.query,
        "state": state,
        "issues": catalog.issues,
    }
    template = (
        "partials/chapter_list.html"
        if wants_partial(request)
        else "novel.html"
    )
    return templates.TemplateResponse(request, template, context)
