"""Public API for the RestrictedPython-based safe REPL (``ResPy`` variant).

This module re-exports the key symbols that an embedding application (e.g. a
Discord bot) needs:

* ``PermissionLevel``, ``Permissions`` – policy configuration.
* ``SafeSession`` – stateful execution context with sync and async ``exec``.
* ``ExecutionTimeoutError`` – timeout exception carrying partial outputs.
* ``ExecutionMemoryLimitError`` – memory-limit exception carrying partial outputs.
* ``CommandRegistry`` – extensible REPL command registry.
* ``exec_restricted``, ``ExecResult``, ``DisplayArtifact`` – low-level
    execution primitives.
* ``main`` – CLI entry-point.
* ``SafeReplImportError``, ``SafeReplCliArgError`` – user-facing exceptions.
"""

from .cli import main
from .engine import DisplayArtifact, ExecResult, exec_restricted
from .imports import SafeReplCliArgError, SafeReplImportError
from .policy import PermissionLevel, Permissions
from .repl_command_registry import CommandRegistry
from .session import ExecutionMemoryLimitError, ExecutionTimeoutError, SafeSession

__all__ = (
    "PermissionLevel",
    "Permissions",
    "SafeSession",
    "ExecutionTimeoutError",
    "ExecutionMemoryLimitError",
    "CommandRegistry",
    "exec_restricted",
    "DisplayArtifact",
    "ExecResult",
    "main",
    "SafeReplImportError",
    "SafeReplCliArgError",
)
