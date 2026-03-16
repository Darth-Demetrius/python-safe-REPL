"""Permission model and runtime policy objects for safe_repl.

This module defines behavior-oriented policy types (`PermissionLevel`,
`Permissions`) while static level tables live in `safe_repl.policy_tables`.
"""

import ast
import builtins
from collections.abc import Mapping
from enum import IntEnum
from typing import Optional
import warnings

from .policy_tables import (
    DEFAULT_ALLOWED_NODES,
    DEFAULT_ALLOWED_SYMBOLS,
    DEFAULT_BLOCKED_NODES,
    DEFAULT_BLOCKED_SYMBOLS,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
)
from .imports import (
    NormalizedImportSpec,
    normalize_validate_imports,
)

__all__ = (
    "PermissionLevel",
    "Permissions",
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
    - `imports`: Import spec strings to normalize/validate for worker-side resolution.
    - `timeout_seconds`: Optional execution timeout in seconds (None for no timeout).
    - `memory_limit_bytes`: Optional memory limit in bytes (None for no limit).

    Defaults:
    - `base_perms` defaults to `PermissionLevel.LIMITED`.
    - All other args default to level defaults.
    """

    def __init__(
        self,
        base_perms: PermissionLevel = PermissionLevel.LIMITED,
        allow_symbols: Optional[ set[str] ] = None,
        block_symbols: Optional[ set[str] ] = None,
        allow_nodes: Optional[ set[type[ast.AST]] ] = None,
        block_nodes: Optional[ set[type[ast.AST]] ] = None,
        imports: Optional[ list[str] ] = None,
        timeout_seconds: Optional[ float ] = ..., #  type: ignore[assignment]
        memory_limit_bytes: Optional[ int ] = ..., #  type: ignore[assignment]
    ):
        """Build a policy from level defaults plus optional overrides."""
        allow_symbols = allow_symbols or set()
        block_symbols = block_symbols or set()
        allow_nodes = allow_nodes or set()
        block_nodes = block_nodes or set()
        imports = imports or []
        self.imports = normalize_validate_imports(imports)

        # Extract imported symbol names and add to allowed symbols
        self.imported_symbols: set[str] = set()
        for spec in self.imports:
            names = spec.get("names", [])
            module_name, module_alias = spec.get("module", ("", ""))

            if not names:
                # Module import without explicit names - add module alias
                if module_alias and isinstance(module_alias, str):
                    self.imported_symbols.add(module_alias)
            elif names[0][0] == "*":
                # Star import - add only the expanded public names directly.
                # The module alias is intentionally NOT added: `module:*` makes
                # symbols directly accessible (e.g. `sqrt(16)`) but does not
                # put the module object itself in scope, avoiding `name.name`
                # style conflicts for modules whose attribute matches their name.
                for import_name, import_alias in names[1:]:
                    self.imported_symbols.add(import_alias)
            else:
                # Explicit imports - add the aliases
                for import_name, import_alias in names:
                    self.imported_symbols.add(import_alias)
        allow_symbols |= self.imported_symbols

        self.level = base_perms
        self.modified = bool(allow_symbols or block_symbols or allow_nodes or block_nodes)
        self.timeout_seconds = (
            DEFAULT_TIMEOUT_SECONDS[self.level]
             if timeout_seconds is ...
             else timeout_seconds
        )
        self.memory_limit_bytes = (
            DEFAULT_MEMORY_LIMIT_BYTES[self.level]
            if memory_limit_bytes is ...
            else memory_limit_bytes
        )

        self.blocked_symbols = DEFAULT_BLOCKED_SYMBOLS[self.level] | block_symbols
        self.allowed_symbols = (
            DEFAULT_ALLOWED_SYMBOLS[self.level] | allow_symbols
        ) - self.blocked_symbols
        if self.level >= PermissionLevel.PERMISSIVE:
            self.allowed_symbols.add("__build_class__")

        builtins_map = builtins.__dict__
        self.globals_dict: dict[str, object] = {"__name__": "__safe_repl__"}
        self.globals_dict["__builtins__"] = {
            name: builtins_map[name]
            for name in self.allowed_symbols
            if name in builtins_map
        }

        self.allowed_nodes = (
            (DEFAULT_ALLOWED_NODES[self.level] | allow_nodes)
            - (DEFAULT_BLOCKED_NODES[self.level] | block_nodes)
        )
        self.allowed_node_tuple = tuple(self.allowed_nodes)  # Efficient isinstance checks.

    def to_relaunch_data(self) -> dict[str, object]:
        """Return a compact payload for restoring this already-built policy.

        Returns:
            A plain-data dictionary containing resolved runtime policy fields.
        """
        return {
            "level": int(self.level),
            "modified": self.modified,
            "allowed_symbols": sorted(self.allowed_symbols),
            "blocked_symbols": sorted(self.blocked_symbols),
            "allowed_nodes": sorted(node.__name__ for node in self.allowed_nodes),
            "imports": list(self.imports),
            "imported_symbols": sorted(self.imported_symbols),
            "timeout_seconds": self.timeout_seconds,
            "memory_limit_bytes": self.memory_limit_bytes,
        }

    @classmethod
    def from_relaunch_data(cls, payload: Mapping[str, object]) -> "Permissions":
        """Restore permissions from ``to_relaunch_data`` output.

        Args:
            payload: Serialized permission payload.

        Returns:
            A reconstructed ``Permissions`` instance.
        """
        restored = cls.__new__(cls)

        restored.level = PermissionLevel(payload["level"])
        restored.modified = bool(payload.get("modified", False))
        restored.timeout_seconds = payload.get("timeout_seconds")
        restored.memory_limit_bytes = payload.get("memory_limit_bytes")

        allowed_symbols = payload.get("allowed_symbols", [])
        blocked_symbols = payload.get("blocked_symbols", [])
        node_names = payload.get("allowed_nodes", [])
        imports = payload.get("imports", [])
        imported_symbols = payload.get("imported_symbols", [])

        restored.allowed_symbols = set(
            allowed_symbols if isinstance(allowed_symbols, list) else []
        )
        restored.blocked_symbols = set(
            blocked_symbols if isinstance(blocked_symbols, list) else []
        )
        restored.allowed_nodes = {
            getattr(ast, name)
            for name in (node_names if isinstance(node_names, list) else [])
        }
        restored.allowed_node_tuple = tuple(restored.allowed_nodes)
        restored.imports = list(imports if isinstance(imports, list) else [])
        restored.imported_symbols = set(
            imported_symbols if isinstance(imported_symbols, list) else []
        )

        builtins_map = builtins.__dict__
        restored.globals_dict = {"__name__": "__safe_repl__"}
        restored.globals_dict["__builtins__"] = {
            name: builtins_map[name]
            for name in restored.allowed_symbols
            if name in builtins_map
        }

        return restored

    def __getstate__(self) -> dict[str, object]:
        """Serialize policy state for pickling."""
        return self.to_relaunch_data()

    def __setstate__(self, state: Mapping[str, object]) -> None:
        """Restore policy state from pickled relaunch payload."""
        restored = self.from_relaunch_data(state)
        self.__dict__.update(restored.__dict__)

    def __str__(self) -> str:
        """Return a compact human-readable summary of active policy."""
        name = self.level.name.lower() + (" (custom)" if self.modified else "")
        if self.imports:
            return f"{name} with {len(self.imports)} imports"
        return name


    def set_limits(self, timeout_seconds: Optional[float] = None, memory_limit_bytes: Optional[int] = None) -> None:
        """
        Set timeout and/or memory limit.
        Minimum timeout is 1 second and minimum memory limit is 1024 bytes to avoid instability.
        Cannot set limits to None during execution.
        """
        if timeout_seconds is not None:
            self.timeout_seconds = max(timeout_seconds, 1)
        if memory_limit_bytes is not None:
            self.memory_limit_bytes = max(memory_limit_bytes, 1024)
