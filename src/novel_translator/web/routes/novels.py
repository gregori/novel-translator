"""Novel registration routes: the web form for RegisterNovel."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from novel_translator.application.novels import RegisterNovelInput
from novel_translator.domain.errors import (
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.web.services import Services

router = APIRouter()

MAX_UPLOAD_BYTES = 1_000_000
"""Largest accepted bible or source upload; bibles are tens of kilobytes."""
MAX_SOURCE_FILES = 32
"""Largest accepted source batch; registrations seed a few chapters."""
MAX_SOURCE_BYTES = 8_000_000
"""Largest accepted total source bytes per registration request."""
_DEFAULT_PROVIDER = "opencode-go"
_DEFAULT_EXPORT_REPOSITORY = "gregori/novels-site"
_DEFAULT_FILENAME_TEMPLATE = "{chapter:03}.md"
_EXAMPLE_BIBLE_PATH = (
    Path(__file__).resolve().parents[4]
    / "config"
    / "translation-bible.example.yaml"
)
_FALLBACK_BIBLE = (
    "title: Example Novel\n"
    "source_language: ja\n"
    "target_language: en\n"
    "characters:\n"
    "  - name: Haru\n"
    "    aliases: [Haru-kun]\n"
    "terminology:\n"
    "  \u9b54\u6cd5: magic\n"
    "honorific_rules:\n"
    "  - Preserve meaningful honorifics.\n"
    "naming_conventions:\n"
    "  - Use canonical character names.\n"
    "style_instructions:\n"
    "  - Use natural English prose.\n"
)


def _services(request: Request) -> Services:
    """Read the shared composition container from the request."""
    return request.app.state.services


def _templates(request: Request):  # type: ignore[no-untyped-def]
    """Read the shared template renderer from the request."""
    return request.app.state.templates


def _example_bible() -> str:
    """Return the shipped example bible for the registration form."""
    try:
        return _EXAMPLE_BIBLE_PATH.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return _FALLBACK_BIBLE


def _defaults() -> dict[str, str]:
    """Return blank registration defaults with gariben-sensible presets."""
    return {
        "novel_id": "",
        "title": "",
        "provider": _DEFAULT_PROVIDER,
        "model": "",
        "volume": "",
        "kakuyomu_work": "",
        "export_repository": _DEFAULT_EXPORT_REPOSITORY,
        "export_directory": "",
        "export_filename_template": _DEFAULT_FILENAME_TEMPLATE,
        "bible_text": _example_bible(),
    }


def _parse_volume(value: str) -> int | None:
    """Turn the optional volume field into an int or fail orienting."""
    text = value.strip()
    if not text:
        return None
    try:
        number = int(text)
    except ValueError as error:
        raise ValidationError("Volume must be a positive number.") from error
    if number < 1:
        raise ValidationError("Volume must be a positive number.")
    return number


def _kakuyomu_root(value: str) -> str | None:
    """Turn a Kakuyomu work URL into the catalog episode root."""
    text = value.strip().rstrip("/")
    if not text:
        return None
    if text.endswith("/episodes"):
        return text
    return f"{text}/episodes"


def _read_upload(upload: UploadFile | None, label: str) -> str | None:
    """Read an uploaded text file within size and encoding limits."""
    if upload is None:
        return None
    name = upload.filename or ""
    if not name:
        return None
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError(f"{label} must be at most 1 MB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{label} must be valid UTF-8.") from error
    if not text.strip():
        raise ValidationError(f"{label} must not be empty.")
    return text


@router.get("/novels/new", response_class=HTMLResponse)
def novel_new_form(request: Request) -> HTMLResponse:
    """Render the novel registration form with sensible defaults."""
    return _templates(request).TemplateResponse(
        request,
        "novels_new.html",
        {"values": _defaults(), "error": None},
    )


@router.post("/novels/new", response_class=HTMLResponse)
def novel_new_submit(  # noqa: C901
    request: Request,
    novel_id: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    provider: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    volume: Annotated[str, Form()] = "",
    kakuyomu_work: Annotated[str, Form()] = "",
    export_repository: Annotated[str, Form()] = "",
    export_directory: Annotated[str, Form()] = "",
    export_filename_template: Annotated[str, Form()] = "",
    bible_text: Annotated[str, Form()] = "",
    bible_upload: Annotated[UploadFile | None, File()] = None,
    source_files: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    """Register one novel, then open its chapter listing."""
    values = {
        "novel_id": novel_id.strip(),
        "title": title.strip(),
        "provider": provider.strip(),
        "model": model.strip(),
        "volume": volume.strip(),
        "kakuyomu_work": kakuyomu_work.strip(),
        "export_repository": export_repository.strip(),
        "export_directory": export_directory.strip(),
        "export_filename_template": export_filename_template.strip(),
        "bible_text": bible_text,
    }
    try:
        pasted = bible_text.strip()
        uploaded = _read_upload(bible_upload, "Bible file")
        if pasted and uploaded is not None:
            raise ValidationError(
                "Provide either bible text or a bible file, not both."
            )
        bible = pasted or uploaded
        if not bible:
            raise ValidationError(
                "Provide a translation bible via text or file upload."
            )
        candidates = [u for u in (source_files or []) if u.filename]
        if len(candidates) > MAX_SOURCE_FILES:
            raise ValidationError(
                "At most 32 source files per registration. "
                "Register the novel first, then add chapters later."
            )
        sources: dict[str, str] = {}
        total = 0
        for upload in candidates:
            name = upload.filename or ""
            content = _read_upload(upload, f"Source file '{name}'")
            if content is not None:
                total += len(content.encode("utf-8"))
                if total > MAX_SOURCE_BYTES:
                    raise ValidationError(
                        "Source files must total at most 8 MB "
                        "per registration."
                    )
                sources[name] = content
        result = _services(request).register_novel.execute(
            RegisterNovelInput(
                novel_id=values["novel_id"],
                title=values["title"],
                model=values["model"],
                export_repository=values["export_repository"]
                or _DEFAULT_EXPORT_REPOSITORY,
                bible_text=bible,
                source_files=sources or None,
                kakuyomu_episode_root=_kakuyomu_root(values["kakuyomu_work"]),
                provider=values["provider"] or _DEFAULT_PROVIDER,
                default_volume=_parse_volume(values["volume"]),
                export_directory=values["export_directory"] or None,
                export_filename_template=(
                    values["export_filename_template"]
                    or _DEFAULT_FILENAME_TEMPLATE
                ),
            )
        )
    except NovelTranslatorError as error:
        return _templates(request).TemplateResponse(
            request,
            "novels_new.html",
            {"values": values, "error": str(error)},
            status_code=400,
        )
    return RedirectResponse(f"/novels/{result.novel_id}", status_code=303)
