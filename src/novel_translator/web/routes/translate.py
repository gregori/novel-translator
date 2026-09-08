"""Translation job routes: enqueue from the web and follow progress."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from novel_translator.application.jobs import (
    EnqueueTranslationInput,
    GetTranslationJobInput,
    RequestJobCancellationInput,
    RetryTranslationJobInput,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.domain.jobs import (
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.domain.translation import DEFAULT_SEGMENT_LIMIT
from novel_translator.web.services import Services

router = APIRouter()

MAX_UPLOAD_BYTES = 1_000_000
"""Largest accepted source upload; chapters are tens of kilobytes."""

_ACTIVE_STATUSES = frozenset(
    {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED}
)


def job_active(job: TranslationJob) -> bool:
    """Report whether one job still changes state in the background."""
    return job.status in _ACTIVE_STATUSES


def _services(request: Request) -> Services:
    """Read the shared composition container from the request."""
    return request.app.state.services


def _templates(request: Request):  # type: ignore[no-untyped-def]
    """Read the shared template renderer from the request."""
    return request.app.state.templates


def _novel_defaults(services: Services) -> list[dict[str, object]]:
    """List registered novels with their catalog translation defaults."""
    novels: list[dict[str, object]] = []
    for novel_id, config in services.registry.config.novels.items():
        novels.append(
            {
                "id": novel_id,
                "title": config.title,
                "provider": config.translation.provider,
                "model": config.translation.model,
                "volume": config.translation.default_volume,
            }
        )
    return sorted(novels, key=lambda item: str(item["id"]))


def _parse_positive(value: str, field: str) -> int | None:
    """Turn an optional form number into an int or fail orienting."""
    text = value.strip()
    if not text:
        return None
    try:
        number = int(text)
    except ValueError as error:
        raise ValidationError(f"{field} must be a positive number.") from error
    if number < 1:
        raise ValidationError(f"{field} must be a positive number.")
    return number


def _chapter(value: str) -> int:
    """Turn the chapter form field into a validated chapter number."""
    chapter = _parse_positive(value, "Chapter")
    if chapter is None:
        raise ValidationError("Chapter must be a positive number.")
    return chapter


def _candidates(
    services: Services, novel: str, chapter: int
) -> tuple[str, ...]:
    """List configured source paths for one novel chapter, if any."""
    try:
        indexed = services.registry.source_candidates(novel)
    except ValidationError:
        return ()
    return tuple(str(path) for path in indexed.get(chapter, ()))


@router.get("/translate", response_class=HTMLResponse)
def translate_form(
    request: Request, novel: str = "", chapter: str = ""
) -> HTMLResponse:
    services = _services(request)
    selected = novel.strip()
    novels = _novel_defaults(services)
    defaults = next((item for item in novels if item["id"] == selected), None)
    chapter_number: int | None = None
    try:
        chapter_number = int(chapter.strip()) if chapter.strip() else None
    except ValueError:
        chapter_number = None
    sources: tuple[str, ...] = ()
    if selected and chapter_number and chapter_number >= 1:
        sources = _candidates(services, selected, chapter_number)
    return _templates(request).TemplateResponse(
        request,
        "translate.html",
        {
            "novels": novels,
            "selected_novel": selected,
            "defaults": defaults,
            "chapter": chapter.strip(),
            "sources": sources,
            "default_segment_limit": DEFAULT_SEGMENT_LIMIT,
        },
    )


def _read_upload(upload: UploadFile | None) -> tuple[str | None, str]:
    """Read an uploaded source file within size and encoding limits."""
    if upload is None or not upload.filename:
        return None, ""
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError("Uploaded source must be at most 1 MB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(
            "Uploaded source must be valid UTF-8."
        ) from error
    if not text.strip():
        raise ValidationError("Uploaded source must not be empty.")
    return text, upload.filename


@router.post("/translate")
def translate_submit(
    request: Request,
    novel: Annotated[str, Form()] = "",
    chapter: Annotated[str, Form()] = "",
    volume: Annotated[str, Form()] = "",
    provider: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    segment_limit: Annotated[str, Form()] = "",
    source_mode: Annotated[str, Form()] = "",
    episode: Annotated[str, Form()] = "",
    upload: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """Enqueue one translation job and follow it to its status page."""
    services = _services(request)
    novel_id = novel.strip()
    if not novel_id:
        raise ValidationError("Select a novel.")
    config = services.registry.novel(novel_id)
    chapter_number = _chapter(chapter)
    mode = source_mode.strip() or "existing-1"
    source_text: str | None = None
    source_ref = ""
    if mode == "upload":
        kind = JobSourceKind.UPLOAD
        source_text, source_ref = _read_upload(upload)
        if source_text is None:
            raise ValidationError("Choose a source file to upload.")
    elif mode == "episode":
        kind = JobSourceKind.EPISODE
        source_ref = episode.strip()
        if not source_ref:
            raise ValidationError("Inform the episode identifier.")
    elif mode.startswith("existing-"):
        kind = JobSourceKind.EXISTING
        candidates = _candidates(services, novel_id, chapter_number)
        if not candidates:
            raise ValidationError(
                "The chapter has no configured source; "
                "upload a file or inform an episode."
            )
        choice = _parse_positive(mode.removeprefix("existing-"), "Source")
        if choice is None or choice > len(candidates):
            raise ValidationError("Select one of the listed sources.")
        source_ref = candidates[choice - 1]
    else:
        raise ValidationError("Unknown source selection.")
    job = services.enqueue_translation.execute(
        EnqueueTranslationInput(
            novel=novel_id,
            chapter=chapter_number,
            provider=provider.strip() or config.translation.provider,
            model=model.strip() or config.translation.model,
            source_kind=kind,
            source_ref=source_ref,
            volume=(
                _parse_positive(volume, "Volume")
                if volume.strip()
                else config.translation.default_volume
            ),
            segment_limit=(
                _parse_positive(segment_limit, "Segment limit")
                if segment_limit.strip()
                else DEFAULT_SEGMENT_LIMIT
            )
            or DEFAULT_SEGMENT_LIMIT,
            source_text=source_text,
        )
    )
    return RedirectResponse(f"/translate/jobs/{job.job_id}", status_code=303)


@router.get("/translate/jobs", response_class=HTMLResponse)
def job_list(request: Request) -> HTMLResponse:
    """List recent translation jobs, newest first."""
    services = _services(request)
    jobs = services.list_translation_jobs.execute()
    return _templates(request).TemplateResponse(
        request,
        "jobs.html",
        {"jobs": jobs, "job_active": job_active},
    )


def _job_or_raise(services: Services, job_id: str) -> TranslationJob:
    """Return one job or fail with an orienting error."""
    return services.get_translation_job.execute(
        GetTranslationJobInput(job_id.strip())
    )


def _job_context(job: TranslationJob) -> dict[str, object]:
    """Build the shared template context for one job page or fragment."""
    return {
        "job": job,
        "active": job_active(job),
        "status_url": f"/translate/jobs/{job.job_id}/status",
        "detail_url": f"/translate/jobs/{job.job_id}",
        "chapter_url": f"/novels/{job.novel}/chapters/{job.chapter}",
    }


@router.get("/translate/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str) -> HTMLResponse:
    """Show one job with live progress while it is active."""
    services = _services(request)
    job = _job_or_raise(services, job_id)
    return _templates(request).TemplateResponse(
        request, "job.html", _job_context(job)
    )


@router.get("/translate/jobs/{job_id}/status", response_class=HTMLResponse)
def job_status(request: Request, job_id: str) -> HTMLResponse:
    """Render the polling fragment for one job's progress block."""
    services = _services(request)
    job = _job_or_raise(services, job_id)
    return _templates(request).TemplateResponse(
        request, "partials/job_status.html", _job_context(job)
    )


@router.post("/translate/jobs/{job_id}/cancel")
def job_cancel(request: Request, job_id: str) -> Response:
    """Cancel a queued job or flag a running job for cancellation."""
    services = _services(request)
    job = services.cancel_translation_job.execute(
        RequestJobCancellationInput(job_id.strip())
    )
    return RedirectResponse(f"/translate/jobs/{job.job_id}", status_code=303)


@router.post("/translate/jobs/{job_id}/retry")
def job_retry(request: Request, job_id: str) -> Response:
    """Enqueue an auditable child retry of one terminal job."""
    services = _services(request)
    job = services.retry_translation_job.execute(
        RetryTranslationJobInput(job_id.strip())
    )
    return RedirectResponse(f"/translate/jobs/{job.job_id}", status_code=303)
