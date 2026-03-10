"""Permission model and runtime policy objects for safe_repl.

This module defines behavior-oriented policy types (`PermissionLevel`,
`Permissions`) while static level tables live in `safe_repl.policy_tables`.
"""

import ast
import builtins
from enum import IntEnum
import warnings

from .policy_tables import (
    DEFAULT_ALLOWED_NODES,
    DEFAULT_ALLOWED_SYMBOLS,
    DEFAULT_BLOCKED_NODES,
    DEFAULT_BLOCKED_SYMBOLS,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
)


class PermissionLevel(IntEnum):
    """Permission levels ordered from most restrictive to most permissive.

    Design invariants (DO NOT BREAK):
    - Level `0` must always be the MOST RESTRICTIVE level
      (used as fallback for invalid input).
    - The last enum member (highest numeric value) should always be the
      LEAST RESTRICTIVE level.
    - `LIMITED` should remain the default for constructor/CLI when no level
      is specified.
    - Ordering allows numeric comparisons, for example:
      `level >= PermissionLevel.LIMITED` means
      "at least limited permissions".

    These invariants allow adding/changing permission levels without refactoring
    fallback/default logic.
    """

    MINIMUM = 0
    LIMITED = 1
    PERMISSIVE = 2
    UNSUPERVISED = 3

    @classmethod
    def _missing_(cls, value: object) -> "PermissionLevel | None":
        """Normalize unsupported enum inputs and fall back to level `0`.

        Accepts case-insensitive names and numeric strings; all other values
        warn and resolve to `cls(0)`.
        """
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                try:
                    return cls[normalized.upper()]
                except KeyError:
                    try:
                        return cls(int(normalized))
                    except ValueError:
                        pass

        valid = ", ".join(f"{level.value} ({level.name})" for level in cls)
        warnings.warn(
            f"Invalid permission level {value}. Use one of: {valid}. Defaulting to {cls(0).name}.",
            stacklevel=2,
        )
        return cls(0)


class Permissions:
    """Resolved execution policy for one evaluator/session context.

    A `Permissions` object combines a baseline permission level with optional
    allow/block overrides and import injections, then computes concrete symbol
    and AST constraints used by the validator/execution engine.
    
    Args: (all optional with defaults)
    - `base_perms`: Baseline permission level to build from.
    - `allow_symbols`: Additional built-in symbols to allow beyond the baseline.
    - `block_symbols`: Built-in symbols to block beyond the baseline.
    - `allow_nodes`: Additional AST node types to allow beyond the baseline.
    - `block_nodes`: AST node types to block beyond the baseline.
    - `imports`: Mapping of symbol names to objects to inject into the execution environment as imports.
    - `timeout_seconds`: Optional execution timeout in seconds (float('inf') for no timeout).
    - `memory_limit_bytes`: Optional memory limit in bytes (float('inf') for no limit).

    Defaults:
    - `base_perms` defaults to `PermissionLevel.LIMITED`.
    - All other args default to empty sets/dicts or `None` (which resolves to level defaults for time/memory).
    """

    def __init__(
        self,
        base_perms: PermissionLevel = PermissionLevel.LIMITED,
        allow_symbols: set[str] | None = None,
        block_symbols: set[str] | None = None,
        allow_nodes: set[type[ast.AST]] | None = None,
        block_nodes: set[type[ast.AST]] | None = None,
        imports: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
        memory_limit_bytes: int | None = None,
    ):
        """Build a policy from level defaults plus optional overrides."""
        allow_symbols = allow_symbols or set()
        block_symbols = block_symbols or set()
        allow_nodes = allow_nodes or set()
        block_nodes = block_nodes or set()
        imports = imports or {}

        self.level = base_perms
        self.modified = bool(allow_symbols or block_symbols or allow_nodes or block_nodes)
        self.set_timeout_seconds(
            DEFAULT_TIMEOUT_SECONDS[self.level] if timeout_seconds is None else timeout_seconds
        )  # Use setter to ensure proper semantics
        self.memory_limit_bytes = (
            DEFAULT_MEMORY_LIMIT_BYTES[self.level]
            if memory_limit_bytes is None
            else memory_limit_bytes
        )

        blocked_symbols = DEFAULT_BLOCKED_SYMBOLS[self.level] | block_symbols
        self.allowed_symbols = (
            DEFAULT_ALLOWED_SYMBOLS[self.level] | allow_symbols
        ) - blocked_symbols
        if self.level >= PermissionLevel.PERMISSIVE:
            self.allowed_symbols.add("__build_class__")
        self.imported_symbols = set(imports) - blocked_symbols
        self.allowed_symbols |= self.imported_symbols

        builtins_map = builtins.__dict__
        self.globals_dict: dict[str, object] = {"__name__": "__safe_repl__"}
        self.globals_dict["__builtins__"] = {
            name: builtins_map[name]
            for name in self.allowed_symbols
            if name in builtins_map
        }
        self.globals_dict.update(
            {name: obj for name, obj in imports.items() if name not in blocked_symbols}
        )

        self.allowed_nodes = (
            (DEFAULT_ALLOWED_NODES[self.level] | allow_nodes)
            - (DEFAULT_BLOCKED_NODES[self.level] | block_nodes)
        )
        self.allowed_node_tuple = tuple(self.allowed_nodes)  # Efficient isinstance checks.

    def __str__(self) -> str:
        """Return a compact human-readable summary of active policy."""
        name = self.level.name.lower() + (" (custom)" if self.modified else "")
        if not self.imported_symbols:
            return name
        if len(self.imported_symbols) <= 3:
            return f"{name} with imports: {', '.join(sorted(self.imported_symbols))}"
        return f"{name} with {len(self.imported_symbols)} imports"

    def set_timeout_seconds(self, seconds: float | None) -> None:
        """Set this instance's execution timeout in seconds (None for no timeout)."""
        # Convert timeout to `Connection.poll` timeout semantics.
        if seconds is None or seconds == float("inf"):
            self.timeout_seconds = None
            return
        self.timeout_seconds = max(seconds, 0.0)

    def set_memory_limit_bytes(self, bytes_limit: int) -> None:
        """Override this instance's memory limit in bytes."""
        self.memory_limit_bytes = bytes_limit

__all__ = (
    "PermissionLevel",
    "Permissions",
)
