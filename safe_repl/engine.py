"""Execution engine for parsing, validating, and running user snippets.

Coordinates timeout and memory controls around validated evaluation/exec.
"""

import ast
from collections.abc import Callable
import signal
from types import FrameType
import tracemalloc

from .policy import MEMORY_LIMIT_INFINITY, Permissions
from .validator import validate_ast


SignalHandler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None
TimerState = tuple[float, float]


def collect_allowed_names(
    user_vars: dict[str, object],
    global_scope: dict[str, object],
) -> set[str]:
    """Build name set visible to validation from locals + execution globals."""
    allowed_names = set(user_vars.keys())
    for name, value in global_scope.items():
        if name == "__builtins__":
            continue
        if isinstance(value, dict):
            allowed_names.update(value.keys())
        else:
            allowed_names.add(name)
    return allowed_names


def _configure_memory_tracking(memory_limit: int) -> bool:
    """Enable memory peak tracking when a finite limit is configured."""
    memory_limit_active = memory_limit < MEMORY_LIMIT_INFINITY
    if not memory_limit_active:
        return False

    if not tracemalloc.is_tracing():
        tracemalloc.start()
        trace_started = True
    else:
        trace_started = False
    tracemalloc.reset_peak()
    return trace_started


def _start_timeout(timeout_seconds: float) -> tuple[SignalHandler, TimerState | None]:
    """Install SIGALRM timeout handler and return previous signal/timer state."""
    if timeout_seconds >= float("inf"):
        return None, None

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _handle_timeout(_signum, _frame):
        raise TimeoutError("Execution timed out.")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    return previous_handler, previous_timer


def safe_exec(
    code: str,
    user_vars: dict[str, object],
    *,
    perms: Permissions,
) -> object | None:
    """Parse, validate, and execute one snippet under a `Permissions` policy.

    Returns expression result for single-expression input, otherwise `None`.
    """
    global_scope = perms.globals_dict
    timeout_seconds = perms.timeout_seconds
    memory_limit = perms.memory_limit_bytes
    trace_started = _configure_memory_tracking(memory_limit)
    memory_limit_active = memory_limit < MEMORY_LIMIT_INFINITY
    allowed_names = collect_allowed_names(user_vars, global_scope)
    previous_handler, previous_timer = _start_timeout(timeout_seconds)

    try:
        tree = ast.parse(code, mode="exec")
        validate_ast(tree, user_vars, allowed_names, perms)

        if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
            expr = ast.Expression(tree.body[0].value)
            ast.fix_missing_locations(expr)
            result = eval(compile(expr, "<safe_repl>", "eval"), global_scope, user_vars)
        else:
            exec(compile(tree, "<safe_repl>", "exec"), global_scope, user_vars)
            result = None

        if memory_limit_active:
            _, peak = tracemalloc.get_traced_memory()
            if peak > memory_limit:
                raise RuntimeError("Memory limit exceeded.")
        return result
    finally:
        if previous_timer is not None:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        if previous_handler is not None:
            signal.signal(signal.SIGALRM, previous_handler)
        if trace_started:
            tracemalloc.stop()
