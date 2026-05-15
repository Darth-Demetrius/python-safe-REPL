"""Public API for the RestrictedPython-based safe REPL (``respy_repl``).

This module re-exports the key symbols that an embedding application (e.g. a
Discord bot) needs:

* ``PermissionLevel``, ``Permissions`` – policy configuration.
* ``SafeSession`` – stateful execution context with sync and async ``exec``.
* ``ExecutionError`` – base execution exception carrying partial outputs.
* ``ExecutionTimeoutError`` – timeout exception carrying partial outputs.
* ``ExecutionMemoryLimitError`` – memory-limit exception carrying partial outputs.
* ``UserCodeExecutionError`` – user-code failure with formatted traceback.
* ``CommandRegistry`` – extensible REPL command registry.
* ``exec_restricted``, ``ExecResult``, ``DisplayArtifact`` – low-level
    execution primitives.
* ``main`` – CLI entry-point.
* ``SafeReplError`` and subclasses – user-facing exception hierarchy.
"""

from .cli import main
from .engine import DisplayArtifact, ExecResult, exec_restricted
from .exceptions import (
    ExecutionError,
    ExecutionMemoryLimitError,
    ExecutionTimeoutError,
    SafeReplCliArgError,
    SafeReplError,
    SafeReplImportError,
    UserCodeExecutionError,
)
from .policy import PermissionLevel, Permissions
from .repl_command_registry import CommandRegistry
from .session import SafeSession

__all__ = (
    "PermissionLevel",
    "Permissions",
    "SafeSession",
    "ExecutionError",
    "ExecutionTimeoutError",
    "ExecutionMemoryLimitError",
    "UserCodeExecutionError",
    "CommandRegistry",
    "exec_restricted",
    "DisplayArtifact",
    "ExecResult",
    "main",
    "SafeReplError",
    "SafeReplImportError",
    "SafeReplCliArgError",
)
