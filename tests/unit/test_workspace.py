"""Tests for shared workspace filesystem and approval persistence."""

from pathlib import Path

import pytest

from novel_translator.domain.errors import ValidationError
from novel_translator.domain.models import ApprovalEvent
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import json_dumps, sha256_text


def test_latest_matching_approval_event_controls_eligibility(
    tmp_path: Path,
) -> None:
    """The latest append-only event wins for exactly one draft hash."""
    workspace = Workspace(tmp_path)
    event = ApprovalEvent(
        "run", sha256_text("Draft"), True, "2026-01-01T00:00:00+00:00"
    )
    workspace.approvals.append_approval(event)
    workspace.approvals.append_approval(
        ApprovalEvent(
            "run", event.draft_hash, False, "2026-01-02T00:00:00+00:00"
        )
    )
    assert not workspace.approvals.is_approved("run", event.draft_hash)


def test_json_serialization_redacts_api_key() -> None:
    """Serializable output never contains secrets."""
    assert "visible" not in json_dumps({"api_key": "visible"})


def test_workspace_rejects_paths_outside_root(tmp_path: Path) -> None:
    """Workspace adapter prevents path traversal."""
    with pytest.raises(ValidationError):
        Workspace(tmp_path).storage.safe(Path("..") / "escape")
