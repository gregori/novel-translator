"""Typed application errors."""


class NovelTranslatorError(Exception):
    """Base class for expected application failures."""


class ValidationError(NovelTranslatorError):
    """Raised when user-supplied data violates a contract."""


class IntegrityError(NovelTranslatorError):
    """Raised when an immutable artifact or invariant is violated."""


class TransientProviderError(NovelTranslatorError):
    """Raised when a provider operation may safely be retried."""


class ApprovalRequired(NovelTranslatorError):
    """Raised when an export lacks a current approval."""


class CollisionRequired(NovelTranslatorError):
    """Raised when export needs explicit replacement confirmation."""


class WorkingCopyConflict(NovelTranslatorError):
    """Raised when a working copy save races a newer persisted version.

    Both the persisted state and the stale submission are preserved
    so no content is lost to a silent last-write-wins merge.
    """

    def __init__(
        self,
        current_content: str,
        current_version: int,
        submitted_content: str,
        submitted_version: int,
    ) -> None:
        super().__init__(
            f"Working copy version {submitted_version} is stale; "
            f"current persisted version is {current_version}."
        )
        self.current_content = current_content
        self.current_version = current_version
        self.submitted_content = submitted_content
        self.submitted_version = submitted_version


class PublicationError(NovelTranslatorError):
    """Raised when opening a publication pull request fails upstream."""
