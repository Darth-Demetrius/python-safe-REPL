"""Permission model and runtime policy objects for safe_repl.

This module defines behavior-oriented policy types (`PermissionLevel`,
`Permissions`) while static level tables live in `safe_repl.policy_tables`.
"""

import ast
import builtins
import importlib
from collections.abc import Iterable, Mapping
from enum import IntEnum
from functools import total_ordering
from typing import Any, Optional
import warnings

from .imports import (
    collect_import_symbols,
    imports_intersection,
    imports_union,
    normalize_validate_imports,
    NormalizedImportSpec,
)
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
    - Level `0` = No permissions at all
    - Higher levels include all permissions of lower levels, plus additional capabilities.
    - The last enum member (highest numeric value) should always be the
      LEAST RESTRICTIVE level.
        - Ordering allows numeric comparisons, for example:
            `level >= PermissionLevel.CONTROLLED` means
            "at least controlled permissions".

    These invariants allow adding/changing permission levels without refactoring
    fallback/default or comparison logic.
    """

    NONE = 0
    RESTRICTED = 1
    CONTROLLED = 2
    TRUSTED    = 3

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


@total_ordering
class Permissions:
    """Resolved execution policy for one evaluator/session context.

    A `Permissions` object combines a baseline permission level with optional
    allow/block overrides and import injections, then computes concrete symbol
    and AST constraints used by the validator/execution engine. It is designed
    to be picklable for storage and transport. Setters for immutable fields
    automatically cast values to the correct type for convenience.
    
    Args: (all optional with defaults)
    - `perm_level`: Baseline permission level to build from.
    - `allow_symbols`: Additional built-in symbols to allow beyond the baseline.
    - `block_symbols`: Built-in symbols to block beyond the baseline, overrides `allow`.
    - `allow_nodes`: Additional AST node types to allow beyond the baseline.
    - `block_nodes`: AST node types to block beyond the baseline, overrides `allow`.
    - `imports`: Import spec strings to normalize/validate for worker-side resolution.
    - `can_save`: Whether this permission level allows saving/restoring sessions.
    - `timeout_seconds`: Optional execution timeout in seconds (None for no timeout).
    - `memory_limit_bytes`: Optional memory limit in bytes (None for no limit).

    Defaults:
    - `perm_level` defaults to `0`/`PermissionLevel.NONE`.
    - All other args default based on the provided level.
    """
    _level: PermissionLevel
    _modified: bool
    _allowed_nodes: set[type[ast.AST]]
    _allowed_nodes_tuple: tuple[type[ast.AST], ...]  # Efficient isinstance checks.
    _blocked_nodes: set[type[ast.AST]]
    _imports: NormalizedImportSpec
    _imported_symbols: set[str]
    _allowed_symbols: set[str]
    _blocked_symbols: set[str]
    _can_save: bool
    _timeout_seconds: float | None
    _memory_limit_bytes: int | None
    _globals_dict: dict[str, object]

    def __init__(
        self,
        perm_level: PermissionLevel | int = 0,
        *,
        allow_nodes: Optional[ set[type[ast.AST]] ] = None,
        block_nodes: Optional[ set[type[ast.AST]] ] = None,
        imports: Optional[ list[str] ] = None,
        allow_symbols: Optional[ set[str] ] = None,
        block_symbols: Optional[ set[str] ] = None,
        can_save: Optional[ bool ] = None,
        timeout_seconds: float | None = ...,  # type: ignore[assignment]
        memory_limit_bytes: int | None = ...,  # type: ignore[assignment]
    ):
        """Build a policy from level defaults plus optional overrides."""
        self.level = PermissionLevel(perm_level)
        self.modified = bool(allow_symbols or block_symbols or allow_nodes or block_nodes)

        self.blocked_nodes = DEFAULT_BLOCKED_NODES[self.level] | (block_nodes or set())
        self.allowed_nodes = DEFAULT_ALLOWED_NODES[self.level] | (allow_nodes or set())
        self.allowed_nodes -= self.blocked_nodes  # Block overrides allow.

        self.imports = normalize_validate_imports(imports or [])
        self.imported_symbols = collect_import_symbols(self.imports)

        self.blocked_symbols = DEFAULT_BLOCKED_SYMBOLS[self.level] | (block_symbols or set())
        self.allowed_symbols = DEFAULT_ALLOWED_SYMBOLS[self.level] | (allow_symbols or set())
        self.allowed_symbols |= self.imported_symbols  # Allow imported symbols by default.
        if self.level >= PermissionLevel.CONTROLLED:
            self.allowed_symbols.add("__build_class__")
        self.allowed_symbols -= self.blocked_symbols  # Block overrides allow.

        self.can_save = (
            can_save
            if can_save is not None
            else (self.level >= PermissionLevel.CONTROLLED)
        )
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

        self.build_globals()

    def build_globals(self) -> None:
        """Construct the globals dict for execution based on allowed symbols and imports."""
        builtins_map = builtins.__dict__
        self.globals_dict = {"__name__": "__safe_repl__"}
        self.globals_dict["__builtins__"] = {
            name: builtins_map[name]
            for name in self.allowed_symbols
            if name in builtins_map
        }
        for (module_name, module_alias), names in self.imports.items():
            module = importlib.import_module(module_name)
            if module_alias in self.allowed_symbols:
                self.globals_dict[module_alias] = module
            if not names:
                continue
            for import_name, import_alias in names:
                if import_alias in self.allowed_symbols:
                    self.globals_dict[import_alias] = getattr(module, import_name)

    def set_limits(
        self,
        timeout_seconds: float | None = ...,  # type: ignore[assignment]
        memory_limit_bytes: int | None = ...,  # type: ignore[assignment]
    ) -> None:
        """Set timeout and/or memory limit.
        
        Warning:
        - Changing limits to 0 will effectively disable execution.
        - Changing limits to None will remove that particular constraint.

        Args:
            timeout_seconds: New timeout in seconds.
            memory_limit_bytes: New memory limit in bytes.
        """
        if timeout_seconds is not ...:
            self.modified |= (timeout_seconds != self.timeout_seconds)
            self.timeout_seconds = timeout_seconds

        if memory_limit_bytes is not ...:
            self.modified |= (memory_limit_bytes != self.memory_limit_bytes)
            self.memory_limit_bytes = memory_limit_bytes

    def __copy__(self) -> Permissions:
        """Create a copy of this ``Permissions`` instance."""
        copied = Permissions.__new__(Permissions)
        copied._level = self._level
        copied._modified = self._modified
        copied._allowed_nodes = set(self._allowed_nodes)
        copied._blocked_nodes = set(self._blocked_nodes)
        copied._imports = {
            module: set(names)
            for module, names in self._imports.items()
        }
        copied._imported_symbols = set(self.imported_symbols)
        copied._allowed_symbols = set(self._allowed_symbols)
        copied._blocked_symbols = set(self._blocked_symbols)
        copied._can_save = self._can_save
        copied._timeout_seconds = self._timeout_seconds
        copied._memory_limit_bytes = self._memory_limit_bytes
        copied._globals_dict = dict(self._globals_dict)
        return copied

    def to_relaunch_data(self) -> dict[str, object]:
        """Return a compact payload for restoring this already-built policy.

        Returns:
            A plain-data dictionary containing resolved runtime policy fields.
        """
        return {
            "level": int(self.level),
            "modified": self.modified,

            "allowed_nodes": sorted(node.__name__ for node in self.allowed_nodes),
            "blocked_nodes": sorted(node.__name__ for node in self.blocked_nodes),

            "imports": self.imports,
            "imported_symbols": sorted(self.imported_symbols),

            "allowed_symbols": sorted(self.allowed_symbols),
            "blocked_symbols": sorted(self.blocked_symbols),

            # "can_save": self.can_save,  # Must be True for this function to be used.
            "timeout_seconds": self.timeout_seconds,
            "memory_limit_bytes": self.memory_limit_bytes,
        }

    @classmethod
    def from_relaunch_data(cls, payload: Mapping[str, object]) -> Permissions:
        """Restore permissions from ``to_relaunch_data`` output.

        Args:
            payload: Serialized permission payload.

        Returns:
            A reconstructed ``Permissions`` instance.
        """
        restored = cls.__new__(cls)

        try:
            restored.level = PermissionLevel(payload["level"])
            restored.modified = bool(payload.get("modified"))

            restored.allowed_nodes = {
                getattr(ast, name)
                for name in payload.get("allowed_nodes", [])  # type: ignore[assignment]
            }
            restored.blocked_nodes = {
                getattr(ast, name)
                for name in payload.get("blocked_nodes", [])  # type: ignore[assignment]
            }

            restored.imports = payload.get("imports", {})  # type: ignore[assignment]
            if not isinstance(restored.imports, dict):
                raise ValueError("Invalid imports format in payload.")
            restored.imported_symbols = set(payload.get("imported_symbols", []))  # type: ignore[assignment]

            restored.allowed_symbols = set(payload.get("allowed_symbols", []))  # type: ignore[assignment]
            restored.blocked_symbols = set(payload.get("blocked_symbols", []))  # type: ignore[assignment]

            restored.can_save = True  # Must be True for this function to be used.
            restored.timeout_seconds = None
            restored.memory_limit_bytes = None
            restored.set_limits(
                payload.get("timeout_seconds"),  # type: ignore[assignment]
                payload.get("memory_limit_bytes")  # type: ignore[assignment]
            )

            restored.build_globals()  # Reconstruct globals dict based on allowed symbols and imports.

        except Exception as exc:
            raise ValueError(f"Failed to restore permissions from payload: {exc}") from exc

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

    def __eq__(self, other: object) -> bool:
        """Equality compares permission level (base_perms) only.

        Returns NotImplemented for unrelated types so Python can handle
        comparisons with other objects.
        """
        match other:
            case Permissions() | PermissionLevel() | int():
                return int(self) == int(other)
            case _:
                return NotImplemented

    def __lt__(self, other: object) -> bool:
        """Less-than compares permission level (base_perms) only.

        This provides a natural ordering by `base_perms` so constructs like
        `max(perm1, perm2)` will return the instance with the higher level.
        """
        match other:
            case Permissions() | PermissionLevel() | int():
                return int(self) < int(other)
            case _:
                return NotImplemented

    def __int__(self) -> int:
        """Return integer representation of this permission level."""
        return int(self.level)

    def __bool__(self) -> bool:
        return bool(self.level)

    @classmethod
    def permissive_merge(
        cls,
        *perms_args: Permissions,
        perms_list: Iterable[Permissions] | None = None,
    ) -> Permissions:
        """Merge multiple permissions into one, using permissive logic."""
        perms_args = (*perms_args, *(perms_list or ()))
        if len(perms_args) == 0:
            return cls(-1)  # No permissions
        if len(perms_args) == 1:
            return perms_args[0].__copy__()  # Only permissions, simply copy

        merged = cls.__new__(cls)
        merged.modified = any(perms.modified for perms in perms_args)
        if not merged.modified:
            return max(perms_args).__copy__()

        merged.level = PermissionLevel(max(perms.level for perms in perms_args))

        merged.allowed_symbols = set().union(*(perms.allowed_symbols for perms in perms_args))
        merged.blocked_symbols = set().intersection(*(perms.blocked_symbols for perms in perms_args))

        merged.allowed_nodes = set().union(*(perms.allowed_nodes for perms in perms_args))
        merged.blocked_nodes = set().intersection(*(perms.blocked_nodes for perms in perms_args))

        merged.imports = imports_union(*(perms.imports for perms in perms_args))
        merged.imported_symbols = set().union(*(perms.imported_symbols for perms in perms_args))

        merged.can_save = any(perms.can_save for perms in perms_args)
        merged.timeout_seconds = None
        if not any(perms.timeout_seconds is None for perms in perms_args):
            merged.timeout_seconds = max(perms.timeout_seconds for perms in perms_args)  # type: ignore[union-attr]
        merged.memory_limit_bytes = None
        if not any(perms.memory_limit_bytes is None for perms in perms_args):
            merged.memory_limit_bytes = max(perms.memory_limit_bytes for perms in perms_args)  # type: ignore[union-attr]

        merged.build_globals()

        return merged

    @classmethod
    def restrictive_merge(
        cls,
        *perms_args: Permissions,
        perms_list: Iterable[Permissions] | None = None,
    ) -> Permissions:
        """Merge multiple permissions into one, using restrictive logic.
        
        The imports intersection logic is minimally implemented and will probably fail
        if there are any conflicting aliases. I do not anticipate this function ever
        being used, so I am not investing in a more robust implementation until/unless
        that becomes a problem.
        """
        perms_args = (*perms_args, *(perms_list or ()))
        if len(perms_args) == 0:
            return cls(-1)  # No permissions
        if len(perms_args) == 1:
            return perms_args[0].__copy__()  # Only permissions, simply copy

        merged = cls.__new__(cls)
        merged.modified = any(perms.modified for perms in perms_args)
        if not merged.modified:
            return min(perms_args).__copy__()

        merged.level = PermissionLevel(min(perms.level for perms in perms_args))

        merged.allowed_symbols = set().intersection(*(perms.allowed_symbols for perms in perms_args))
        merged.blocked_symbols = set().union(*(perms.blocked_symbols for perms in perms_args))

        merged.allowed_nodes = set().intersection(*(perms.allowed_nodes for perms in perms_args))
        merged.blocked_nodes = set().union(*(perms.blocked_nodes for perms in perms_args))

        merged.imports = imports_intersection(*(perms.imports for perms in perms_args))
        merged.imported_symbols = set().intersection(*(perms.imported_symbols for perms in perms_args))

        merged.can_save = all(perms.can_save for perms in perms_args)
        merged.timeout_seconds = None
        if any(perms.timeout_seconds is not None for perms in perms_args):
            merged.timeout_seconds = min(
                perms.timeout_seconds
                for perms in perms_args
                if perms.timeout_seconds is not None
            )
        merged.memory_limit_bytes = None
        if any(perms.memory_limit_bytes is not None for perms in perms_args):
            merged.memory_limit_bytes = min(
                perms.memory_limit_bytes
                for perms in perms_args
                if perms.memory_limit_bytes is not None
            )

        merged.build_globals()

        return merged

    ## Property getters/setters for all fields ##

    @property
    def level(self) -> PermissionLevel:
        """Return the baseline permission level of this policy."""
        return self._level
    @level.setter
    def level(self, value: PermissionLevel | int | str) -> None:
        self._level = PermissionLevel(value)

    @property
    def modified(self) -> bool:
        """Return whether this policy has been modified from its baseline level defaults."""
        return self._modified
    @modified.setter
    def modified(self, value: bool) -> None:
        self._modified = bool(value)

    @property
    def allowed_nodes(self) -> set[type[ast.AST]]:
        return self._allowed_nodes
    @allowed_nodes.setter
    def allowed_nodes(self, value: set[type[ast.AST]]) -> None:
        self._allowed_nodes = value
        self._allowed_nodes_tuple = tuple(value)  # Set tuple for efficient isinstance checks.

    @property
    def allowed_nodes_tuple(self) -> tuple[type[ast.AST], ...]:
        """Return the allowed AST node types as a tuple for efficient isinstance checks."""
        return self._allowed_nodes_tuple

    @property
    def blocked_nodes(self) -> set[type[ast.AST]]:
        return self._blocked_nodes
    @blocked_nodes.setter
    def blocked_nodes(self, value: set[type[ast.AST]]) -> None:
        self._blocked_nodes = value

    @property
    def imports(self) -> NormalizedImportSpec:
        return self._imports
    @imports.setter
    def imports(self, value: NormalizedImportSpec) -> None:
        self._imports = value

    @property
    def imported_symbols(self) -> set[str]:
        return self._imported_symbols
    @imported_symbols.setter
    def imported_symbols(self, value: set[str]) -> None:
        self._imported_symbols = value

    @property
    def allowed_symbols(self) -> set[str]:
        return self._allowed_symbols
    @allowed_symbols.setter
    def allowed_symbols(self, value: set[str]) -> None:
        self._allowed_symbols = value

    @property
    def blocked_symbols(self) -> set[str]:
        return self._blocked_symbols
    @blocked_symbols.setter
    def blocked_symbols(self, value: set[str]) -> None:
        self._blocked_symbols = value

    @property
    def can_save(self) -> bool:
        """Check whether this permission level allows saving/restoring sessions."""
        return self._can_save
    @can_save.setter
    def can_save(self, value: Any) -> None:
        self._can_save = bool(value)

    @property
    def timeout_seconds(self) -> float | None:
        """Return the execution timeout in seconds, or None if no timeout."""
        return self._timeout_seconds
    @timeout_seconds.setter
    def timeout_seconds(self, value: float | int | None) -> None:
        self._timeout_seconds = float(value) if value is not None else None

    @property
    def memory_limit_bytes(self) -> int | None:
        """Return the memory limit in bytes, or None if no limit."""
        return self._memory_limit_bytes
    @memory_limit_bytes.setter
    def memory_limit_bytes(self, value: int | float | None) -> None:
        self._memory_limit_bytes = int(value) if value is not None else None

    @property
    def globals_dict(self) -> dict[str, object]:
        return self._globals_dict
    @globals_dict.setter
    def globals_dict(self, value: dict[str, object]) -> None:
        self._globals_dict = value
