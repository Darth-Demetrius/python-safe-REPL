"""Static policy tables for symbols, AST nodes, and runtime defaults.

This module contains data-only policy configuration used by `safe_repl.policy`.
Separating these constants keeps behavior-centric code smaller and easier to scan.
"""

import ast
import builtins


# Builtin capability groups by feature area.
CORE_FUNCTIONS = {
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

COLLECTION_FUNCTIONS = {
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

UTILITY_FUNCTIONS = {"all", "any", "isinstance", "type", "repr", "ascii", "format", "slice"}
FUNCTIONAL_FUNCTIONS = {"map", "filter"}


# AST capability groups by language feature area.
CORE_NODES = {
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

ITERATION_NODES = {
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

FUNCTION_DEF_NODES = {ast.FunctionDef, ast.Return}
CLASS_NODES = {ast.ClassDef}
SCOPE_NODES = {ast.Global, ast.Nonlocal}
EXCEPTION_NODES = {ast.Try, ast.Raise, ast.With, ast.ExceptHandler}
IMPORT_NODES = {ast.Import, ast.ImportFrom, ast.alias}


# Baseline per-level symbol policy.
# Index position must align with PermissionLevel numeric values.
ALLOWED_SYMBOLS_MINIMUM = CORE_FUNCTIONS
ALLOWED_SYMBOLS_LIMITED = (
    ALLOWED_SYMBOLS_MINIMUM
    | COLLECTION_FUNCTIONS
    | UTILITY_FUNCTIONS
    | FUNCTIONAL_FUNCTIONS
)
ALLOWED_SYMBOLS_PERMISSIVE = ALLOWED_SYMBOLS_LIMITED
ALLOWED_SYMBOLS_UNSUPERVISED = set(dir(builtins))

BLOCKED_SYMBOLS_UNSUPERVISED = {"breakpoint", "compile", "eval", "exec"}
BLOCKED_SYMBOLS_PERMISSIVE = BLOCKED_SYMBOLS_UNSUPERVISED | {
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
BLOCKED_SYMBOLS_LIMITED = BLOCKED_SYMBOLS_PERMISSIVE
BLOCKED_SYMBOLS_MINIMUM = BLOCKED_SYMBOLS_PERMISSIVE


# Baseline per-level AST policy.
# Index position must align with PermissionLevel numeric values.
ALLOWED_NODES_MINIMUM = CORE_NODES
ALLOWED_NODES_LIMITED = ALLOWED_NODES_MINIMUM | ITERATION_NODES | FUNCTION_DEF_NODES
ALLOWED_NODES_PERMISSIVE = ALLOWED_NODES_LIMITED | EXCEPTION_NODES | CLASS_NODES | SCOPE_NODES
ALLOWED_NODES_UNSUPERVISED = ALLOWED_NODES_PERMISSIVE | IMPORT_NODES


DEFAULT_ALLOWED_SYMBOLS = (
    ALLOWED_SYMBOLS_MINIMUM,
    ALLOWED_SYMBOLS_LIMITED,
    ALLOWED_SYMBOLS_PERMISSIVE,
    ALLOWED_SYMBOLS_UNSUPERVISED,
)

DEFAULT_ALLOWED_NODES = (
    ALLOWED_NODES_MINIMUM,
    ALLOWED_NODES_LIMITED,
    ALLOWED_NODES_PERMISSIVE,
    ALLOWED_NODES_UNSUPERVISED,
)

DEFAULT_BLOCKED_NODES = (
    {ast.Attribute},
    set(),
    set(),
    set(),
)

DEFAULT_BLOCKED_SYMBOLS = (
    BLOCKED_SYMBOLS_MINIMUM,
    BLOCKED_SYMBOLS_LIMITED,
    BLOCKED_SYMBOLS_PERMISSIVE,
    BLOCKED_SYMBOLS_UNSUPERVISED,
)

DEFAULT_TIMEOUT_SECONDS: tuple[float | None, ...] = (
    0.2,
    1.0,
    10.0,
    None,
)

DEFAULT_MEMORY_LIMIT_BYTES: tuple[int | None, ...] = (
    64 * 1024 * 1024,
    256 * 1024 * 1024,
    None,
    None,
)
