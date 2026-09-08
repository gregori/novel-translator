"""Background worker draining queued translation jobs.

Configuration comes from ``NOVEL_TRANSLATOR_*`` environment variables
read by :func:`main`:

- ``NOVEL_TRANSLATOR_CATALOG`` (default ``novels.yaml``)
- ``NOVEL_TRANSLATOR_WORKSPACE`` (default ``.novel-translator``)
- ``NOVEL_TRANSLATOR_DATABASE`` (default
  ``sqlite:///<workspace>/working-copies.sqlite``)
- ``NOVEL_TRANSLATOR_BASE_URL`` (default ``http://localhost:8080``)
- ``NOVEL_TRANSLATOR_MODEL`` (default ``default``)
- ``NOVEL_TRANSLATOR_API_KEY`` (default empty)
- ``NOVEL_TRANSLATOR_PROVIDER`` (default ``opencode-go``)
- ``NOVEL_TRANSLATOR_REQUEST_TIMEOUT`` (default ``300.0`` seconds)
- ``NOVEL_TRANSLATOR_POLL_SECONDS`` (default ``5.0``)
- ``NOVEL_TRANSLATOR_HEARTBEAT_SECONDS`` (default ``30.0``)
- ``NOVEL_TRANSLATOR_STALE_SECONDS`` (default ``120.0``)
"""

from __future__ import annotations

import os
import threading
import time
from asyncio import CancelledError
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novel_translator.application.jobs import TranslationJobStore
from novel_translator.application.prepare import (
    PrepareTranslation,
    PrepareTranslationInput,
)
from novel_translator.application.translate import (
    StartTranslation,
    StartTranslationInput,
)
from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.jobs import (
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.domain.models import ChapterIdentity
from novel_translator.domain.translation import (
    SourceDocument,
    TranslatorGateway,
)
from novel_translator.infrastructure.catalog import (
    NovelRegistry,
    load_catalog,
)
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.jobs import (
    SqlAlchemyTranslationJobRepository,
)
from novel_translator.infrastructure.providers import (
    OpenCodeGoConfig,
    resolve_provider,
)
from novel_translator.infrastructure.source import (
    load_bible,
    read_source,
)
from novel_translator.infrastructure.workspace import Workspace

GatewayFactory = Callable[[str, OpenCodeGoConfig], TranslatorGateway]
"""Build a live gateway for one claimed job's provider."""

MAX_ERROR_MESSAGE_CHARS = 500
"""Longest error message persisted on a failed job."""


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Typed settings for one translation worker process."""

    catalog_path: Path
    workspace_root: Path
    database_url: str
    base_url: str
    model: str
    api_key: str
    provider: str = "opencode-go"
    request_timeout_seconds: float = 300.0
    poll_seconds: float = 5.0
    heartbeat_seconds: float = 30.0
    stale_seconds: float = 120.0


def _default_gateway(
    provider: str, endpoint: OpenCodeGoConfig
) -> TranslatorGateway:
    """Resolve the configured provider to a live gateway."""
    return resolve_provider(provider, endpoint).gateway


def _parse_moment(value: str | None) -> datetime | None:
    """Parse one stored ISO timestamp without raising."""
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _is_stale(
    job: TranslationJob, current: datetime, stale_seconds: float
) -> bool:
    """Decide whether one active job missed its heartbeat deadline."""
    reference = (
        _parse_moment(job.heartbeat_at)
        or _parse_moment(job.started_at)
        or _parse_moment(job.created_at)
    )
    if reference is None:
        return True
    return (current - reference).total_seconds() > stale_seconds


def recover_stale_jobs(
    store: TranslationJobStore,
    stale_seconds: float,
    *,
    limit: int = 1000,
    now: datetime | None = None,
) -> int:
    """Recover jobs whose heartbeat expired.

    Running jobs become interrupted; jobs with an expired cancel
    request become cancelled. Returns the number of recovered jobs.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    recovered = 0
    for job in store.list_recent(limit):
        if job.status not in (
            JobStatus.RUNNING,
            JobStatus.CANCEL_REQUESTED,
        ):
            continue
        if not _is_stale(job, current, stale_seconds):
            continue
        if job.status == JobStatus.RUNNING:
            store.interrupt(job.job_id)
        else:
            store.mark_cancelled(job.job_id)
        recovered += 1
    return recovered


def _cancel_was_requested(store: TranslationJobStore, job_id: str) -> bool:
    """Check one fresh job row for a cooperative cancel request."""
    fresh = store.get(job_id)
    return fresh is not None and (
        fresh.cancel_requested or fresh.status == JobStatus.CANCEL_REQUESTED
    )


def _watch_progress(
    store: TranslationJobStore, job_id: str, current: int, total: int
) -> None:
    """Persist progress and abort promptly when cancellation arrives."""
    store.update_progress(job_id, current, total)
    if _cancel_was_requested(store, job_id):
        raise CancelledError("Translation job was cancelled.")


def _send_heartbeats(
    store: TranslationJobStore,
    job_id: str,
    interval: float,
    stop: threading.Event,
) -> None:
    """Refresh one running job until the translation finishes."""
    while not stop.wait(interval):
        try:
            store.heartbeat(job_id)
        except Exception:
            return


def _upload_inputs(
    registry: NovelRegistry, job: TranslationJob
) -> tuple[Path, int | None]:
    """Resolve bible and volume for an upload without catalog sources."""
    config = registry.novel(job.novel)
    volume = (
        job.volume
        if job.volume is not None
        else config.translation.default_volume
    )
    return registry.resolve_path(config.bible), volume


def _safe_message(error: BaseException) -> str:
    """Truncate one error message without adding new content."""
    return str(error)[:MAX_ERROR_MESSAGE_CHARS]


def _execute_claimed(
    config: WorkerConfig,
    store: TranslationJobStore,
    job: TranslationJob,
    gateway_factory: GatewayFactory | None,
) -> str:
    """Translate one claimed job and return its persisted run ID."""
    registry = load_catalog(config.catalog_path)
    factory = gateway_factory or _default_gateway
    if job.source_kind == JobSourceKind.UPLOAD:
        if not job.source_text:
            raise ValidationError("Upload job has no source text.")
        bible_path, volume = _upload_inputs(registry, job)
        document = SourceDocument(job.source_text, f"upload:{job.source_ref}")
        provider_name = job.provider
        model_name = job.model
        novel = job.novel
        chapter = job.chapter
    else:
        prepared = PrepareTranslation(registry).execute(
            PrepareTranslationInput(
                novel=job.novel,
                chapter=job.chapter,
                source=(
                    job.source_ref
                    if job.source_kind == JobSourceKind.EXISTING
                    else None
                ),
                episode=(
                    job.source_ref
                    if job.source_kind == JobSourceKind.EPISODE
                    else None
                ),
                provider=job.provider,
                model=job.model,
                volume=job.volume,
            )
        )
        document = read_source(prepared.source)
        bible_path = prepared.bible
        volume = prepared.volume
        provider_name = prepared.provider
        model_name = prepared.model
        novel = prepared.novel
        chapter = prepared.chapter
    bible = load_bible(bible_path)
    gateway = factory(
        provider_name,
        OpenCodeGoConfig(
            base_url=config.base_url,
            model=model_name,
            api_key=config.api_key,
            timeout_seconds=config.request_timeout_seconds,
        ),
    )
    workspace = Workspace(config.workspace_root)
    stop = threading.Event()
    interval = max(config.heartbeat_seconds, 0.1)
    beats = threading.Thread(
        target=_send_heartbeats,
        args=(store, job.job_id, interval, stop),
        daemon=True,
    )
    beats.start()
    try:
        result = StartTranslation(workspace, gateway).execute(
            StartTranslationInput(
                identity=ChapterIdentity(novel, chapter),
                source=document,
                bible=bible,
                provider=provider_name,
                model=model_name,
                volume=volume,
                segment_limit=job.segment_limit,
                progress=(
                    lambda current, total, _a: _watch_progress(
                        store, job.job_id, current, total
                    )
                ),
                retry_notice=(
                    lambda current, total, attempt, error: print(
                        f"job {job.job_id} segment {current}/{total} "
                        f"attempt {attempt}: {type(error).__name__}: "
                        f"{error}",
                        flush=True,
                    )
                ),
            )
        )
    finally:
        stop.set()
        beats.join(timeout=max(interval * 2.0, 1.0))
    return result.run_id


def run_once(
    config: WorkerConfig,
    store: TranslationJobStore,
    gateway_factory: GatewayFactory | None = None,
) -> bool:
    """Claim and translate one queued job; False when idle."""
    claimed = store.claim_queued()
    if claimed is None:
        return False
    job_id = claimed.job_id
    if _cancel_was_requested(store, job_id):
        _settle(store, job_id, store.mark_cancelled)
        return True
    try:
        run_id = _execute_claimed(config, store, claimed, gateway_factory)
    except CancelledError:
        if _cancel_was_requested(store, job_id):
            _settle(store, job_id, store.mark_cancelled)
        else:
            _settle(store, job_id, store.interrupt)
        return True
    except KeyboardInterrupt:
        if _cancel_was_requested(store, job_id):
            _settle(store, job_id, store.mark_cancelled)
        else:
            _settle(store, job_id, store.interrupt)
        raise
    except Exception as error:
        _settle(
            store,
            job_id,
            store.fail,
            type(error).__name__,
            _safe_message(error),
        )
        return True
    try:
        store.finish(job_id, run_id)
    except IntegrityError:
        # Lost a race: cancel arrived after the last progress check.
        # Honor the cancel instead of resurrecting a settled job.
        _settle(store, job_id, store.mark_cancelled)
    return True


def _settle(
    store: TranslationJobStore,
    job_id: str,
    action: Callable[..., object],
    *args: object,
) -> None:
    """Apply one terminal write, tolerating a concurrent settlement."""
    with suppress(IntegrityError):
        action(job_id, *args)


def _env(name: str, default: str) -> str:
    """Read one string variable with a fallback default."""
    value = os.environ.get(name, default)
    return value if value.strip() else default


def _env_float(name: str, default: float) -> float:
    """Read one float variable with a fallback default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _load_config(workspace_default: str = ".novel-translator") -> WorkerConfig:
    """Build worker settings from NOVEL_TRANSLATOR_* variables."""
    workspace = Path(_env("NOVEL_TRANSLATOR_WORKSPACE", workspace_default))
    database_url = os.environ.get("NOVEL_TRANSLATOR_DATABASE", "")
    if not database_url.strip():
        database_url = (
            "sqlite:///" + (workspace / "working-copies.sqlite").as_posix()
        )
    return WorkerConfig(
        catalog_path=Path(_env("NOVEL_TRANSLATOR_CATALOG", "novels.yaml")),
        workspace_root=workspace,
        database_url=database_url,
        base_url=_env("NOVEL_TRANSLATOR_BASE_URL", "http://localhost:8080"),
        model=_env("NOVEL_TRANSLATOR_MODEL", "default"),
        api_key=_env("NOVEL_TRANSLATOR_API_KEY", ""),
        provider=_env("NOVEL_TRANSLATOR_PROVIDER", "opencode-go"),
        request_timeout_seconds=_env_float(
            "NOVEL_TRANSLATOR_REQUEST_TIMEOUT", 300.0
        ),
        heartbeat_seconds=_env_float(
            "NOVEL_TRANSLATOR_HEARTBEAT_SECONDS", 30.0
        ),
        stale_seconds=_env_float("NOVEL_TRANSLATOR_STALE_SECONDS", 120.0),
    )


def main() -> None:
    """Drain queued translation jobs until interrupted."""
    config = _load_config()
    database = Database(config.database_url)
    database.prepare()
    store: TranslationJobStore = SqlAlchemyTranslationJobRepository(database)
    while True:
        try:
            recover_stale_jobs(store, config.stale_seconds)
            if not run_once(config, store):
                time.sleep(config.poll_seconds)
        except KeyboardInterrupt:
            break
        except Exception as error:
            print(f"worker iteration failed: {type(error).__name__}: {error}")
            time.sleep(config.poll_seconds)
