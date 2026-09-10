"""Shared request helpers for the web routes.

Every helper here is a thin adapter concern: parsing form choices,
resolving friendly selections into run identities, and composing
action URLs. No editorial rule lives in this module.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from novel_translator.application.catalog import ResolveChapterInput
from novel_translator.application.review import ListRevisionsInput
from novel_translator.application.working_copy import GetWorkingCopyInput
from novel_translator.domain.errors import (
    NovelTranslatorError,
    ValidationError,
)
from novel_translator.domain.models import ChapterState, WorkingCopy
from novel_translator.web.services import Services

FLASH_MESSAGES: dict[str, str] = {
    "working-copy": "Working copy ready for edits.",
    "revision-created": "Revision created from your working copy.",
    "discarded": "Working copy discarded — the draft is untouched.",
    "approved": "Approval recorded.",
    "revoked": "Approval revoked.",
    "exported": "Export completed into the site checkout.",
    "published": "Publication pull request opened.",
    "already-published": "Already published — no new pull request needed.",
}


def wants_partial(request: Request) -> bool:
    """Report whether the client asked for an HTML fragment."""
    return request.headers.get("hx-request") == "true" or (
        request.headers.get("x-requested-with") == "fetch"
    )


def require_novel(services: Services, novel: str) -> None:
    """Fail with an orienting 404 for unregistered novels."""
    if not services.novel_registered(novel):
        raise HTTPException(
            status_code=404,
            detail=f"This novel is not registered: {novel}. "
            "Check the novels.yaml catalog.",
        )


def parse_choice(value: str | None) -> int | None:
    """Turn a form/query run choice into an optional ordinal."""
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as error:
        raise ValidationError("Run choice must be a number.") from error


def run_id_for(
    services: Services, novel: str, chapter: int, run_choice: int | None
) -> str:
    """Resolve the friendly selection or raise an orienting error."""
    resolved = services.resolve_chapter.execute(
        ResolveChapterInput(novel, chapter, run_choice)
    )
    if resolved.run_id is None:
        raise NovelTranslatorError(
            "The selected chapter has no translation run yet. "
            "Start one from the CLI."
        )
    return resolved.run_id


def active_copy(services: Services, run_id: str) -> WorkingCopy:
    """Return the run's active working copy or raise an error."""
    copy = services.get_working_copy.execute(GetWorkingCopyInput(run_id))
    if copy is None:
        raise NovelTranslatorError(
            "This chapter has no active working copy. "
            "Start one before saving edits."
        )
    return copy


def stale_session() -> NovelTranslatorError:
    """Return the typed error for a replaced working copy."""
    return NovelTranslatorError(
        "This editing session is stale — the working copy was replaced "
        "or removed elsewhere. Reload the page before editing again."
    )


def revision_id_for(
    services: Services, run_id: str, ordinal: int | None
) -> str | None:
    """Map a displayed revision ordinal to its immutable identifier."""
    if ordinal is None:
        return None
    summaries = services.list_revisions.execute(ListRevisionsInput(run_id))
    if ordinal < 1 or ordinal > len(summaries):
        raise NovelTranslatorError(
            f"Revision choice must be between 1 and {len(summaries)}."
        )
    return summaries[ordinal - 1].record.revision_id


def chapter_urls(
    novel: str, chapter: int, run_choice: int | None
) -> dict[str, str]:
    """Compose every action URL for one chapter page."""
    base = f"/novels/{novel}/chapters/{chapter}"
    suffix = f"?run_choice={run_choice}" if run_choice else ""
    return {
        "page_url": base + suffix,
        "start_url": f"{base}/working-copy{suffix}",
        "save_url": f"{base}/working-copy/save{suffix}",
        "discard_url": f"{base}/working-copy/discard{suffix}",
        "wc_diff_url": f"{base}/working-copy/diff{suffix}",
        "preview_url": f"{base}/working-copy/preview{suffix}",
        "revision_url": f"{base}/revision{suffix}",
        "approval_url": f"{base}/approval{suffix}",
        "revoke_url": f"{base}/approval/revoke{suffix}",
        "export_url": f"{base}/export{suffix}",
        "export_preview_url": f"{base}/export/preview{suffix}",
        "export_download_url": f"{base}/export/download{suffix}",
        "publish_url": f"{base}/publish{suffix}",
    }


def done_url(
    novel: str,
    chapter: int,
    run_choice: int | None,
    event: str,
) -> str:
    """Add a completion marker without corrupting an existing query."""
    page_url = chapter_urls(novel, chapter, run_choice)["page_url"]
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}done={event}"


def redirect_done(
    novel: str,
    chapter: int,
    run_choice: int | None,
    event: str,
) -> RedirectResponse:
    """Redirect to the chapter page with a flash marker."""
    return RedirectResponse(
        done_url(novel, chapter, run_choice, event),
        status_code=303,
    )


def state_or_none(value: str) -> ChapterState | None:
    """Turn a querystring state into an enum or None."""
    if not value:
        return None
    try:
        return ChapterState(value)
    except ValueError:
        return None
