"""Permission model and policy configuration for safe_repl.

Defines permission levels, baseline allow/block tables, and the `Permissions`
object used by execution and validation layers.
"""

import ast
import builtins
from enum import IntEnum
import warnings


# Builtin capability groups by feature area.
_CORE_FUNCTIONS = {
    "abs",
    "round",
    "min",
    "max",
    "sum",
    "pow",
    "divmod",
    "int",
    "float",
    "str",
    "bool",
    "chr",
    "ord",
    "hex",
    "oct",
    "bin",
}

_COLLECTION_FUNCTIONS = {
    "list",
    "tuple",
    "dict",
    "set",
    "bytes",
    "bytearray",
    "frozenset",
    "len",
    "range",
    "enumerate",
    "zip",
    "reversed",
    "sorted",
    "iter",
    "next",
}

_UTILITY_FUNCTIONS = {"all", "any", "isinstance", "type", "repr", "ascii", "format", "slice"}
_FUNCTIONAL_FUNCTIONS = {"map", "filter"}

# AST capability groups by language feature area.
_CORE_NODES = {
    ast.Module,
    ast.Expression,
    ast.Expr,
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.Set,
    ast.Dict,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.Assign,
    ast.AugAssign,
    ast.Call,
    ast.keyword,
    ast.Starred,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.operator,
    ast.unaryop,
    ast.boolop,
    ast.cmpop,
    ast.IfExp,
    ast.NamedExpr,
    ast.If,
    ast.Assert,
}

_ITERATION_NODES = {
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Lambda,
    ast.arguments,
    ast.arg,
}

_FUNCTION_DEF_NODES = {ast.FunctionDef, ast.Return}
_CLASS_NODES = {ast.ClassDef}
_SCOPE_NODES = {ast.Global, ast.Nonlocal}
_EXCEPTION_NODES = {ast.Try, ast.Raise, ast.With, ast.ExceptHandler}
_IMPORT_NODES = {ast.Import, ast.ImportFrom, ast.alias}


# Baseline per-level symbol policy.
# Index position must align with PermissionLevel numeric values.
_ALLOWED_SYMBOLS_MINIMUM = _CORE_FUNCTIONS
_ALLOWED_SYMBOLS_LIMITED = (
    _ALLOWED_SYMBOLS_MINIMUM
    | _COLLECTION_FUNCTIONS
    | _UTILITY_FUNCTIONS
    | _FUNCTIONAL_FUNCTIONS
)
_ALLOWED_SYMBOLS_PERMISSIVE = _ALLOWED_SYMBOLS_LIMITED
_ALLOWED_SYMBOLS_UNSUPERVISED = set(dir(builtins))
MEMORY_LIMIT_INFINITY = 2**63 - 1

_BLOCKED_SYMBOLS_UNSUPERVISED = {"breakpoint", "compile", "eval", "exec"}
_BLOCKED_SYMBOLS_PERMISSIVE = _BLOCKED_SYMBOLS_UNSUPERVISED | {
    "__import__", "delattr", "getattr", "globals", "input", "locals",
    "memoryview", "open", "setattr", "vars",
}
_BLOCKED_SYMBOLS_LIMITED = _BLOCKED_SYMBOLS_PERMISSIVE
_BLOCKED_SYMBOLS_MINIMUM = _BLOCKED_SYMBOLS_PERMISSIVE

# Baseline per-level AST policy.
# Index position must align with PermissionLevel numeric values.
_ALLOWED_NODES_MINIMUM = _CORE_NODES
_ALLOWED_NODES_LIMITED = _ALLOWED_NODES_MINIMUM | _ITERATION_NODES | _FUNCTION_DEF_NODES
_ALLOWED_NODES_PERMISSIVE = _ALLOWED_NODES_LIMITED | _EXCEPTION_NODES | _CLASS_NODES | _SCOPE_NODES
_ALLOWED_NODES_UNSUPERVISED = _ALLOWED_NODES_PERMISSIVE | _IMPORT_NODES


DEFAULT_ALLOWED_SYMBOLS = (
    _ALLOWED_SYMBOLS_MINIMUM,
    _ALLOWED_SYMBOLS_LIMITED,
    _ALLOWED_SYMBOLS_PERMISSIVE,
    _ALLOWED_SYMBOLS_UNSUPERVISED,
)

DEFAULT_ALLOWED_NODES = (
    _ALLOWED_NODES_MINIMUM,
    _ALLOWED_NODES_LIMITED,
    _ALLOWED_NODES_PERMISSIVE,
    _ALLOWED_NODES_UNSUPERVISED,
)

DEFAULT_BLOCKED_NODES = (
    {ast.Attribute},
    set(),
    set(),
    set(),
)

DEFAULT_BLOCKED_SYMBOLS = (
    _BLOCKED_SYMBOLS_MINIMUM,
    _BLOCKED_SYMBOLS_LIMITED,
    _BLOCKED_SYMBOLS_PERMISSIVE,
    _BLOCKED_SYMBOLS_UNSUPERVISED,
)

DEFAULT_TIMEOUT_SECONDS: tuple[float, float, float, float] = (
    0.1,
    0.5,
    10.0,
    float("inf"),
)

DEFAULT_MEMORY_LIMIT_BYTES: tuple[int, int, int, int] = (
    64 * 1024 * 1024,
    256 * 1024 * 1024,
    MEMORY_LIMIT_INFINITY,
    MEMORY_LIMIT_INFINITY,
)


def _build_builtins_scope(allowed_symbols: set[str]) -> dict[str, object]:
    """Create the restricted `__builtins__` mapping for execution globals."""
    return {
        name: getattr(builtins, name)
        for name in allowed_symbols
        if hasattr(builtins, name)
    }


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
            if not normalized:
                normalized = value
            else:
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

        Defaults:
        - `base_perms` defaults to `PermissionLevel.LIMITED`.
        - Per-instance timeout/memory limits are initialized from
            `DEFAULT_TIMEOUT_SECONDS` / `DEFAULT_MEMORY_LIMIT_BYTES` by level.
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
        """Build a policy from level defaults plus optional overrides.

        Args:
            base_perms: Baseline permission level. Defaults to `LIMITED`.
            allow_symbols: Additional symbol names to permit.
            block_symbols: Symbol names to deny even if baseline allows them.
            allow_nodes: Additional AST node types to permit.
            block_nodes: AST node types to deny even if baseline allows them.
            imports: Imported objects injected into execution globals.
            timeout_seconds: Optional per-instance execution timeout override.
            memory_limit_bytes: Optional per-instance memory limit override.
        """
        # Normalize optional containers to avoid mutable-default pitfalls.
        allow_symbols = allow_symbols or set()
        block_symbols = block_symbols or set()
        allow_nodes = allow_nodes or set()
        block_nodes = block_nodes or set()
        imports = imports or {}

        self.level = base_perms
        self.modified = bool(allow_symbols or block_symbols or allow_nodes or block_nodes)
        self.timeout_seconds = (
            DEFAULT_TIMEOUT_SECONDS[self.level]
            if timeout_seconds is None
            else timeout_seconds
        )
        self.memory_limit_bytes = (
            DEFAULT_MEMORY_LIMIT_BYTES[self.level]
            if memory_limit_bytes is None
            else memory_limit_bytes
        )

        blocked_symbols = DEFAULT_BLOCKED_SYMBOLS[self.level] | block_symbols
        self.allowed_symbols = (DEFAULT_ALLOWED_SYMBOLS[self.level] | allow_symbols) - blocked_symbols
        if self.level >= PermissionLevel.PERMISSIVE:
            self.allowed_symbols.add("__build_class__")
        self.imported_symbols = set(imports.keys()) - blocked_symbols
        self.allowed_symbols |= self.imported_symbols

        self.globals_dict: dict[str, object] = {
            "__builtins__": _build_builtins_scope(self.allowed_symbols)
        }
        self.globals_dict["__name__"] = "__safe_repl__"
        self.globals_dict.update({name: obj for name, obj in imports.items() if name not in blocked_symbols})

        self.allowed_nodes = (
            (DEFAULT_ALLOWED_NODES[self.level] | allow_nodes)
            - (DEFAULT_BLOCKED_NODES[self.level] | block_nodes)
        )
        self.allowed_node_tuple = tuple(self.allowed_nodes) # For efficient isinstance checks in validator.

    def __str__(self) -> str:
        """Return a compact human-readable summary of active policy."""
        name = self.level.name.lower() + (" (custom)" if self.modified else "")
        if not self.imported_symbols:
            return name
        if len(self.imported_symbols) <= 3:
            return f"{name} with imports: {', '.join(sorted(self.imported_symbols))}"
        return f"{name} with {len(self.imported_symbols)} imports"

    def set_timeout_seconds(self, seconds: float) -> None:
        """Override this instance's execution timeout in seconds."""
        self.timeout_seconds = seconds

    def set_memory_limit_bytes(self, bytes_limit: int) -> None:
        """Override this instance's memory limit in bytes."""
        self.memory_limit_bytes = bytes_limit
