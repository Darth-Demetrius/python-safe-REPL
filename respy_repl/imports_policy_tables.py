"""Default per-module import policy tables for the RestrictedPython REPL.

Structure mirrors the original ``safe_repl.imports_policy_tables``:
    DEFAULT_IMPORTS_ALLOW[module][level] = {'*'} | {symbol, ...}
    DEFAULT_IMPORTS_BLOCK[module][level] = {symbol, ...}

Levels are cumulative - the import guard collects all rules from level 1 up to
and including the session level.  A ``{'*'}`` in the allow table means "all
public symbols from this module are allowed at this level."

Block rules at any level override allow rules at the same or lower level.

Threat tiers (same annotation as original):
    Level 3 block - direct attack surfaces (FFI, code generation, FS import
                    entry-points).
    Level 2 block - elevated resource-risk surfaces acceptable for personal
                    use but not semi-trusted code.
    Level 1 block - broad anti-DoS constraints.
"""

DEFAULT_IMPORTS_ALLOW: dict[str, dict[int, set[str]]] = {}
DEFAULT_IMPORTS_BLOCK: dict[str, dict[int, set[str]]] = {}
IMPORT_POLICY_CATEGORIES: dict[str, set[str]] = {}


# ---------------------------------------------------------------------------
# Core Python – Data Types
# ---------------------------------------------------------------------------
DEFAULT_IMPORTS_ALLOW["datetime"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["zoneinfo"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["calendar"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["collections"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["collections.abc"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["heapq"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["bisect"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["array"] = {1: {"*"}}

DEFAULT_IMPORTS_ALLOW["weakref"] = {2: {"*"}}
DEFAULT_IMPORTS_BLOCK["weakref"] = {2: {"finalize", "ref"}}

DEFAULT_IMPORTS_ALLOW["types"] = {1: {"*"}}
DEFAULT_IMPORTS_BLOCK["types"] = {1: {
    "BuiltinFunctionType",
    "BuiltinMethodType",
    "CellType",
    "CodeType",
    "CoroutineType",
    "AsyncGeneratorType",
    "FrameType",
    "FunctionType",
    "GeneratorType",
    "LambdaType",
    "MappingProxyType",
    "MethodType",
    "ModuleType",
    "SimpleNamespace",
    "TracebackType",
}}

DEFAULT_IMPORTS_ALLOW["copy"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["pprint"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["reprlib"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["enum"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["graphlib"] = {1: {"*"}}
DEFAULT_IMPORTS_BLOCK["graphlib"] = {1: {"TopologicalSorter"}}

IMPORT_POLICY_CATEGORIES["Core Python: Data Types"] = {
    "datetime",
    "zoneinfo",
    "calendar",
    "collections",
    "collections.abc",
    "heapq",
    "bisect",
    "array",
    "weakref",
    "types",
    "copy",
    "pprint",
    "reprlib",
    "enum",
    "graphlib",
}

# ---------------------------------------------------------------------------
# Core Python – Numeric and Mathematical
# ---------------------------------------------------------------------------
DEFAULT_IMPORTS_ALLOW["numbers"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["math"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["cmath"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["decimal"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["fractions"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["random"] = {1: {"*"}}
DEFAULT_IMPORTS_ALLOW["statistics"] = {1: {"*"}}

IMPORT_POLICY_CATEGORIES["Core Python: Numeric and Mathematical"] = {
    "numbers", "math", "cmath", "decimal", "fractions", "random", "statistics"
}

# ---------------------------------------------------------------------------
# Core Python – Functional Programming
# ---------------------------------------------------------------------------
DEFAULT_IMPORTS_ALLOW["itertools"] = {2: {"*"}}
DEFAULT_IMPORTS_ALLOW["functools"] = {2: {"*"}}
DEFAULT_IMPORTS_ALLOW["operator"] = {3: {"*"}}

IMPORT_POLICY_CATEGORIES["Core Python: Functional Programming"] = {
    "itertools", "functools", "operator"
}

# ---------------------------------------------------------------------------
# Core Python – Internet Data / Multimedia / i18n
# ---------------------------------------------------------------------------
DEFAULT_IMPORTS_ALLOW["json"] = {3: {"*"}}
DEFAULT_IMPORTS_ALLOW["wave"] = {3: {"*"}}
DEFAULT_IMPORTS_ALLOW["colorsys"] = {3: {"*"}}
DEFAULT_IMPORTS_ALLOW["gettext"] = {3: {"*"}}
DEFAULT_IMPORTS_ALLOW["locale"] = {3: {"*"}}

IMPORT_POLICY_CATEGORIES["Core Python: Internet Data / Multimedia / i18n"] = {
    "json", "wave", "colorsys", "gettext", "locale"
}

# ---------------------------------------------------------------------------
# Third-party
# ---------------------------------------------------------------------------

# NumPy
DEFAULT_IMPORTS_ALLOW["numpy"] = {1: {"*"}}
DEFAULT_IMPORTS_BLOCK["numpy"] = {
    3: {
        "ctypes", "distutils", "f2py", "fromfile", "genfromtxt",
        "lib.npyio", "load", "loadtxt", "memmap", "save", "savetxt",
        "savez", "savez_compressed", "tofile",
    },
    2: {"core.records", "ma", "rec", "record"},
    1: {"fft", "linalg", "polynomial", "char"},
}

# Matplotlib
DEFAULT_IMPORTS_ALLOW["matplotlib"] = {2: {"*"}}
DEFAULT_IMPORTS_BLOCK["matplotlib"] = {
    3: {"backends", "backend_bases", "use"},
}

# SciPy
DEFAULT_IMPORTS_ALLOW["scipy"] = {1: {"*"}}
DEFAULT_IMPORTS_BLOCK["scipy"] = {
    3: {"datasets", "io"},
    1: {
        "cluster", "fft", "fftpack", "integrate", "interpolate", "linalg",
        "misc", "ndimage", "odr", "optimize", "signal", "sparse", "spatial",
        "special", "stats", "test",
    },
}

# SymPy
DEFAULT_IMPORTS_ALLOW["sympy"] = {1: {"*"}}
DEFAULT_IMPORTS_BLOCK["sympy"] = {
    3: {"codegen", "core.sympify", "external", "parsing"},
    2: {
        "combinatorics", "core", "integrals", "matrices", "ntheory",
        "polys", "sets", "solvers", "tensor",
    },
    1: {
        "diffgeom", "discrete", "latex", "physics", "plotting",
        "printing", "simplify", "stats",
    },
}

# MyDyce
DEFAULT_IMPORTS_ALLOW["MyDyce"] = {1: {"*"}}


IMPORT_POLICY_CATEGORIES["Third-party"] = {
        "numpy", "matplotlib", "scipy", "sympy", "MyDyce"
    }
