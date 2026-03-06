"""Safe REPL with tiered permission levels for restricted code execution.

Public API is re-exported from focused internal modules:
- Policy: `PermissionLevel`, `Permissions`, limits/tuning helpers
- Engine: `safe_exec`
- Session: `SafeSession`, `repl`
- CLI: `main`
"""

from .cli import main
from .engine import safe_exec
from .imports import (
    SafeReplCliArgError,
    SafeReplImportError,
    parse_import_spec as _parse_import_spec,
    validate_cli_args as _validate_cli_args,
)
from .policy import PermissionLevel, Permissions
from .session import SafeSession, repl

__all__ = [
    "PermissionLevel",
    "Permissions",
    "SafeSession",
    "safe_exec",
    "repl",
    "main",
    "SafeReplImportError",
    "SafeReplCliArgError",
    "_parse_import_spec",
    "_validate_cli_args",
]
