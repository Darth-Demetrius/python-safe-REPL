"""Process lifecycle and timeout helpers for process-isolated execution."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable, Final


DEFAULT_START_METHOD: Final[str] = "fork"
PROCESS_JOIN_TIMEOUT_SECONDS: Final[float] = 0.2


def spawn_context_process(
    *,
    context: object,
    target: Callable[..., None],
    kwargs: dict[str, object],
    daemon: bool,
) -> BaseProcess:
    """Create a process from a multiprocessing context with runtime checks."""
    process_factory = getattr(context, "Process", None)
    if process_factory is None:
        raise RuntimeError("Multiprocessing context does not provide a Process factory.")

    process = process_factory(target=target, kwargs=kwargs, daemon=daemon)
    if not isinstance(process, BaseProcess):
        raise RuntimeError("Multiprocessing context returned unsupported process type.")
    return process


def validate_process_isolation_support(start_method: str) -> None:
    """Validate process-isolation prerequisites for current platform/runtime."""
    if start_method != DEFAULT_START_METHOD:
        raise RuntimeError(
            f"Unsupported process start method '{start_method}'. "
            f"Use '{DEFAULT_START_METHOD}' for process-isolated mode."
        )
    if DEFAULT_START_METHOD not in multiprocessing.get_all_start_methods():
        raise RuntimeError("Process-isolated mode is not supported on this platform.")


def finalize_process(process: BaseProcess, *, terminate: bool = False) -> None:
    """Finalize a process, optionally terminating before join/kill fallback."""
    if terminate:
        process.terminate()
    process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)


def await_worker_response(
    parent_conn: Connection,
    process: BaseProcess,
    *,
    timeout: float | None,
) -> object:
    """Receive worker payload or enforce timeout by terminating worker."""
    if not parent_conn.poll(timeout):
        finalize_process(process, terminate=True)
        raise TimeoutError("Execution timed out.")
    return parent_conn.recv()
