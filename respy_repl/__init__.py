"""Public API for the RestrictedPython-based safe REPL (``ResPy`` variant).

This module re-exports the key symbols that an embedding application (e.g. a
Discord bot) needs:

* ``PermissionLevel``, ``Permissions`` – policy configuration.
* ``SafeSession`` – stateful execution context with sync and async ``exec``.
* ``CommandRegistry`` – extensible REPL command registry.
* ``exec_restricted``, ``ExecResult`` – low-level execution primitives.
* ``main`` – CLI entry-point.
* ``SafeReplImportError``, ``SafeReplCliArgError`` – user-facing exceptions.
"""

from .cli import main
from .engine import ExecResult, exec_restricted
from .imports import SafeReplCliArgError, SafeReplImportError
from .policy import PermissionLevel, Permissions
from .repl_command_registry import CommandRegistry
from .session import SafeSession

__all__ = (
    "PermissionLevel",
    "Permissions",
    "SafeSession",
    "CommandRegistry",
    "exec_restricted",
    "ExecResult",
    "main",
    "SafeReplImportError",
    "SafeReplCliArgError",
)
