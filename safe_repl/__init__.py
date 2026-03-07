"""Safe REPL with tiered permission levels for restricted code execution.

Public API is re-exported from focused internal modules:
- Policy: `PermissionLevel`, `Permissions`, limits/tuning helpers
- Engine: `safe_exec`
- Session: `SafeSession`, `repl`
- CLI: `main`
"""

from .cli import main
from .engine import safe_exec
from .execution import (
    ExecutionMode,
    safe_exec_process_isolated,
    supports_process_isolation,
)
from .imports import (
    SafeReplCliArgError,
    SafeReplImportError,
    parse_import_spec as _parse_import_spec,
    validate_cli_args as _validate_cli_args,
)
from .policy import PermissionLevel, Permissions
from .session import SafeSession, repl

__all__ = (
    "PermissionLevel",
    "Permissions",
    "ExecutionMode",
    "SafeSession",
    "safe_exec",
    "safe_exec_process_isolated",
    "supports_process_isolation",
    "repl",
    "main",
    "SafeReplImportError",
    "SafeReplCliArgError",
    "_parse_import_spec",
    "_validate_cli_args",
)
