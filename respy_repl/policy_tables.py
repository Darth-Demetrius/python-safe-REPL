"""Static policy tables for the RestrictedPython-based safe REPL.

RestrictedPython handles AST-level code transformation automatically, so this
module only needs to define allowed builtins, timeout/memory defaults, and
import-access flags.  There is no AST-node table because RestrictedPython's
compiler enforces node-level restrictions for us.

Level taxonomy (mirrors the original safe_repl design):
    Level 1 (RESTRICTED)  - pure computation; no side-effects.
    Level 2 (CONTROLLED)  - class/function definitions; richer error set.
    Level 3 (TRUSTED)     - almost all builtins; light import access.
"""

import builtins

__all__ = [
    "DEFAULT_ALLOWED_BUILTINS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MEMORY_LIMIT_BYTES",
]


# ---------------------------------------------------------------------------
# Builtin symbol sets
# ---------------------------------------------------------------------------

_COLLECTIONS_AND_ITERATORS: set[str] = {
    "all", "any", "dict", "enumerate", "filter", "frozenset", "iter",
    "len", "list", "map", "next", "range", "reversed", "set", "slice",
    "sorted", "tuple", "zip",
}

_CONVERSIONS_AND_MATH: set[str] = {
    "abs", "ascii", "bin", "bool", "bytearray", "bytes", "chr", "complex",
    "divmod", "float", "format", "hash", "hex", "int", "isinstance",
    "issubclass", "oct", "ord", "pow", "repr", "round", "str", "sum", "type",
}

_SAFE_EXCEPTIONS: set[str] = {
    "ArithmeticError", "AttributeError", "Exception", "IndexError",
    "KeyError", "LookupError", "NameError", "NotImplementedError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError",
}

# RESTRICTED: pure expression-level work; safe for untrusted semi-public input.
ALLOWED_BUILTINS_RESTRICTED: set[str] = {
    "print",
    "object",
    "NotImplemented", "True", "False", "None",
    *_COLLECTIONS_AND_ITERATORS,
    *_CONVERSIONS_AND_MATH,
    *_SAFE_EXCEPTIONS,
}

# CONTROLLED: adds class/function helpers and a broader exception hierarchy.
ALLOWED_BUILTINS_CONTROLLED: set[str] = {
    *ALLOWED_BUILTINS_RESTRICTED,
    # Introspection & OOP
    "callable", "classmethod", "delattr", "dir", "getattr", "hasattr",
    "id", "property", "setattr", "staticmethod", "super", "vars",
    "__build_class__",
    # Extended exception set
    "BaseException", "EOFError", "FileExistsError", "FileNotFoundError",
    "FloatingPointError", "GeneratorExit", "ImportError", "MemoryError",
    "ModuleNotFoundError", "OSError", "OverflowError", "RecursionError",
    "RuntimeWarning", "StopAsyncIteration", "SyntaxError", "SystemError",
    "SystemExit", "TimeoutError", "UnboundLocalError", "UnicodeDecodeError",
    "UnicodeEncodeError", "UnicodeError", "UnicodeTranslateError",
    "UnicodeWarning", "UserWarning", "Warning",
    # Singletons
    "Ellipsis", "NotImplemented",
}

# TRUSTED: almost all builtins; only the most dangerous ones are removed.
_BLOCKED_BUILTINS_TRUSTED: set[str] = {
    "breakpoint",   # halts execution
    "compile",      # code generation
    "eval",         # code generation
    "exec",         # code generation
    "__import__",   # replaced with policy-aware import guard
    "input",        # blocking I/O
    "memoryview",   # low-level buffer access
    "open",         # filesystem access
}
ALLOWED_BUILTINS_TRUSTED: set[str] = set(dir(builtins)) - _BLOCKED_BUILTINS_TRUSTED


DEFAULT_ALLOWED_BUILTINS: tuple[set[str], ...] = (
    set(),                         # level 0 – NONE
    ALLOWED_BUILTINS_RESTRICTED,   # level 1 – RESTRICTED
    ALLOWED_BUILTINS_CONTROLLED,   # level 2 – CONTROLLED
    ALLOWED_BUILTINS_TRUSTED,      # level 3 – TRUSTED
)


# ---------------------------------------------------------------------------
# Runtime limit defaults (same values as the original safe_repl)
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS: tuple[float | None, ...] = (
    0.0,    # level 0 – effectively disabled
    0.2,    # level 1 – tight for RESTRICTED
    1.0,    # level 2 – moderate for CONTROLLED
    10.0,   # level 3 – generous for TRUSTED
)

DEFAULT_MEMORY_LIMIT_BYTES: tuple[int | None, ...] = (
    0,                   # level 0 – effectively disabled
    64  * 1024 * 1024,   # level 1 – 64 MB
    256 * 1024 * 1024,   # level 2 – 256 MB
    None,                # level 3 – no limit
)
