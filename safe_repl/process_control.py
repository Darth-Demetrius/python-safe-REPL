"""Process lifecycle and timeout helpers for process-isolated execution."""

from __future__ import annotations

import math
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable, Final

from .policy import Permissions


DEFAULT_START_METHOD: Final[str] = "fork"
PROCESS_JOIN_TIMEOUT_SECONDS: Final[float] = 0.2


def _join_or_kill(process: BaseProcess) -> None:
    """Join a process and force-kill only when it remains alive."""
    process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)


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


def supports_process_isolation() -> bool:
    """Return true when process-isolated execution is supported."""
    return DEFAULT_START_METHOD in multiprocessing.get_all_start_methods()


def timeout_for_perms(perms: Permissions) -> float | None:
    """Return IPC poll timeout derived from policy timeout settings."""
    return poll_timeout_seconds(perms.timeout_seconds)


def validate_process_isolation_support(start_method: str) -> None:
    """Validate process-isolation prerequisites for current platform/runtime."""
    if start_method != DEFAULT_START_METHOD:
        raise RuntimeError(
            f"Unsupported process start method '{start_method}'. "
            f"Use '{DEFAULT_START_METHOD}' for process-isolated mode."
        )
    if not supports_process_isolation():
        raise RuntimeError("Process-isolated mode is not supported on this platform.")


def poll_timeout_seconds(timeout_seconds: float) -> float | None:
    """Convert policy timeout to `Connection.poll` timeout semantics."""
    if timeout_seconds <= 0:
        return 0.0
    if math.isinf(timeout_seconds):
        return None
    return timeout_seconds


def terminate_process(process: BaseProcess) -> None:
    """Terminate process and force-kill if it doesn't exit promptly."""
    process.terminate()
    _join_or_kill(process)


def finalize_process(process: BaseProcess) -> None:
    """Join process, force-killing only if it remains alive."""
    _join_or_kill(process)


def await_worker_response(
    parent_conn: Connection,
    process: BaseProcess,
    *,
    timeout: float | None,
) -> object:
    """Receive worker payload or enforce timeout by terminating worker."""
    if not parent_conn.poll(timeout):
        terminate_process(process)
        raise TimeoutError("Execution timed out.")
    return parent_conn.recv()
