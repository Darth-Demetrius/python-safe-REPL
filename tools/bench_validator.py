"""Micro-benchmarks for `safe_repl.validator` hot paths.

Usage:
    python tools/bench_validator.py --iterations 2000

Reports average time per `validate_ast` call for several representative
AST snippets.
"""
from __future__ import annotations

import argparse
import ast
import time
from typing import Iterable

from safe_repl import validator
from safe_repl.policy import Permissions, PermissionLevel


def make_trees() -> dict[str, ast.AST]:
    samples = {
        "literal": "42",
        "simple_name": "x",
        "attribute_access": "obj.attr",
        "deep_attribute": "a.b.c.d.e.f.g",
        "call_attr": "obj.method(1, 2, key='v')",
        "assign_unpack": "a, b = (1, 2)",
        "subscript_assign": "arr[0] = 1",
        "complex_snippet": "for i in range(10): x = obj.method(i)\narr[i] = x",
    }
    return {name: ast.parse(code, mode="exec") for name, code in samples.items()}


def time_call(func, iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    end = time.perf_counter()
    return end - start


def bench(trees: dict[str, ast.AST], iterations: int) -> dict[str, float]:
    perms = Permissions(base_perms=PermissionLevel.UNSUPERVISED)  # allow attribute access for bench
    results = {}
    # Provide some user variables referenced by snippets to avoid validation errors
    user_vars = {"obj": object(), "arr": [], "a": [], "x": 0}
    for name, tree in trees.items():
        # Warm-up current implementation
        validator.validate_ast(tree, user_vars=user_vars, allowed_names=set(), perms=perms)

        def run_current() -> None:
            validator.validate_ast(tree, user_vars=user_vars, allowed_names=set(), perms=perms)

        total_current = time_call(run_current, iterations)
        results[name] = total_current / iterations
    return results


def pretty_print(results: dict[str, float], iterations: int) -> None:
    print(f"Benchmark: {iterations} iterations each")
    print("Average time per call (microseconds): current implementation")
    for name, sec in sorted(results.items(), key=lambda kv: kv[1]):
        print(f" - {name:15s}: {sec * 1e6:8.2f}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=2000)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    trees = make_trees()
    results = bench(trees, iterations=args.iterations)
    pretty_print(results, args.iterations)


if __name__ == "__main__":
    main()
