"""Subprocess execution runtime for safe_repl.

This module contains process-specific worker, IPC, and lifecycle helpers used
by both one-shot isolated execution and persistent subprocess sessions.
"""

from __future__ import annotations

import builtins
import math
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable, Final, TypedDict

from .engine import safe_exec
from .policy import MEMORY_LIMIT_INFINITY, Permissions

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on some platforms
    resource = None  # type: ignore[assignment]


_DEFAULT_START_METHOD: Final[str] = "fork"
_PROCESS_JOIN_TIMEOUT_SECONDS: Final[float] = 0.2
_PERSISTENT_OP_EXEC: Final[str] = "exec"
_PERSISTENT_OP_RESET: Final[str] = "reset"
_PERSISTENT_OP_CLOSE: Final[str] = "close"
_PERSISTENT_OPS: Final[set[str]] = {
    _PERSISTENT_OP_EXEC,
    _PERSISTENT_OP_RESET,
    _PERSISTENT_OP_CLOSE,
}


class _WorkerSuccessResponse(TypedDict):
    ok: bool
    result: object | None
    user_vars: dict[str, object]


class _WorkerErrorResponse(TypedDict):
    ok: bool
    exception_type: str
    message: str


class _WorkerCommand(TypedDict, total=False):
    op: str
    code: str
    user_vars: dict[str, object]


WorkerResponse = _WorkerSuccessResponse | _WorkerErrorResponse


# ---------------------------------------------------------------------------
# Context/process helpers
# ---------------------------------------------------------------------------


def _spawn_context_process(
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


def _coerce_worker_command(payload: object) -> _WorkerCommand | None:
    """Best-effort parse of inbound IPC payload into worker command schema."""
    if not isinstance(payload, dict):
        return None

    command: _WorkerCommand = {}

    op = payload.get("op")
    if op is not None:
        if not isinstance(op, str):
            return None
        command["op"] = op

    code = payload.get("code")
    if code is not None:
        if not isinstance(code, str):
            return None
        command["code"] = code

    user_vars = payload.get("user_vars")
    if user_vars is not None:
        if not isinstance(user_vars, dict):
            return None
        command["user_vars"] = user_vars

    return command


def supports_process_isolation() -> bool:
    """Return true when process-isolated execution is supported."""
    return _DEFAULT_START_METHOD in multiprocessing.get_all_start_methods()


def _timeout_for_perms(perms: Permissions) -> float | None:
    """Return IPC poll timeout derived from policy timeout settings."""
    return _poll_timeout_seconds(perms.timeout_seconds)


def _validate_process_isolation_support(start_method: str) -> None:
    """Validate process-isolation prerequisites for current platform/runtime."""
    if start_method != _DEFAULT_START_METHOD:
        raise RuntimeError(
            f"Unsupported process start method '{start_method}'. "
            f"Use '{_DEFAULT_START_METHOD}' for process-isolated mode."
        )
    if not supports_process_isolation():
        raise RuntimeError("Process-isolated mode is not supported on this platform.")


def _poll_timeout_seconds(timeout_seconds: float) -> float | None:
    """Convert policy timeout to `Connection.poll` timeout semantics."""
    if timeout_seconds <= 0:
        return 0.0
    if math.isinf(timeout_seconds):
        return None
    return timeout_seconds


# ---------------------------------------------------------------------------
# Worker response helpers
# ---------------------------------------------------------------------------


def _raise_worker_exception(exception_type: str, message: str) -> None:
    """Map worker-reported exception metadata into local exception types."""
    if exception_type == "TimeoutError":
        raise TimeoutError(message)
    if exception_type == "ValueError":
        raise ValueError(message)
    if exception_type == "MemoryError":
        raise MemoryError(message)
    if exception_type == "RuntimeError":
        raise RuntimeError(message)

    candidate = getattr(builtins, exception_type, None)
    if isinstance(candidate, type) and issubclass(candidate, Exception):
        raise candidate(message)

    raise RuntimeError(f"Worker raised {exception_type}: {message}")


def _apply_worker_memory_limit(memory_limit_bytes: int) -> None:
    """Apply best-effort address-space/process memory limits in the worker."""
    if resource is None:
        return
    if memory_limit_bytes >= MEMORY_LIMIT_INFINITY:
        return

    soft_hard = (memory_limit_bytes, memory_limit_bytes)
    for limit_name in ("RLIMIT_AS", "RLIMIT_DATA"):
        if hasattr(resource, limit_name):
            resource.setrlimit(getattr(resource, limit_name), soft_hard)


def _terminate_process(process: BaseProcess) -> None:
    """Terminate process and force-kill if it doesn't exit promptly."""
    process.terminate()
    process.join(timeout=_PROCESS_JOIN_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=_PROCESS_JOIN_TIMEOUT_SECONDS)


def _finalize_process(process: BaseProcess) -> None:
    """Join process, force-killing only if it remains alive."""
    process.join(timeout=_PROCESS_JOIN_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=_PROCESS_JOIN_TIMEOUT_SECONDS)


def _build_worker_error_response(message: str) -> _WorkerErrorResponse:
    """Create a runtime worker error payload for transport failures."""
    return {
        "ok": False,
        "exception_type": "RuntimeError",
        "message": message,
    }


def _build_worker_success_response(
    *,
    result: object | None,
    user_vars: dict[str, object],
) -> _WorkerSuccessResponse:
    """Create a success payload that includes the latest worker user vars."""
    return {
        "ok": True,
        "result": result,
        "user_vars": dict(user_vars),
    }


def _build_worker_exception_response(exc: BaseException) -> _WorkerErrorResponse:
    """Convert a raised exception into worker error payload format."""
    return {
        "ok": False,
        "exception_type": type(exc).__name__,
        "message": str(exc),
    }


def _execute_worker_code(
    code: str,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> WorkerResponse:
    """Execute code and return a structured worker response payload."""
    try:
        result = safe_exec(code, local_user_vars, perms=perms)
        return _build_worker_success_response(result=result, user_vars=local_user_vars)
    except BaseException as exc:  # noqa: BLE001
        return _build_worker_exception_response(exc)


def _send_worker_response(conn: Connection, response: WorkerResponse) -> bool:
    """Send worker response; return false when transport is unusable."""
    try:
        conn.send(response)
        return True
    except Exception as send_exc:  # noqa: BLE001
        fallback = _build_worker_error_response(
            f"Failed to serialize isolated worker response: {send_exc}"
        )
        try:
            conn.send(fallback)
            return True
        except Exception:  # noqa: BLE001
            return False


def _apply_persistent_command(
    command: _WorkerCommand,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> tuple[WorkerResponse, bool]:
    """Apply one persistent-worker command and return response plus continue flag."""
    operation = command.get("op")

    if not isinstance(operation, str) or operation not in _PERSISTENT_OPS:
        return _build_worker_error_response("Unknown persistent worker operation."), True

    if operation == _PERSISTENT_OP_CLOSE:
        return _build_worker_success_response(result=None, user_vars=local_user_vars), False

    if operation == _PERSISTENT_OP_RESET:
        requested_vars = command.get("user_vars")
        if not isinstance(requested_vars, dict):
            requested_vars = {}
        local_user_vars.clear()
        local_user_vars.update(requested_vars)
        return _build_worker_success_response(result=None, user_vars=local_user_vars), True

    if operation == _PERSISTENT_OP_EXEC:
        code = command.get("code")
        if not isinstance(code, str):
            return _build_worker_error_response("Missing or invalid code payload."), True
        return _execute_worker_code(code, local_user_vars=local_user_vars, perms=perms), True

    return _build_worker_error_response("Unknown persistent worker operation."), True


def _apply_success_response_to_user_vars(
    response: object,
    user_vars: dict[str, object],
) -> object | None:
    """Validate worker response, map errors, and sync returned user variables."""
    if not isinstance(response, dict):
        raise RuntimeError("Invalid response from isolated worker.")

    ok_value = response.get("ok")
    if ok_value is False:
        exception_type = response.get("exception_type")
        message = response.get("message")
        if not isinstance(exception_type, str) or not isinstance(message, str):
            raise RuntimeError("Invalid error payload from isolated worker.")
        _raise_worker_exception(exception_type, message)
    if ok_value is not True:
        raise RuntimeError("Invalid response status from isolated worker.")

    synced_user_vars = response.get("user_vars")
    if not isinstance(synced_user_vars, dict):
        raise RuntimeError("Isolated worker returned invalid user-vars payload.")

    user_vars.clear()
    user_vars.update(synced_user_vars)
    return response.get("result")


# ---------------------------------------------------------------------------
# Worker process entrypoints
# ---------------------------------------------------------------------------


def _run_isolated_worker(
    conn: Connection,
    *,
    code: str,
    user_vars: dict[str, object],
    perms: Permissions,
) -> None:
    """Execute one snippet in a child process and send a structured response."""
    local_user_vars = dict(user_vars)
    try:
        _apply_worker_memory_limit(perms.memory_limit_bytes)
        response = _execute_worker_code(code, local_user_vars=local_user_vars, perms=perms)
    except BaseException as exc:  # noqa: BLE001
        response = _build_worker_exception_response(exc)

    try:
        _send_worker_response(conn, response)
    finally:
        conn.close()


def _run_persistent_isolated_worker(
    conn: Connection,
    *,
    initial_user_vars: dict[str, object],
    perms: Permissions,
) -> None:
    """Run command loop for a long-lived isolated worker process."""
    local_user_vars = dict(initial_user_vars)
    _apply_worker_memory_limit(perms.memory_limit_bytes)

    while True:
        try:
            payload = conn.recv()
        except (EOFError, OSError):
            break

        command = _coerce_worker_command(payload)
        if command is None:
            if not _send_worker_response(conn, _build_worker_error_response("Invalid command payload.")):
                break
            continue

        response, should_continue = _apply_persistent_command(
            command,
            local_user_vars=local_user_vars,
            perms=perms,
        )
        if not _send_worker_response(conn, response):
            break
        if not should_continue:
            break

    conn.close()


def _await_worker_response(
    parent_conn: Connection,
    process: BaseProcess,
    *,
    timeout: float | None,
) -> object:
    """Receive worker payload or enforce timeout by terminating worker."""
    if not parent_conn.poll(timeout):
        _terminate_process(process)
        raise TimeoutError("Execution timed out.")
    return parent_conn.recv()


# ---------------------------------------------------------------------------
# Public subprocess execution APIs
# ---------------------------------------------------------------------------


def safe_exec_process_isolated(
    code: str,
    user_vars: dict[str, object],
    *,
    perms: Permissions,
    start_method: str = _DEFAULT_START_METHOD,
) -> object | None:
    """Execute one snippet in a child process and sync state back to caller.

    Notes:
    - This mode currently targets POSIX `fork` start method.
    - Return value and synchronized user vars must be pickle-serializable.
    """
    _validate_process_isolation_support(start_method)

    ctx = multiprocessing.get_context(start_method)
    parent_conn, child_conn = ctx.Pipe(duplex=False)

    process = _spawn_context_process(
        context=ctx,
        target=_run_isolated_worker,
        kwargs={
            "conn": child_conn,
            "code": code,
            "user_vars": user_vars,
            "perms": perms,
        },
        daemon=True,
    )

    timeout = _timeout_for_perms(perms)
    process.start()
    child_conn.close()

    try:
        response = _await_worker_response(parent_conn, process, timeout=timeout)
    finally:
        parent_conn.close()
        _finalize_process(process)
    return _apply_success_response_to_user_vars(response, user_vars)


class PersistentSubprocessSession:
    """Long-lived subprocess-backed executor for one `SafeSession` instance."""

    def __init__(
        self,
        *,
        perms: Permissions,
        user_vars: dict[str, object],
        start_method: str = _DEFAULT_START_METHOD,
    ):
        _validate_process_isolation_support(start_method)

        self._perms = perms
        self._user_vars = user_vars
        self._start_method = start_method
        self._parent_conn: Connection | None = None
        self._process: BaseProcess | None = None

    @property
    def is_open(self) -> bool:
        """Return true when worker process and control pipe are active."""
        return (
            self._process is not None
            and self._process.is_alive()
            and self._parent_conn is not None
        )

    def open(self) -> None:
        """Start persistent worker if it is not already running."""
        if self.is_open:
            return

        ctx = multiprocessing.get_context(self._start_method)
        parent_conn, child_conn = ctx.Pipe(duplex=True)
        process = _spawn_context_process(
            context=ctx,
            target=_run_persistent_isolated_worker,
            kwargs={
                "conn": child_conn,
                "initial_user_vars": dict(self._user_vars),
                "perms": self._perms,
            },
            daemon=True,
        )
        process.start()
        child_conn.close()

        self._parent_conn = parent_conn
        self._process = process

    def close(self) -> None:
        """Close persistent worker and release process resources."""
        process = self._process
        parent_conn = self._parent_conn
        self._process = None
        self._parent_conn = None

        if process is None:
            if parent_conn is not None:
                parent_conn.close()
            return

        try:
            if parent_conn is not None and process.is_alive():
                try:
                    parent_conn.send({"op": _PERSISTENT_OP_CLOSE})
                    if parent_conn.poll(_PROCESS_JOIN_TIMEOUT_SECONDS):
                        parent_conn.recv()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if parent_conn is not None:
                parent_conn.close()
            _finalize_process(process)

    def reopen(self) -> None:
        """Restart persistent worker with current local user variable state."""
        self.close()
        self.open()

    def exec(self, code: str) -> object | None:
        """Execute one snippet through the persistent worker."""
        response = self._request(
            {"op": _PERSISTENT_OP_EXEC, "code": code},
            timeout=_timeout_for_perms(self._perms),
        )
        return _apply_success_response_to_user_vars(response, self._user_vars)

    def reset(self) -> None:
        """Clear worker and local user variable state."""
        response = self._request(
            {"op": _PERSISTENT_OP_RESET, "user_vars": {}},
            timeout=_timeout_for_perms(self._perms),
        )
        _apply_success_response_to_user_vars(response, self._user_vars)

    def _request(self, command: dict[str, object], *, timeout: float | None) -> object:
        """Send command to worker and return response payload."""
        if not self.is_open:
            raise RuntimeError("Persistent subprocess session is not open.")

        assert self._parent_conn is not None
        assert self._process is not None

        try:
            self._parent_conn.send(command)
            return _await_worker_response(self._parent_conn, self._process, timeout=timeout)
        except TimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RuntimeError(f"Persistent subprocess session failed: {exc}") from exc
