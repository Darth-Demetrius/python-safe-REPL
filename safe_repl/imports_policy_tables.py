"""Default policy tables for commonly imported modules.

I will use dicts instead of tuples for the level tables to allow for sparse tables.
The validator will have to handle missing levels by treating them as empty sets.
And will have to check all levels up to the current level, not just the current level.

Level 3 block: direct attack surfaces (FFI, code generation, filesystem import/export entrypoints).
Level 2 block: elevated resource-risk surfaces acceptable for personal use but not for semi-trusted code.
Level 1 block: broad anti-DoS constraints.
"""

DEFAULT_IMPORTS_ALLOW: dict[str, dict[int, set[str]]] = {}
DEFAULT_IMPORTS_BLOCK: dict[str, dict[int, set[str]]] = {}

## Core Python Modules ##
# Data Types
DEFAULT_IMPORTS_ALLOW["datetime"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["zoneinfo"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["calendar"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["collections"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["collections.abc"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["heapq"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["bisect"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["array"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["weakref"] = {2: {'*'},}
DEFAULT_IMPORTS_BLOCK["weakref"] = {2: {'finalize', 'ref',},}
DEFAULT_IMPORTS_ALLOW["types"] = {1: {'*'},}
DEFAULT_IMPORTS_BLOCK["types"] = {1: {
    'FunctionType',
    'LambdaType',
    'MethodType',
    'BuiltinFunctionType',
    'BuiltinMethodType',
    'GeneratorType',
    'CoroutineType',
    'AsyncGeneratorType',
    'CodeType',
    'FrameType',
    'TracebackType',
    'CellType',
    'ModuleType',
    'MappingProxyType',
    'SimpleNamespace',
    },}
DEFAULT_IMPORTS_ALLOW["copy"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["pprint"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["reprlib"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["enum"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["graphlib"] = {1: {'*'},}
DEFAULT_IMPORTS_BLOCK["graphlib"] = {1: {'TopologicalSorter'},}

# Numeric and Mathematical Modules
DEFAULT_IMPORTS_ALLOW["numbers"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["math"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["cmath"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["decimal"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["fractions"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["random"] = {1: {'*'},}
DEFAULT_IMPORTS_ALLOW["statistics"] = {1: {'*'},}

# Functional Programming Modules
DEFAULT_IMPORTS_ALLOW["itertools"] = {2: {'*'},}
DEFAULT_IMPORTS_ALLOW["functools"] = {2: {'*'},}
DEFAULT_IMPORTS_ALLOW["operator"] = {3: {'*'},}

# Internet Data Handling
DEFAULT_IMPORTS_ALLOW["json"] = {3: {'*'},}

# Multimedia Services
DEFAULT_IMPORTS_ALLOW["wave"] = {3: {'*'},}
DEFAULT_IMPORTS_ALLOW["colorsys"] = {3: {'*'},}

# Internationalization
DEFAULT_IMPORTS_ALLOW["gettext"] = {3: {'*'},}
DEFAULT_IMPORTS_ALLOW["locale"] = {3: {'*'},}


DEFAULT_IMPORTS_ALLOW["numpy"] = {1: {'*'},}
DEFAULT_IMPORTS_BLOCK["numpy"] = {
    3: {
        "ctypes",
        "distutils",
        "f2py",
        "fromfile",
        "genfromtxt",
        "lib.npyio",
        "load",
        "loadtxt",
        "memmap",
        "save",
        "savetxt",
        "savez",
        "savez_compressed",
        "tofile",
    },
    2: {
        "core.records",
        "ma",
        "rec",
        "record",
    },
    1: {
        "fft",
        "linalg",
        "polynomial",
        "char",
    },
}

DEFAULT_IMPORTS_ALLOW["matplotlib"] = {2: {'*'},}
DEFAULT_IMPORTS_BLOCK["matplotlib"] = {
    3: {
        "backends",
        "backend_bases",
        "use",
    },
}

DEFAULT_IMPORTS_ALLOW["scipy"] = {1: {'*'},}
DEFAULT_IMPORTS_BLOCK["scipy"] = {
    3: {
        "datasets",
        "io",
    },
    1: {
        "cluster",
        "fft",
        "fftpack",
        "integrate",
        "interpolate",
        "linalg",
        "misc",
        "ndimage",
        "odr",
        "optimize",
        "signal",
        "sparse",
        "spatial",
        "special",
        "stats",
        "test",
    },
}

DEFAULT_IMPORTS_ALLOW["sympy"] = {1: {'*'},}
DEFAULT_IMPORTS_BLOCK["sympy"] = {
    3: {
        "codegen",
        "core.sympify",
        "external",
        "parsing",
    },
    2: {
        "integrals",
        "matrices",
        "ntheory",
        "polys",
        "solvers",
        "tensor",
        "combinatorics",
        "core",
        "sets",
    },
    1: {
        "diffgeom",
        "discrete",
        "latex",
        "physics",
        "plotting",
        "printing",
        "simplify",
        "stats",
    },
}
