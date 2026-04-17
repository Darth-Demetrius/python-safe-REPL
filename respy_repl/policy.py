"""Permission model and runtime policy for the RestrictedPython-based REPL.

``PermissionLevel`` and ``Permissions`` mirror the originals in purpose and
interface, but the implementation is simplified because RestrictedPython
handles AST-level restrictions automatically.  There is no AST-node allow/block
tracking here; ``Permissions`` focuses on:

* Which builtins are available in the execution context.
* Timeout and memory limits.
* Import specifications.
* Building the ``restricted_globals`` dict consumed by ``ResPy_engine``.
"""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Iterable, Mapping
from enum import IntEnum
from functools import total_ordering
from typing import Any, Optional
import warnings

from .imports import (
    NormalizedImportSpec,
    SafeReplImportError,
    collect_import_symbols,
    imports_union,
    make_import_guard,
    normalize_validate_imports,
)
from .policy_tables import (
    DEFAULT_ALLOWED_BUILTINS,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
)


def _write_guard(obj: object) -> object:
    """Guard for attribute assignment - simply returns the object."""
    return obj



class PermissionLevel(IntEnum):
    """Permission levels ordered from most restrictive to most permissive.

    Design invariants (identical to original ``safe_repl.policy``):
    - Level ``0`` = no permissions at all.
    - Higher levels include all permissions of lower levels.
    - The last member (highest value) is always the *least* restrictive.
    """

    NONE       = 0
    RESTRICTED = 1
    CONTROLLED = 2
    TRUSTED    = 3

    @classmethod
    def _missing_(cls, value: object) -> "PermissionLevel | None":
        """Accept case-insensitive names and numeric strings."""
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

        valid = ", ".join(f"{l.value} ({l.name})" for l in cls)
        warnings.warn(
            f"Invalid permission level {value!r}. Use one of: {valid}. "
            f"Defaulting to {cls(0).name}.",
            stacklevel=2,
        )
        return cls(0)


@total_ordering
class Permissions:
    """Resolved execution policy for one RestrictedPython evaluator/session.

    A ``Permissions`` object combines a baseline permission level with optional
    symbol overrides and import injections, then computes the concrete builtins
    dict and restricted globals used by the execution engine.

    Unlike the original ``safe_repl.policy.Permissions``, there is **no** AST
    node tracking because RestrictedPython enforces node-level restrictions at
    compile time.

    Args:
        perm_level: Baseline permission level.
        allow_symbols: Additional built-in names to allow beyond the baseline.
        block_symbols: Names to remove; overrides ``allow_symbols``.
        imports: Import spec strings to resolve (pre-approved by the host).
        timeout_seconds: Execution timeout; ``None`` disables the limit.
        memory_limit_bytes: RSS cap measured via ``tracemalloc``; ``None``
            disables the limit.
    """

    _level: PermissionLevel
    _modified: bool
    _allowed_symbols: set[str]
    _blocked_symbols: set[str]
    _imports: NormalizedImportSpec
    _imported_symbols: set[str]
    _timeout_seconds: float | None
    _memory_limit_bytes: int | None
    _restricted_globals: dict[str, object]

    def __init__(
        self,
        perm_level: PermissionLevel | int = 0,
        *,
        allow_symbols: Optional[set[str]] = None,
        block_symbols: Optional[set[str]] = None,
        imports: Optional[list[str]] = None,
        timeout_seconds: float | None = ...,   # type: ignore[assignment]
        memory_limit_bytes: int | None = ...,  # type: ignore[assignment]
    ) -> None:
        """Build a policy from level defaults plus optional overrides."""
        self.level = PermissionLevel(perm_level)
        self.modified = bool(allow_symbols or block_symbols)

        self.imports = normalize_validate_imports(imports or [])
        self.imported_symbols = collect_import_symbols(self.imports)

        base_symbols = set(DEFAULT_ALLOWED_BUILTINS[self.level])
        self.allowed_symbols = base_symbols | (allow_symbols or set())
        self.allowed_symbols |= self.imported_symbols
        self.blocked_symbols = block_symbols or set()
        self.allowed_symbols -= self.blocked_symbols

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

        self.build_restricted_globals()

    # ------------------------------------------------------------------
    # Globals construction
    # ------------------------------------------------------------------

    def build_restricted_globals(self) -> None:
        """Construct the restricted-globals dict for the execution engine.

        The returned dict includes:
        * ``__builtins__``: filtered builtins dict plus RestrictedPython guards.
        * ``__name__``: ``'__safe_repl__'``.
        * Pre-imported module/symbol bindings.
        * A policy-aware ``__import__`` guard.
        """
        from RestrictedPython.Eval import (
            default_guarded_getattr,
            default_guarded_getitem,
            default_guarded_getiter,
        )
        from RestrictedPython.Guards import (
            guarded_iter_unpack_sequence,
            guarded_unpack_sequence,
        )

        builtins_map = builtins.__dict__
        safe_builtins: dict[str, object] = {
            name: builtins_map[name]
            for name in self.allowed_symbols
            if name in builtins_map
        }

        # Inject the policy-aware import guard as ``__import__`` so every
        # ``import`` statement in restricted code is filtered.
        safe_builtins["__import__"] = make_import_guard(
            self.imports, level=int(self.level)
        )

        # RestrictedPython requires ``_print_`` to come from a PrintCollector
        # instance, which is created fresh per execution in the engine.  We do
        # NOT set it here; the engine sets it before each exec call.

        glb: dict[str, object] = {
            "__name__": "__safe_repl__",
            "__metaclass__": type,  # Required for class definitions in RestrictedPython
            "__builtins__": safe_builtins,
            # RestrictedPython guard hooks (required for compiled restricted code).
            "_getiter_": default_guarded_getiter,
            "_getitem_": default_guarded_getitem,
            "_getattr_": default_guarded_getattr,
            "_write_": _write_guard,
            "_inplacevar_": _default_inplacevar,
            "_unpack_sequence_": guarded_unpack_sequence,
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        }

        # Pre-inject explicitly allowed imports so user code can reference them
        # without an explicit import statement (mirrors original behaviour).
        for (module_name, module_alias), names in self.imports.items():
            module = importlib.import_module(module_name)
            if module_alias in self.allowed_symbols or module_alias == module_name:
                glb[module_alias] = module
            for import_name, import_alias in names:
                if import_alias in self.allowed_symbols:
                    glb[import_alias] = getattr(module, import_name)

        self._restricted_globals = glb

    @property
    def restricted_globals(self) -> dict[str, object]:
        """Return the restricted globals dict for the execution engine."""
        return self._restricted_globals

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_relaunch_data(self) -> dict[str, object]:
        """Return a compact, picklable payload for restarting this policy."""
        return {
            "level": int(self.level),
            "modified": self.modified,
            "imports": self.imports,
            "imported_symbols": sorted(self.imported_symbols),
            "allowed_symbols": sorted(self.allowed_symbols),
            "blocked_symbols": sorted(self.blocked_symbols),
            "timeout_seconds": self.timeout_seconds,
            "memory_limit_bytes": self.memory_limit_bytes,
        }

    @classmethod
    def from_relaunch_data(cls, payload: Mapping[str, object]) -> "Permissions":
        """Restore a ``Permissions`` instance from ``to_relaunch_data`` output."""
        restored = cls.__new__(cls)
        try:
            restored.level = PermissionLevel(payload["level"])  # type: ignore[arg-type]
            restored.modified = bool(payload.get("modified"))

            restored.imports = payload.get("imports", {})  # type: ignore[assignment]
            if not isinstance(restored.imports, dict):
                raise ValueError("Invalid imports format in payload.")
            restored.imported_symbols = set(payload.get("imported_symbols", []))  # type: ignore[arg-type]

            restored.allowed_symbols = set(payload.get("allowed_symbols", []))  # type: ignore[arg-type]
            restored.blocked_symbols = set(payload.get("blocked_symbols", []))  # type: ignore[arg-type]

            restored.timeout_seconds = None
            restored.memory_limit_bytes = None
            restored.set_limits(
                payload.get("timeout_seconds"),       # type: ignore[arg-type]
                payload.get("memory_limit_bytes"),    # type: ignore[arg-type]
            )
            restored.build_restricted_globals()
        except Exception as exc:
            raise ValueError(
                f"Failed to restore permissions from payload: {exc}"
            ) from exc
        return restored

    def __getstate__(self) -> dict[str, object]:
        return self.to_relaunch_data()

    def __setstate__(self, state: Mapping[str, object]) -> None:
        restored = self.from_relaunch_data(state)
        self.__dict__.update(restored.__dict__)

    # ------------------------------------------------------------------
    # Merge helpers
    # ------------------------------------------------------------------

    def set_limits(
        self,
        timeout_seconds: float | None = ...,   # type: ignore[assignment]
        memory_limit_bytes: int | None = ...,  # type: ignore[assignment]
    ) -> None:
        """Update timeout and/or memory limit in-place."""
        if timeout_seconds is not ...:
            self.timeout_seconds = timeout_seconds  # type: ignore[assignment]
        if memory_limit_bytes is not ...:
            self.memory_limit_bytes = memory_limit_bytes  # type: ignore[assignment]

    def __copy__(self) -> "Permissions":
        copied = Permissions.__new__(Permissions)
        copied._level = self._level
        copied._modified = self._modified
        copied._imports = {m: set(n) for m, n in self._imports.items()}
        copied._imported_symbols = set(self._imported_symbols)
        copied._allowed_symbols = set(self._allowed_symbols)
        copied._blocked_symbols = set(self._blocked_symbols)
        copied._timeout_seconds = self._timeout_seconds
        copied._memory_limit_bytes = self._memory_limit_bytes
        copied._restricted_globals = dict(self._restricted_globals)
        return copied

    @classmethod
    def permissive_merge(cls, *perms_args: "Permissions") -> "Permissions":
        """Merge multiple permissions using permissive (max) logic."""
        if not perms_args:
            return cls(0)
        if len(perms_args) == 1:
            return perms_args[0]

        merged = cls.__new__(cls)
        merged.level = PermissionLevel(max(p.level for p in perms_args))
        merged.modified = any(p.modified for p in perms_args)

        merged.allowed_symbols = set().union(*(p.allowed_symbols for p in perms_args))
        merged.blocked_symbols = set().intersection(*(p.blocked_symbols for p in perms_args))

        merged.imports = imports_union(*(p.imports for p in perms_args))
        merged.imported_symbols = set().union(*(p.imported_symbols for p in perms_args))

        merged.timeout_seconds = None
        if not any(p.timeout_seconds is None for p in perms_args):
            merged.timeout_seconds = max(p.timeout_seconds for p in perms_args)  # type: ignore[union-attr]
        merged.memory_limit_bytes = None
        if not any(p.memory_limit_bytes is None for p in perms_args):
            merged.memory_limit_bytes = max(p.memory_limit_bytes for p in perms_args)  # type: ignore[union-attr]

        merged.build_restricted_globals()
        return merged

    # ------------------------------------------------------------------
    # Comparison & representation
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        match other:
            case Permissions() | PermissionLevel() | int():
                return int(self) == int(other)
            case _:
                return NotImplemented

    def __lt__(self, other: object) -> bool:
        match other:
            case Permissions() | PermissionLevel() | int():
                return int(self) < int(other)
            case _:
                return NotImplemented

    def __int__(self) -> int:
        return int(self.level)

    def __str__(self) -> str:
        name = self.level.name.lower() + (" (custom)" if self.modified else "")
        if self.imports:
            return f"{name} with {len(self.imports)} imports"
        return name

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def level(self) -> PermissionLevel:
        """Return the baseline permission level."""
        return self._level

    @level.setter
    def level(self, value: PermissionLevel | int | str) -> None:
        self._level = PermissionLevel(value)

    @property
    def modified(self) -> bool:
        """Return whether the policy was customised beyond its level defaults."""
        return self._modified

    @modified.setter
    def modified(self, value: bool) -> None:
        self._modified = bool(value)

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
    def timeout_seconds(self) -> float | None:
        return self._timeout_seconds

    @timeout_seconds.setter
    def timeout_seconds(self, value: float | int | None) -> None:
        self._timeout_seconds = float(value) if value is not None else None

    @property
    def memory_limit_bytes(self) -> int | None:
        return self._memory_limit_bytes

    @memory_limit_bytes.setter
    def memory_limit_bytes(self, value: int | float | None) -> None:
        self._memory_limit_bytes = int(value) if value is not None else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _default_inplacevar(op: str, x: object, y: object) -> object:
    """Minimal in-place operator fallback used when RestrictedPython does not
    provide one in ``safe_globals``."""
    ops: dict[str, object] = {
        "+=": lambda a, b: a + b,       # type: ignore[operator]
        "-=": lambda a, b: a - b,       # type: ignore[operator]
        "*=": lambda a, b: a * b,       # type: ignore[operator]
        "/=": lambda a, b: a / b,       # type: ignore[operator]
        "//=": lambda a, b: a // b,     # type: ignore[operator]
        "%=": lambda a, b: a % b,       # type: ignore[operator]
        "**=": lambda a, b: a ** b,     # type: ignore[operator]
        "&=": lambda a, b: a & b,       # type: ignore[operator]
        "|=": lambda a, b: a | b,       # type: ignore[operator]
        "^=": lambda a, b: a ^ b,       # type: ignore[operator]
        "<<=": lambda a, b: a << b,     # type: ignore[operator]
        ">>=": lambda a, b: a >> b,     # type: ignore[operator]
    }
    fn = ops.get(op)
    if fn is None:
        raise NotImplementedError(f"Unsupported in-place operator: {op!r}")
    return fn(x, y)  # type: ignore[operator]
