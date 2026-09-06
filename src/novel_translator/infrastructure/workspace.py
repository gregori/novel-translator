"""Composition root for filesystem workspace repositories."""

from pathlib import Path

from novel_translator.infrastructure.approvals import ApprovalRepository
from novel_translator.infrastructure.filesystem import WorkspaceStorage
from novel_translator.infrastructure.revisions import RevisionRepository
from novel_translator.infrastructure.run_reader import RunReader
from novel_translator.infrastructure.runs import RunRepository


class Workspace:
    """Expose cohesive repositories over one persistent workspace root."""

    def __init__(self, root: Path) -> None:
        storage = WorkspaceStorage(root)
        self.storage = storage
        self.runs = RunRepository(storage)
        self.reader = RunReader(storage)
        self.revisions = RevisionRepository(storage)
        self.approvals = ApprovalRepository(storage)
