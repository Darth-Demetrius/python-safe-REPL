"""Execution engine for the RestrictedPython-based safe REPL.

This module replaces both ``engine.py`` (execution) and ``validator.py``
(AST safety) from the original.  RestrictedPython's ``compile_restricted_*``
functions transform user source at compile time, injecting guard hook calls
(``_getattr_``, ``_write_``, etc.) and disabling dangerous constructs.  We
supply appropriate implementations of those guards via ``Permissions``.

Key differences from the original ``safe_exec``
-------------------------------------------------
* No subprocess / ``multiprocessing`` required.
* Returns ``(result, captured_output)`` – Discord-friendly: no stdout
  side-effects from the exec call.
* Timeout is enforced via a ``threading.Timer`` + ``ctypes`` async-exception
  injection into the executing thread.  This is the same technique used by
  production Discord bot toolkits such as Jishaku and discord-ext-menus.
  The thread *may* linger briefly after cancellation but the calling coroutine
  will no longer be blocked.
* Memory is bounded via ``tracemalloc`` peak tracking (same as original).
* Attribute access restrictions (blocking private/dunder names) are enforced
  by RestrictedPython at compile time.
"""

from __future__ import annotations

import ast
import ctypes
import threading
import tracemalloc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from RestrictedPython import compile_restricted_exec
from RestrictedPython.PrintCollector import PrintCollector

if TYPE_CHECKING:
    from .policy import Permissions


__all__ = [
    "ExecResult",
    "exec_restricted",
]





# ---------------------------------------------------------------------------
# Exec result
# ---------------------------------------------------------------------------

@dataclass
class ExecResult:
    """Outcome of one ``exec_restricted`` call.

    Attributes:
        result: The value of the last expression, or ``None`` for statements.
        output: Captured text from ``print()`` calls within the snippet.
        ok: ``True`` when execution completed without raising an exception.
        exception: The exception if ``ok`` is ``False``, otherwise ``None``.
    """

    result: object | None
    output: str
    ok: bool
    exception: BaseException | None = field(default=None)


# ---------------------------------------------------------------------------
# Thread-injection timeout
# ---------------------------------------------------------------------------

def _inject_exception_into_thread(thread_id: int, exc_type: type) -> None:
    """Asynchronously raise *exc_type* inside the given thread.

    Uses the CPython C-API ``PyThreadState_SetAsyncExc`` to inject an exception
    into a running Python thread.  The exception will be raised the next time
    the thread executes a Python opcode after the injection.

    Note: This is a *best-effort* mechanism – threads blocked in C extensions
    or tight bytecode loops may not respond immediately.  For most user-submitted
    REPL snippets this is sufficient.

    Args:
        thread_id: ``threading.Thread.ident`` of the target thread.
        exc_type: Exception type to inject (e.g. ``TimeoutError``).
    """
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread_id),
        ctypes.py_object(exc_type),
    )
    # res == 0: thread not found (may have already finished – that's fine)
    # res  > 1: multiple threads matched (should never happen with a real ident)


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

def exec_restricted(
    code: str,
    user_vars: dict[str, object],
    *,
    perms: "Permissions",
) -> ExecResult:
    """Compile, validate, and execute *code* under a ``Permissions`` policy.

    The function:
    1. Compiles the source with ``RestrictedPython.compile_restricted_exec``
       (which transforms attribute/item access and write operations into guarded
       versions).
    2. Detects single-expression input and returns its value as ``result``.
    3. Captures ``print`` output via ``RestrictedPython.PrintCollector``.
    4. Enforces a wall-clock timeout using a ``threading.Timer`` that injects
       ``TimeoutError`` into the executing thread.
    5. Tracks peak memory allocation via ``tracemalloc``.

    Args:
        code: Raw Python source submitted by the user.
        user_vars: Mutable namespace dict; will be updated with any new names
                   defined by the snippet.  Passed as the *locals* dict to
                   ``exec``/``eval``.
        perms: Active execution policy.

    Returns:
        An ``ExecResult`` describing the outcome.

    Raises:
        SyntaxError: If the source cannot be compiled (including RestrictedPython
                     security violations detected at compile time).
    """
    # ------------------------------------------------------------------
    # 1. Parse and normalize source
    # ------------------------------------------------------------------
    tree = ast.parse(code, mode="exec")
    _RESULT_KEY = "respy_result_value"
    is_single_expr = len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)

    source = code
    if is_single_expr:
        # Compile expression snippets as an assignment in exec-mode so that
        # RestrictedPython's print collector and statement machinery work.
        expr_stmt = tree.body[0]
        assert isinstance(expr_stmt, ast.Expr)
        assign = ast.Assign(
            targets=[ast.Name(id=_RESULT_KEY, ctx=ast.Store())],
            value=expr_stmt.value,
        )
        wrapped = ast.Module(body=[assign], type_ignores=[])
        ast.fix_missing_locations(wrapped)
        source = ast.unparse(wrapped)

    # ------------------------------------------------------------------
    # 2. Compile
    # ------------------------------------------------------------------
    compile_result = compile_restricted_exec(source)
    if compile_result.errors:
        raise SyntaxError("\n".join(compile_result.errors))

    code_obj = compile_result.code
    if code_obj is None:
        # Empty / comment-only source.
        return ExecResult(result=None, output="", ok=True)

    # ------------------------------------------------------------------
    # 3. Build per-execution globals (shallow-copy + fresh PrintCollector)
    # ------------------------------------------------------------------
    glb = dict(perms.restricted_globals)  # shallow copy – guards are shared
    _sys_names = set(glb.keys())  # Track initial system names
    # Pre-populate with existing user variables so functions can access them
    glb.update(user_vars)
    glb["_print_"] = PrintCollector

    # ------------------------------------------------------------------
    # 4. Apply memory tracking setup
    # ------------------------------------------------------------------
    memory_limit = perms.memory_limit_bytes
    _started_tracemalloc = False
    if memory_limit is not None:
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            _started_tracemalloc = True
        tracemalloc.reset_peak()

    # ------------------------------------------------------------------
    # 5. Execute (with timeout via thread injection)
    # ------------------------------------------------------------------
    exc_holder: list[BaseException | None] = [None]
    result_holder: list[object] = [None]

    def _run() -> None:
        try:
            # Execute with glb as both globals and locals so functions can see user vars
            exec(code_obj, glb)
            if is_single_expr:
                result_holder[0] = glb.pop(_RESULT_KEY, None)
        except BaseException as exc:
            exc_holder[0] = exc

    worker = threading.Thread(target=_run, daemon=True)
    timer: threading.Timer | None = None

    try:
        if perms.timeout_seconds is not None:
            def _fire_timeout() -> None:
                if worker.ident is not None:
                    _inject_exception_into_thread(worker.ident, TimeoutError)

            timer = threading.Timer(perms.timeout_seconds, _fire_timeout)
            timer.daemon = True
            timer.start()

        worker.start()
        # Join for slightly longer than the timeout to let the injected
        # exception propagate and the thread to clean up.
        join_timeout = (
            perms.timeout_seconds + 0.5
            if perms.timeout_seconds is not None
            else None
        )
        worker.join(timeout=join_timeout)
    finally:
        if timer is not None:
            timer.cancel()

    # ------------------------------------------------------------------
    # 6. Post-execution checks
    # ------------------------------------------------------------------
    # Extract PrintCollector from execution namespace
    captured_output = ""
    collector_obj = glb.pop("_print", None)
    if callable(collector_obj):
        try:
            captured_output = str(collector_obj())
        except Exception:
            captured_output = ""

    # Extract user-defined variables from glb back to user_vars
    # (skip system names that were added during initialization)
    for key in list(glb.keys()):
        if key not in _sys_names and not key.startswith("_"):
            user_vars[key] = glb[key]

    # If the thread is still alive after the join window the timeout injection
    # didn't take effect in time (e.g. blocked in a C extension).  We surface
    # a TimeoutError to the caller but cannot kill the thread.
    if worker.is_alive():
        return ExecResult(
            result=None,
            output=captured_output,
            ok=False,
            exception=TimeoutError(
                "Execution timed out (thread still running – best-effort)."
            ),
        )

    held_exc = exc_holder[0]
    if held_exc is not None:
        return ExecResult(
            result=None,
            output=captured_output,
            ok=False,
            exception=held_exc,
        )

    # Memory peak check (after execution so the thread's allocations are counted).
    if memory_limit is not None:
        try:
            _, peak = tracemalloc.get_traced_memory()
            if peak > memory_limit:
                return ExecResult(
                    result=None,
                    output=captured_output,
                    ok=False,
                    exception=MemoryError(
                        f"Memory limit exceeded "
                        f"({peak // 1024 // 1024} MB > "
                        f"{memory_limit // 1024 // 1024} MB)."
                    ),
                )
        finally:
            if _started_tracemalloc:
                tracemalloc.stop()

    return ExecResult(
        result=result_holder[0],
        output=captured_output,
        ok=True,
    )
