"""Typed application errors."""


class NovelTranslatorError(Exception):
    """Base class for expected application failures."""


class ValidationError(NovelTranslatorError):
    """Raised when user-supplied data violates a contract."""


class IntegrityError(NovelTranslatorError):
    """Raised when an immutable artifact or invariant is violated."""


class ApprovalRequired(NovelTranslatorError):
    """Raised when an export lacks a current approval."""


class CollisionRequired(NovelTranslatorError):
    """Raised when export needs explicit replacement confirmation."""
