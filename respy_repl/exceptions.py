"""Exception hierarchy for ``respy_repl`` execution and input validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import DisplayArtifact


class SafeReplError(Exception):
    """Base class for public ``respy_repl`` exceptions."""


class SafeReplInputError(SafeReplError, ValueError):
    """Base class for user input/argument validation failures."""


class SafeReplImportError(SafeReplInputError):
    """Raised when an import spec cannot be resolved or is disallowed."""


class SafeReplCliArgError(SafeReplInputError):
    """Raised when CLI arguments are invalid."""


class ExecutionError(SafeReplError, RuntimeError):
    """Base error for execution failures with partial output support.

    Attributes:
        user_message: User-facing message shown by ``str(error)``.
        output: Captured text output generated before failure.
        display_artifacts: Captured rich artifacts generated before failure.
        original_exception: Original exception object raised by execution.
        source_exception_type: Original exception type name, when available.
    """

    def __init__(
        self,
        message: str,
        *,
        output: str = "",
        display_artifacts: list[DisplayArtifact] | None = None,
        original_exception: BaseException | None = None,
        source_exception_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.user_message = message
        self.output = output
        self.display_artifacts = list(display_artifacts or [])
        self.original_exception = original_exception
        self.source_exception_type = (
            source_exception_type
            if source_exception_type is not None
            else (
                type(original_exception).__name__
                if original_exception is not None
                else None
            )
        )


class UserCodeExecutionError(ExecutionError):
    """Execution error raised for non-timeout/non-memory user-code failures."""


class ExecutionTimeoutError(ExecutionError, TimeoutError):
    """Execution error raised when a timeout limit is exceeded."""


class ExecutionMemoryLimitError(ExecutionError, MemoryError):
    """Execution error raised when a memory limit is exceeded."""
