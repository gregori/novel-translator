"""Integration tests for persistent translation jobs and the worker."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

from novel_translator.application.jobs import (
    EnqueueTranslation,
    EnqueueTranslationInput,
    ListTranslationJobs,
    RequestJobCancellation,
    RequestJobCancellationInput,
    RetryTranslationJob,
    RetryTranslationJobInput,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.domain.jobs import (
    JobSourceKind,
    JobStatus,
    TranslationJob,
)
from novel_translator.domain.translation import segment_text
from novel_translator.infrastructure.database import Database
from novel_translator.infrastructure.jobs import (
    SqlAlchemyTranslationJobRepository,
)
from novel_translator.infrastructure.providers import OpenCodeGoConfig
from novel_translator.worker import (
    WorkerConfig,
    recover_stale_jobs,
    run_once,
)

NOVEL = "test-novel"
SOURCE_TEXT = (
    "First paragraph here.\n\nSecond paragraph here.\n\nThird here.\n"
)


def write_catalog(root: Path) -> Path:
    """Write a minimal catalog with bible and export settings."""
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "bible.yaml").write_text("title: Test Novel\n", encoding="utf-8")
    catalog = (
        "novels:\n"
        f"  {NOVEL}:\n"
        "    title: Test Novel\n"
        "    bible: bible.yaml\n"
        "    source_directory: sources\n"
        "    export:\n"
        "      repository: test-repo\n"
        "      directory: out\n"
        "    translation:\n"
        "      provider: opencode-go\n"
        "      model: test-model\n"
    )
    path = root / "catalog.yaml"
    path.write_text(catalog, encoding="utf-8")
    return path


def make_store(
    tmp_path: Path,
) -> SqlAlchemyTranslationJobRepository:
    """Prepare a file database and return its job repository."""
    database = Database(str(tmp_path / "jobs.db"))
    database.prepare()
    return SqlAlchemyTranslationJobRepository(database)


def make_config(tmp_path: Path) -> WorkerConfig:
    """Build a worker config over isolated temporary paths."""
    return WorkerConfig(
        catalog_path=write_catalog(tmp_path / "catalog"),
        workspace_root=tmp_path / "workspace",
        database_url=str(tmp_path / "jobs.db"),
        base_url="http://localhost:1",
        model="test-model",
        api_key="key",
        poll_seconds=0.01,
        heartbeat_seconds=0.05,
        stale_seconds=60.0,
    )


def enqueue(
    store: SqlAlchemyTranslationJobRepository,
    source_ref: str,
    segment_limit: int = 60_000,
    source_kind: JobSourceKind = JobSourceKind.EXISTING,
    source_text: str | None = None,
    chapter: int = 1,
) -> TranslationJob:
    """Enqueue one valid job against the real repository."""
    return EnqueueTranslation(store).execute(
        EnqueueTranslationInput(
            novel=NOVEL,
            chapter=chapter,
            provider="opencode-go",
            model="test-model",
            source_kind=source_kind,
            source_ref=source_ref,
            segment_limit=segment_limit,
            source_text=source_text,
        )
    )


def write_source(tmp_path: Path, content: str = SOURCE_TEXT) -> str:
    """Write one readable source file and return its path."""
    path = tmp_path / "chapter-001.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def fake_gateway(text: str = "Translated.") -> Mock:
    """Build a gateway double returning fixed translations."""
    gateway = Mock()
    gateway.translate.return_value = text
    return gateway


def factory_for(
    gateway: Mock,
) -> Callable[[str, OpenCodeGoConfig], Mock]:
    """Adapt one gateway double to the worker factory signature."""

    def factory(provider: str, endpoint: OpenCodeGoConfig) -> Mock:
        assert provider == "opencode-go"
        assert endpoint.model == "test-model"
        return gateway

    return factory


def test_migration_applies_on_empty_database(tmp_path: Path) -> None:
    """Preparing an empty database creates the job queue table."""
    database = Database(str(tmp_path / "fresh.db"))
    database.prepare()

    connection = sqlite3.connect(tmp_path / "fresh.db")
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        connection.close()

    assert "translation_jobs" in tables
    assert "working_copies" in tables
    assert version == "0002"


def test_claim_is_atomic_sequential(tmp_path: Path) -> None:
    """Two sequential claims win once each, then find nothing."""
    store = make_store(tmp_path)
    first = enqueue(store, write_source(tmp_path))
    second = enqueue(store, write_source(tmp_path), chapter=2)

    assert store.claim_queued() is not None
    first_claim = store.get(first.job_id)
    assert first_claim is not None
    assert first_claim.status == JobStatus.RUNNING
    assert store.claim_queued() is not None
    assert store.get(second.job_id) is not None
    assert store.claim_queued() is None


def test_run_once_translates_and_persists_run(
    tmp_path: Path,
) -> None:
    """A queued job translates end to end and records its run."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    job = enqueue(store, write_source(tmp_path))
    gateway = fake_gateway()

    assert run_once(config, store, factory_for(gateway)) is True

    finished = store.get(job.job_id)
    assert finished is not None
    assert finished.status == JobStatus.SUCCEEDED
    assert finished.run_id is not None
    assert finished.completed_at is not None
    run_file = config.workspace_root / "runs" / finished.run_id / "run.json"
    assert (
        json.loads(run_file.read_text(encoding="utf-8"))["status"]
        == "draft_completed"
    )
    assert run_once(config, store, factory_for(gateway)) is False


def test_run_once_reports_segment_progress(tmp_path: Path) -> None:
    """Progress callbacks persist the final segment counters."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    expected_segments = len(segment_text(SOURCE_TEXT, 30))
    assert expected_segments > 1
    job = enqueue(store, write_source(tmp_path), segment_limit=30)

    assert run_once(config, store, factory_for(fake_gateway())) is True

    finished = store.get(job.job_id)
    assert finished is not None
    assert finished.status == JobStatus.SUCCEEDED
    assert finished.progress_total == expected_segments
    assert finished.progress_current == expected_segments


def test_run_once_records_gateway_failure(tmp_path: Path) -> None:
    """A definitive gateway error fails the job with safe metadata."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    job = enqueue(store, write_source(tmp_path))
    gateway = Mock()
    gateway.translate.side_effect = ValidationError("boom")

    assert run_once(config, store, factory_for(gateway)) is True

    failed = store.get(job.job_id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error_type == "ValidationError"
    assert failed.error_message == "boom"


def test_run_once_cancels_running_job(tmp_path: Path) -> None:
    """A cancel request mid-run settles the job as cancelled."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    job = enqueue(store, write_source(tmp_path), segment_limit=30)
    gateway = Mock()

    def translate(prompt: str) -> str:
        RequestJobCancellation(store).execute(
            RequestJobCancellationInput(job.job_id)
        )
        return "partial"

    gateway.translate.side_effect = translate

    assert run_once(config, store, factory_for(gateway)) is True

    cancelled = store.get(job.job_id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED


def test_cancelled_queued_job_never_runs(tmp_path: Path) -> None:
    """Cancelling a queued job removes it from worker claims."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    job = enqueue(store, write_source(tmp_path))

    RequestJobCancellation(store).execute(
        RequestJobCancellationInput(job.job_id)
    )

    assert run_once(config, store, factory_for(fake_gateway())) is False
    assert store.get(job.job_id) is not None


def test_retry_links_child_and_runs_again(tmp_path: Path) -> None:
    """A failed job seeds a queued child that can succeed."""
    store = make_store(tmp_path)
    config = make_config(tmp_path)
    job = enqueue(store, write_source(tmp_path))
    failing = Mock()
    failing.translate.side_effect = ValidationError("boom")
    assert run_once(config, store, factory_for(failing)) is True

    child = RetryTranslationJob(store).execute(
        RetryTranslationJobInput(job.job_id)
    )

    assert child.parent_job_id == job.job_id
    assert child.status == JobStatus.QUEUED
    assert run_once(config, store, factory_for(fake_gateway())) is True
    retried = store.get(child.job_id)
    assert retried is not None
    assert retried.status == JobStatus.SUCCEEDED
    recent = ListTranslationJobs(store).execute()
    assert {item.job_id for item in recent} >= {
        job.job_id,
        child.job_id,
    }


def test_recover_stale_interrupts_abandoned_job(
    tmp_path: Path,
) -> None:
    """An old heartbeat marks the abandoned job interrupted."""
    store = make_store(tmp_path)
    job = enqueue(store, write_source(tmp_path))
    store.claim_queued()
    store.heartbeat(job.job_id, at="2000-01-01T00:00:00+00:00")

    recovered = recover_stale_jobs(store, stale_seconds=60.0)

    assert recovered == 1
    updated = store.get(job.job_id)
    assert updated is not None
    assert updated.status == JobStatus.INTERRUPTED
    assert recover_stale_jobs(store, stale_seconds=60.0) == 0
