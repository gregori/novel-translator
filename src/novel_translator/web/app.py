"""FastAPI application factory and entry point for the web room."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from novel_translator.application.approve import (
    ApproveArtifact,
    RevokeApproval,
)
from novel_translator.application.catalog import (
    ListChapters,
    ListDashboard,
    ResolveChapter,
)
from novel_translator.application.export import ExportArtifact
from novel_translator.application.inspect import ReadChapterForReview
from novel_translator.application.jobs import (
    EnqueueTranslation,
    GetTranslationJob,
    ListTranslationJobs,
    RequestJobCancellation,
    RetryTranslationJob,
)
from novel_translator.application.review import GetDiff, ListRevisions
from novel_translator.application.working_copy import (
    CreateRevisionFromWorkingCopy,
    DiscardWorkingCopy,
    GetWorkingCopy,
    GetWorkingCopyDiff,
    SaveWorkingCopy,
    StartWorkingCopy,
)
from novel_translator.domain.errors import (
    ApprovalRequired,
    CollisionRequired,
    IntegrityError,
    NovelTranslatorError,
)
from novel_translator.infrastructure.catalog import load_catalog
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.jobs import (
    SqlAlchemyTranslationJobRepository,
)
from novel_translator.infrastructure.working_copies import (
    SqlAlchemyWorkingCopyRepository,
)
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.web import routes
from novel_translator.web.auth import AuthMiddleware, build_auth_state
from novel_translator.web.routes.auth import router as auth_router
from novel_translator.web.routes.translate import router as translate_router
from novel_translator.web.services import Services
from novel_translator.web.viewmodels import (
    diff_html,
    format_elapsed,
    format_timestamp,
    render_markdown,
    state_class,
    state_label,
)

_PACKAGE = Path(__file__).parent
TEMPLATES = _PACKAGE / "templates"
STATIC = _PACKAGE / "static"


def _status_for(error: NovelTranslatorError) -> int:
    """Map one typed application error onto an HTTP status."""
    if isinstance(
        error, (IntegrityError, ApprovalRequired, CollisionRequired)
    ):
        return 409
    return 400


def _register_filters(templates: Jinja2Templates) -> None:
    """Expose presentation helpers to templates as Jinja filters."""
    templates.env.filters["state_label"] = state_label
    templates.env.filters["state_class"] = state_class
    templates.env.filters["timestamp"] = format_timestamp
    templates.env.filters["elapsed"] = format_elapsed
    templates.env.filters["markdown"] = render_markdown
    templates.env.filters["diff"] = diff_html


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _OriginCheckMiddleware(BaseHTTPMiddleware):
    """Refuse cross-site mutating requests with 403."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in _MUTATING_METHODS:
            # Absent Origin/Referer is allowed on purpose: modern browsers
            # always send Origin on cross-site POSTs, while non-browser
            # clients send neither. The signed session cookie remains
            # the barrier for those; see deploy/README.md.
            if request.headers.get("sec-fetch-site") == "cross-site":
                return PlainTextResponse(
                    "Cross-site request refused.", status_code=403
                )
            presented = request.headers.get("origin") or request.headers.get(
                "referer"
            )
            if presented is not None:
                expected = request.url.hostname or ""
                actual = urlsplit(presented).hostname or ""
                if actual != expected:
                    return PlainTextResponse(
                        "Cross-site request refused.", status_code=403
                    )
        return await call_next(request)


def create_app(
    catalog_path: str | Path,
    workspace_root: str | Path,
    database_url: str,
    site_root: str | Path | None = None,
) -> FastAPI:
    """Compose the reading and review room over shared use cases."""
    registry = load_catalog(Path(catalog_path))
    workspace = Workspace(Path(workspace_root))
    database = Database(database_url)
    database.prepare()
    working_copies = SqlAlchemyWorkingCopyRepository(database)
    job_store = SqlAlchemyTranslationJobRepository(database)
    auth = build_auth_state(
        os.environ.get("NOVEL_TRANSLATOR_AUTH_PASSWORD_HASH"),
        os.environ.get("NOVEL_TRANSLATOR_SESSION_SECRET"),
    )
    services = Services(
        registry=registry,
        list_dashboard=ListDashboard(registry, workspace, working_copies),
        list_chapters=ListChapters(registry, workspace, working_copies),
        resolve_chapter=ResolveChapter(registry, workspace, working_copies),
        read_chapter_for_review=ReadChapterForReview(
            registry, workspace, working_copies
        ),
        list_revisions=ListRevisions(workspace),
        get_diff=GetDiff(workspace),
        approve_artifact=ApproveArtifact(workspace),
        revoke_approval=RevokeApproval(workspace),
        export_artifact=ExportArtifact(workspace, FilesystemArtifactWriter()),
        get_working_copy=GetWorkingCopy(working_copies),
        start_working_copy=StartWorkingCopy(workspace, working_copies),
        save_working_copy=SaveWorkingCopy(working_copies),
        discard_working_copy=DiscardWorkingCopy(working_copies),
        get_working_copy_diff=GetWorkingCopyDiff(workspace, working_copies),
        create_revision_from_working_copy=CreateRevisionFromWorkingCopy(
            workspace, working_copies
        ),
        enqueue_translation=EnqueueTranslation(job_store),
        get_translation_job=GetTranslationJob(job_store),
        list_translation_jobs=ListTranslationJobs(job_store),
        cancel_translation_job=RequestJobCancellation(job_store),
        retry_translation_job=RetryTranslationJob(job_store),
        site_root=Path(site_root).resolve() if site_root is not None else None,
    )
    app = FastAPI(
        title="Novel Translator",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.auth = auth
    app.state.services = services
    templates = Jinja2Templates(directory=str(TEMPLATES))
    _register_filters(templates)
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    app.include_router(auth_router)
    app.include_router(translate_router)
    app.include_router(routes.router)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(_OriginCheckMiddleware)

    async def _healthz() -> PlainTextResponse:
        """Answer orchestrator probes without templates or state."""
        return PlainTextResponse("ok")

    app.add_api_route("/healthz", _healthz, include_in_schema=False)

    async def _application_error(
        request: Request, error: NovelTranslatorError
    ) -> HTMLResponse:
        """Render expected application failures as orienting pages."""
        message = str(error) or "The requested action is not available."
        if routes.wants_partial(request):
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": message, "kind": "warn"},
                status_code=_status_for(error),
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "status": _status_for(error)},
            status_code=_status_for(error),
        )

    async def _http_error(
        request: Request, error: StarletteHTTPException
    ) -> HTMLResponse:
        """Render missing pages in the same editorial voice."""
        detail = error.detail
        message = (
            detail if detail != "Not Found" else "This page does not exist."
        )
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "status": error.status_code},
            status_code=error.status_code,
        )

    app.exception_handler(NovelTranslatorError)(_application_error)
    app.exception_handler(StarletteHTTPException)(_http_error)

    return app


def main() -> None:
    """Run the web room from environment configuration."""
    load_dotenv(Path.cwd() / ".env", override=False)
    workspace = Path(
        os.environ.get("NOVEL_TRANSLATOR_WORKSPACE", ".novel-translator")
    )
    database_url = os.environ.get(
        "NOVEL_TRANSLATOR_DATABASE",
        f"sqlite:///{(workspace / 'working-copies.sqlite').as_posix()}",
    )
    site_root = os.environ.get("NOVEL_TRANSLATOR_SITE_ROOT")
    app = create_app(
        catalog_path=os.environ.get("NOVEL_TRANSLATOR_CATALOG", "novels.yaml"),
        workspace_root=workspace,
        database_url=database_url,
        site_root=site_root,
    )
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("NOVEL_TRANSLATOR_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("NOVEL_TRANSLATOR_WEB_PORT", "8000")),
        # Traefik terminates TLS in front of this pod, so the client IP
        # and scheme come from its proxy headers. The pod is reachable
        # only through the ClusterIP service, never directly.
        forwarded_allow_ips="*",
    )
