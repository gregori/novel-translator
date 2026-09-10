"""Tests for approved artifact publication as site pull requests."""

from pathlib import Path

import pytest
from test_catalog import create_registry

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
)
from novel_translator.application.export import (
    ExportHistoryInput,
    ListExportHistory,
)
from novel_translator.application.publish import (
    PublishExport,
    PublishExportInput,
    PublishOutcome,
    PublishResult,
)
from novel_translator.domain.errors import ApprovalRequired, PublicationError
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text

RUN_ID = "c" * 32
DRAFT = "Chapter 1: A New Dawn\n\nBody."


class FakePublisher:
    """Record publication calls without touching the network."""

    def __init__(
        self,
        outcome: PublishOutcome | None = None,
        error: PublicationError | None = None,
        read_content: str | None = None,
    ) -> None:
        self.calls: list[dict[str, str]] = []
        self.read_calls: list[dict[str, str]] = []
        self._outcome = outcome
        self._error = error
        self._read_content = read_content

    def read(self, *, repository: str, path: str) -> str | None:
        """Record one read and return the staged file content."""
        self.read_calls.append({"repository": repository, "path": path})
        return self._read_content

    def publish(
        self,
        *,
        repository: str,
        path: str,
        content: str,
        branch: str,
        title: str,
        body: str,
    ) -> PublishOutcome:
        self.calls.append(
            {
                "repository": repository,
                "path": path,
                "content": content,
                "branch": branch,
                "title": title,
                "body": body,
            }
        )
        if self._error is not None:
            raise self._error
        if self._outcome is not None:
            return self._outcome
        return PublishOutcome(
            git_commit="deadbeef",
            pull_request_url="https://github.com/gregori/novels-site/pull/1",
            branch=branch,
            created=True,
        )


def make_workspace(root: Path) -> Workspace:
    """Persist one approved draft run under a workspace root."""
    run_dir = root / "runs" / RUN_ID

    run_dir.mkdir(parents=True)
    (run_dir / "draft.md").write_text(DRAFT, encoding="utf-8")
    (run_dir / "draft.sha256").write_text(sha256_text(DRAFT), encoding="utf-8")
    (run_dir / "run.json").write_text(
        '{"identity": {"chapter": 1}}', encoding="utf-8"
    )
    return Workspace(root)


def publish(
    workspace: Workspace,
    publisher: FakePublisher,
    tmp_path: Path,
    revision_id: str | None = None,
) -> PublishResult:
    """Publish an approved draft through the public use case."""
    registry = create_registry(tmp_path)
    ApproveArtifact(workspace).execute(
        ArtifactApprovalInput(RUN_ID, revision_id)
    )
    return PublishExport(workspace, registry, publisher).execute(
        PublishExportInput(
            run_id=RUN_ID,
            novel="test-novel",
            chapter=1,
            revision_id=revision_id,
        )
    )


def test_publish_opens_pull_request_for_approved_artifact(
    tmp_path: Path,
) -> None:
    """Publication renders approved Markdown onto a deterministic branch."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    publisher = FakePublisher()

    result = publish(workspace, publisher, catalog_root)

    assert len(publisher.calls) == 1
    call = publisher.calls[0]
    assert call["repository"] == "gregori/novels-site"
    assert call["path"] == "src/content/novels/test-novel/001.md"
    assert call["branch"] == result.branch
    assert call["branch"].startswith("novel-translator/test-novel-ch1-")
    assert 'chapterTitle: "Chapter 1: A New Dawn"' in call["content"]
    assert result.pull_request_url == (
        "https://github.com/gregori/novels-site/pull/1"
    )
    assert result.created is True

    history = ListExportHistory(workspace).execute(ExportHistoryInput(RUN_ID))
    assert len(history) == 1
    event = history[0]
    assert event.git_commit == "deadbeef"
    assert event.pull_request_url == result.pull_request_url
    assert event.destination == (
        "gregori/novels-site/src/content/novels/test-novel/001.md"
    )
    assert event.content_hash == result.content_hash


def test_publish_requires_current_approval(tmp_path: Path) -> None:
    """Unapproved artifacts never reach the publisher or the ledger."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    publisher = FakePublisher()
    registry = create_registry(catalog_root)

    with pytest.raises(ApprovalRequired):
        PublishExport(workspace, registry, publisher).execute(
            PublishExportInput(run_id=RUN_ID, novel="test-novel", chapter=1)
        )

    assert publisher.calls == []
    history = ListExportHistory(workspace).execute(ExportHistoryInput(RUN_ID))
    assert history == ()


def test_publish_reuses_prior_pr_url_on_idempotent_retry(
    tmp_path: Path,
) -> None:
    """A short-circuit without a fresh PR keeps the original link."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    registry = create_registry(catalog_root)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    first = PublishExport(workspace, registry, FakePublisher()).execute(
        PublishExportInput(run_id=RUN_ID, novel="test-novel", chapter=1)
    )
    retry_publisher = FakePublisher(
        outcome=PublishOutcome(
            git_commit="basehead",
            pull_request_url=None,
            branch=first.branch,
            created=False,
        )
    )
    retry = PublishExport(workspace, registry, retry_publisher).execute(
        PublishExportInput(run_id=RUN_ID, novel="test-novel", chapter=1)
    )
    assert retry.created is False
    assert retry.pull_request_url == first.pull_request_url
    assert retry.branch == first.branch


def test_publish_failure_records_no_provenance(tmp_path: Path) -> None:
    """A GitHub failure leaves approvals untouched and appends nothing."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    registry = create_registry(catalog_root)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    publisher = FakePublisher(error=PublicationError("GitHub is down."))

    with pytest.raises(PublicationError):
        PublishExport(workspace, registry, publisher).execute(
            PublishExportInput(run_id=RUN_ID, novel="test-novel", chapter=1)
        )
    history = ListExportHistory(workspace).execute(ExportHistoryInput(RUN_ID))
    assert history == ()
    assert workspace.approvals.is_artifact_approved(
        workspace.runs.generated_draft(RUN_ID), RUN_ID
    )


def test_publish_reuses_live_publish_date_for_stable_retries(
    tmp_path: Path,
) -> None:
    """A retry renders the same bytes as the live site file."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    registry = create_registry(catalog_root)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    live = (
        '---\nchapterTitle: "Chapter 1: A New Dawn"\n'
        "publishDate: 2026-01-01\n---\n\nChapter 1: A New Dawn\n\nBody.\n"
    )
    publisher = FakePublisher(read_content=live)
    PublishExport(workspace, registry, publisher).execute(
        PublishExportInput(run_id=RUN_ID, novel="test-novel", chapter=1)
    )
    assert "publishDate: 2026-01-01" in publisher.calls[0]["content"]
    assert publisher.read_calls == [
        {
            "repository": "gregori/novels-site",
            "path": "src/content/novels/test-novel/001.md",
        }
    ]


def test_publish_explicit_date_wins_over_live_date(tmp_path: Path) -> None:
    """An explicit date overrides the live site file date."""
    workspace = make_workspace(tmp_path / "workspace")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    registry = create_registry(catalog_root)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    live = (
        '---\nchapterTitle: "Chapter 1: A New Dawn"\n'
        "publishDate: 2026-01-01\n---\n\nChapter 1: A New Dawn\n\nBody.\n"
    )
    publisher = FakePublisher(read_content=live)
    PublishExport(workspace, registry, publisher).execute(
        PublishExportInput(
            run_id=RUN_ID,
            novel="test-novel",
            chapter=1,
            publish_date="2026-02-02",
        )
    )
    assert "publishDate: 2026-02-02" in publisher.calls[0]["content"]
