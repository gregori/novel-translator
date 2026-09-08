"""Regression tests for the Phase 5 review findings: guarded queue."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_translate_web import build_client as build_web_client

from novel_translator.application.jobs import (
    EnqueueTranslation,
    EnqueueTranslationInput,
    RequestJobCancellation,
    RequestJobCancellationInput,
    RetryTranslationJob,
    RetryTranslationJobInput,
)
from novel_translator.domain.errors import IntegrityError, ValidationError
from novel_translator.domain.jobs import (
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.jobs import (
    SqlAlchemyTranslationJobRepository,
)
from novel_translator.web.app import create_app


def build_store(tmp_path: Path) -> SqlAlchemyTranslationJobRepository:
    """Persist jobs in an isolated migrated SQLite database."""
    database = Database(f"sqlite:///{(tmp_path / 'jobs.sqlite').as_posix()}")
    database.prepare()
    return SqlAlchemyTranslationJobRepository(database)


def enqueue(
    store: SqlAlchemyTranslationJobRepository, chapter: int = 1
) -> TranslationJob:
    """Queue one upload job for the shared test novel."""
    return EnqueueTranslation(store).execute(
        EnqueueTranslationInput(
            novel="novel",
            chapter=chapter,
            provider="opencode-go",
            model="catalog-model",
            source_kind=JobSourceKind.UPLOAD,
            source_ref="chapter-1.md",
            source_text="原文テキスト",
        )
    )


def test_cancel_lost_to_claim_falls_back_to_flag(
    tmp_path: Path,
) -> None:
    """A cancel racing a worker claim flags instead of vanishing."""
    store = build_store(tmp_path)
    job = enqueue(store)
    claimed = store.claim_queued()
    assert claimed is not None
    cancelled = RequestJobCancellation(store).execute(
        RequestJobCancellationInput(job.job_id)
    )
    assert cancelled.status == JobStatus.CANCEL_REQUESTED
    assert cancelled.cancel_requested


def test_terminal_writes_reject_a_settled_row(tmp_path: Path) -> None:
    """Finish and cancel never overwrite each other's terminal state."""
    store = build_store(tmp_path)
    job = enqueue(store)
    store.claim_queued()
    store.finish(job.job_id, "a" * 32)
    with pytest.raises(IntegrityError):
        store.request_cancel(job.job_id)
    with pytest.raises(IntegrityError):
        store.mark_cancelled(job.job_id)

    second = enqueue(store, chapter=2)
    store.claim_queued()
    store.mark_cancelled(second.job_id)
    with pytest.raises(IntegrityError):
        store.finish(second.job_id, "b" * 32)


def test_duplicate_active_chapter_is_rejected(tmp_path: Path) -> None:
    """A second job for the same chapter waits for the first to settle."""
    store = build_store(tmp_path)
    enqueue(store)
    with pytest.raises(ValidationError, match="already has"):
        enqueue(store)
    queued = store.claim_queued()
    assert queued is not None
    with pytest.raises(ValidationError, match="already has"):
        enqueue(store)
    store.mark_cancelled(queued.job_id)
    retry = RetryTranslationJob(store).execute(
        RetryTranslationJobInput(queued.job_id)
    )
    assert retry.parent_job_id == queued.job_id
    assert retry.attempt == queued.attempt + 1
    with pytest.raises(ValidationError, match="already has"):
        enqueue(store)


def test_listings_skip_source_payloads(tmp_path: Path) -> None:
    """Recent listings never materialize megabyte upload payloads."""
    store = build_store(tmp_path)
    job = enqueue(store)
    complete = store.get(job.job_id)
    assert complete is not None
    assert complete.source_text == "原文テキスト"
    summaries = store.list_recent()
    assert len(summaries) == 1
    assert summaries[0].source_text is None
    active = store.find_active("novel", 1)
    assert active is not None
    assert active.source_text is None
    assert store.find_active("novel", 2) is None


def test_web_duplicate_enqueue_is_rejected(tmp_path: Path) -> None:
    """Double taps on Start redirect to an orienting error, not a twin."""
    client, _ = build_web_client(tmp_path)
    first = client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "1",
            "source_mode": "existing-1",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303
    second = client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "1",
            "source_mode": "existing-1",
        },
    )
    assert second.status_code == 400
    assert "already has" in second.text


def test_half_configured_gate_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One auth secret without the other refuses to boot an open room."""
    from test_translate_web import CATALOG_YAML

    sources = tmp_path / "sources"
    sources.mkdir()
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("NOVEL_TRANSLATOR_AUTH_PASSWORD_HASH", "x" * 10)
    monkeypatch.delenv("NOVEL_TRANSLATOR_SESSION_SECRET", raising=False)
    with pytest.raises(ValueError, match="half-configured"):
        create_app(config, workspace, f"sqlite:///{tmp_path / 'half.sqlite'}")
