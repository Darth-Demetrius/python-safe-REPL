"""Benchmarks for the security-facing policy and validator surfaces.

Usage:
    python tools/bench_security.py --iterations 5000

Reports:
- average module import time for `safe_repl.policy` and `safe_repl.validator`
- average `Permissions(...)` construction time
- average `validate_ast(...)` time for representative snippets
"""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
import time

from safe_repl.policy import PermissionLevel, Permissions
from safe_repl.validator import validate_ast


def _time_call(func, iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    end = time.perf_counter()
    return end - start


def _import_module_fresh(module_name: str) -> None:
    to_remove = [name for name in sys.modules if name == module_name or name.startswith(f"{module_name}.")]
    for name in to_remove:
        sys.modules.pop(name, None)
    importlib.import_module(module_name)


def _bench_imports(iterations: int) -> dict[str, float]:
    modules = ("safe_repl.policy", "safe_repl.validator")
    results: dict[str, float] = {}
    for module_name in modules:
        total = _time_call(lambda mn=module_name: _import_module_fresh(mn), iterations)
        results[module_name] = total / iterations
    return results


def _bench_permissions(iterations: int) -> float:
    return _time_call(lambda: Permissions(base_perms=PermissionLevel.LIMITED), iterations) / iterations


def _make_trees() -> dict[str, ast.AST]:
    samples = {
        "literal": "42",
        "attribute_access": "obj.attr",
        "call_attr": "obj.method(1, 2, key='v')",
        "assign_unpack": "a, b = (1, 2)",
        "complex_snippet": "for i in range(10): x = obj.method(i)\narr[i] = x",
    }
    return {name: ast.parse(code, mode="exec") for name, code in samples.items()}


def _bench_validation(iterations: int) -> dict[str, float]:
    perms = Permissions(base_perms=PermissionLevel.UNSUPERVISED)
    user_vars = {"obj": object(), "arr": [], "a": [], "x": 0}
    trees = _make_trees()
    results: dict[str, float] = {}
    for name, tree in trees.items():
        validate_ast(tree, user_vars=user_vars, allowed_names=set(), perms=perms)
        total = _time_call(
            lambda t=tree: validate_ast(t, user_vars=user_vars, allowed_names=set(), perms=perms),
            iterations,
        )
        results[name] = total / iterations
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--import-iterations", type=int, default=200)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    import_results = _bench_imports(args.import_iterations)
    permission_avg = _bench_permissions(args.iterations)
    validation_results = _bench_validation(args.iterations)

    print(f"Import benchmark: {args.import_iterations} iterations each")
    print("Average time per import (milliseconds):")
    for name, seconds in sorted(import_results.items(), key=lambda item: item[1]):
        print(f" - {name:20s}: {seconds * 1e3:8.3f}")

    print()
    print(f"Permissions benchmark: {args.iterations} iterations")
    print(f" - Permissions(base_perms=LIMITED): {permission_avg * 1e6:8.2f} µs")

    print()
    print(f"Validation benchmark: {args.iterations} iterations each")
    print("Average time per validate_ast call (microseconds):")
    for name, seconds in sorted(validation_results.items(), key=lambda item: item[1]):
        print(f" - {name:15s}: {seconds * 1e6:8.2f}")


if __name__ == "__main__":
    main()
