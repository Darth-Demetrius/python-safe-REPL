"""Static policy tables for symbols, AST nodes, and runtime defaults.

This module contains data-only policy configuration used by `safe_repl.policy`.
Separating these constants keeps behavior-centric code smaller and easier to scan.
"""

import ast
import builtins

from safe_repl.AST_DEFS import *

__all__ = [
    "DEFAULT_ALLOWED_NODES",
    "DEFAULT_BLOCKED_NODES",
    "DEFAULT_ALLOWED_SYMBOLS",
    "DEFAULT_BLOCKED_SYMBOLS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MEMORY_LIMIT_BYTES",
]

#### Node policy tables ####
SET = set[type[ast.AST]]  # just makes type signatures easier to read

ALLOWED_NODES_RESTRICTED: SET = {
    ast.mod,  # ROOT_NODES
    *LITERALS,
    ast.Name,  # from VARIABLES
    *OPERATORS,
    *EXPRESSIONS_L1,
    *EXP_SUBSCRIPTING,
    *EXP_COMPREHENSIONS,
    ast.Assign, ast.AugAssign, ast.Assert, ast.Pass,  # some STATEMENTS
    ast.If,  # from CONTROL_FLOW

    # Interactive is new
    ast.Module, ast.Interactive, ast.Expression,  # MOD - {ast.FunctionType}
    ast.Load, ast.Store,  # EXPR_CONTEXT - {ast.Del}
}

ALLOWED_NODES_CONTROLLED: SET = {
    *ALLOWED_NODES_RESTRICTED,
    ast.Starred,  # rest of VARIABLES
    ast.Raise, ast.Delete,  # rest of STATEMENTS - {ast.AnnAssign, ast.TypeAlias}
    *(CONTROL_FLOW_STMT | {ast.ExceptHandler, ast.withitem}),  # rest of CONTROL_FLOW - {ast.TryStar}
    *(FUNCTION_AND_CLASS_DEFS - {ast.Yield, ast.YieldFrom}),
    ast.Continue,  # from STMT
    ast.Del,  # rest of EXPR_CONTEXT
    ast.ExceptHandler,  # EXEPTHANDLER
}

ALLOWED_NODES_TRUSTED: SET = {
    *ALLOWED_NODES_CONTROLLED,
    ast.NamedExpr,  # rest of EXPRESSIONS
    ast.AnnAssign, ast.TypeAlias,  # rest of STATEMENTS
    *STATEMENT_IMPORTS,
    ast.TryStar,  # rest of CONTROL_FLOW
    *PATTERN_MATCHING,  # includes PATTERN
    ast.TypeIgnore, ast.type_ignore,  # TYPE_ANNOTATIONS
    ast.type_param,  # TYPE_PARAMETERS / TYPE_PARAM
    ast.Yield, ast.YieldFrom,  # rest of FUNCTION_AND_CLASS_DEFS
    *ASYNC_AND_AWAIT,
    ast.FunctionType,  # rest of MOD
    ast.stmt,  # all items are already allowed
    ast.expr,  # all items are already allowed
    *TYPE_PARAM,
}

# Only for reference, to check completeness of the above sets.
AST_STUFF_NOT_IN_OTHER_SETS: set = {
    ast.NodeVisitor,
    ast.excepthandler,
    ast.NodeTransformer,
    ast.Param,
    ast.AugStore,
    ast.AugLoad,
    ast.Suite,
    ast.AST,
    ast.slice,
    ast.Index,
}

DEFAULT_ALLOWED_NODES: tuple[SET, ...] = (
    set(),
    ALLOWED_NODES_RESTRICTED,
    ALLOWED_NODES_CONTROLLED,
    ALLOWED_NODES_TRUSTED,
)

DEFAULT_BLOCKED_NODES: tuple[SET, ...] = (
    set(),
    set(),
    set(),
    set(),
)


#### Symbol policy tables ####

COLLECTIONS_AND_ITERATORS: set[str] = {
    "all",
    "any",
    "dict",
    "enumerate",
    "filter",
    "format",
    "frozenset",
    "iter",
    "len",
    "list",
    "map",
    "next",
    "range",
    "reversed",
    "set",
    "slice",
    "sorted",
    "tuple",
    "zip",
}

CONVERSIONS_AND_MATH: set[str] = {
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "chr",
    "float",
    "hex",
    "int",
    "isinstance",
    "oct",
    "ord",
    "repr",
    "str",
    "type",
    "abs",
    "max",
    "min",
    "round",
    "sum",
}

SAFE_EXCEPTIONS: set[str] = {
    "Exception",
    "IndexError",
    "KeyError",
    "TypeError",
    "ValueError",
}

ALLOWED_SYMBOLS_RESTRICTED: set[str] = {
    "print",
    *COLLECTIONS_AND_ITERATORS,
    *CONVERSIONS_AND_MATH,
    *SAFE_EXCEPTIONS,
}
ALLOWED_SYMBOLS_CONTROLLED: set[str] = ALLOWED_SYMBOLS_RESTRICTED
ALLOWED_SYMBOLS_TRUSTED: set[str] = set(dir(builtins))  # Currently allow all builtins, will probably change in the future.

BLOCKED_SYMBOLS_TRUSTED: set[str] = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
}
BLOCKED_SYMBOLS_CONTROLLED: set[str] = {
    *BLOCKED_SYMBOLS_TRUSTED,
    "__import__",
    "delattr",
    "getattr",
    "globals",
    "input",
    "locals",
    "memoryview",
    "open",
    "setattr",
    "vars",
}
BLOCKED_SYMBOLS_RESTRICTED: set[str] = BLOCKED_SYMBOLS_CONTROLLED

# Default per-level symbol policy tables.
# Index position must align with PermissionLevel numeric values.
DEFAULT_ALLOWED_SYMBOLS: tuple[set[str], ...] = (
    set(),
    ALLOWED_SYMBOLS_RESTRICTED,
    ALLOWED_SYMBOLS_CONTROLLED,
    ALLOWED_SYMBOLS_TRUSTED,
)

DEFAULT_BLOCKED_SYMBOLS: tuple[set[str], ...] = (
    set(),
    BLOCKED_SYMBOLS_RESTRICTED,
    BLOCKED_SYMBOLS_CONTROLLED,
    BLOCKED_SYMBOLS_TRUSTED,
)

DEFAULT_TIMEOUT_SECONDS: tuple[float | None, ...] = (
    0.0,
    0.2,
    1.0,
    10.0,
)

DEFAULT_MEMORY_LIMIT_BYTES: tuple[int | None, ...] = (
    0,
    64 * 1024 * 1024,
    256 * 1024 * 1024,
    None,
)


#### Other policy tables ####

PRIVATE_ACCESS = ()
DUNDER_ACCESS = ()
