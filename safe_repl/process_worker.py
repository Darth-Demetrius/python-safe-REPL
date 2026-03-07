"""Worker-side execution helpers for process-isolated runtime."""

from __future__ import annotations

import builtins
from multiprocessing.connection import Connection

from .engine import safe_exec
from .policy import MEMORY_LIMIT_INFINITY, Permissions
from .process_protocol import (
    PERSISTENT_OP_CLOSE,
    PERSISTENT_OP_EXEC,
    PERSISTENT_OP_RESET,
    PERSISTENT_OPS,
    WorkerCommand,
    WorkerErrorResponse,
    WorkerResponse,
    WorkerSuccessResponse,
    coerce_worker_command,
)

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on some platforms
    resource = None  # type: ignore[assignment]


_UNKNOWN_OPERATION_MESSAGE = "Unknown persistent worker operation."


def _build_error_response(*, exception_type: str, message: str) -> WorkerErrorResponse:
    """Create an error payload with explicit exception metadata."""
    return {
        "ok": False,
        "exception_type": exception_type,
        "message": message,
    }


def raise_worker_exception(exception_type: str, message: str) -> None:
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


def apply_worker_memory_limit(memory_limit_bytes: int) -> None:
    """Apply best-effort address-space/process memory limits in the worker."""
    if resource is None:
        return
    if memory_limit_bytes >= MEMORY_LIMIT_INFINITY:
        return

    soft_hard = (memory_limit_bytes, memory_limit_bytes)
    for limit_name in ("RLIMIT_AS", "RLIMIT_DATA"):
        if hasattr(resource, limit_name):
            resource.setrlimit(getattr(resource, limit_name), soft_hard)


def build_worker_error_response(message: str) -> WorkerErrorResponse:
    """Create a runtime worker error payload for transport failures."""
    return _build_error_response(exception_type="RuntimeError", message=message)


def build_worker_success_response(
    *,
    result: object | None,
    user_vars: dict[str, object],
) -> WorkerSuccessResponse:
    """Create a success payload that includes the latest worker user vars."""
    return {
        "ok": True,
        "result": result,
        "user_vars": dict(user_vars),
    }


def build_worker_exception_response(exc: BaseException) -> WorkerErrorResponse:
    """Convert a raised exception into worker error payload format."""
    return _build_error_response(exception_type=type(exc).__name__, message=str(exc))


def execute_worker_code(
    code: str,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> WorkerResponse:
    """Execute code and return a structured worker response payload."""
    try:
        result = safe_exec(code, local_user_vars, perms=perms)
        return build_worker_success_response(result=result, user_vars=local_user_vars)
    except BaseException as exc:  # noqa: BLE001
        return build_worker_exception_response(exc)


def send_worker_response(conn: Connection, response: WorkerResponse) -> bool:
    """Send worker response; return false when transport is unusable."""
    try:
        conn.send(response)
        return True
    except Exception as send_exc:  # noqa: BLE001
        transport_error = build_worker_error_response(
            f"Failed to serialize isolated worker response: {send_exc}"
        )
        try:
            conn.send(transport_error)
            return True
        except Exception:  # noqa: BLE001
            return False


def apply_persistent_command(
    command: WorkerCommand,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> tuple[WorkerResponse, bool]:
    """Apply one persistent-worker command and return response plus continue flag."""
    operation = command.get("op")
    if not isinstance(operation, str) or operation not in PERSISTENT_OPS:
        return build_worker_error_response(_UNKNOWN_OPERATION_MESSAGE), True

    if operation == PERSISTENT_OP_CLOSE:
        return build_worker_success_response(result=None, user_vars=local_user_vars), False

    if operation == PERSISTENT_OP_RESET:
        requested_vars = command.get("user_vars")
        if not isinstance(requested_vars, dict):
            requested_vars = {}
        local_user_vars.clear()
        local_user_vars.update(requested_vars)
        return build_worker_success_response(result=None, user_vars=local_user_vars), True

    if operation == PERSISTENT_OP_EXEC:
        code = command.get("code")
        if not isinstance(code, str):
            return build_worker_error_response("Missing or invalid code payload."), True
        return execute_worker_code(code, local_user_vars=local_user_vars, perms=perms), True

    return build_worker_error_response(_UNKNOWN_OPERATION_MESSAGE), True


def apply_success_response_to_user_vars(
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
        raise_worker_exception(exception_type, message)
    if ok_value is not True:
        raise RuntimeError("Invalid response status from isolated worker.")

    synced_user_vars = response.get("user_vars")
    if not isinstance(synced_user_vars, dict):
        raise RuntimeError("Isolated worker returned invalid user-vars payload.")

    user_vars.clear()
    user_vars.update(synced_user_vars)
    return response.get("result")


def run_isolated_worker(
    conn: Connection,
    *,
    code: str,
    user_vars: dict[str, object],
    perms: Permissions,
) -> None:
    """Execute one snippet in a child process and send a structured response."""
    local_user_vars = dict(user_vars)
    try:
        apply_worker_memory_limit(perms.memory_limit_bytes)
        response = execute_worker_code(code, local_user_vars=local_user_vars, perms=perms)
    except BaseException as exc:  # noqa: BLE001
        response = build_worker_exception_response(exc)

    try:
        send_worker_response(conn, response)
    finally:
        conn.close()


def run_persistent_isolated_worker(
    conn: Connection,
    *,
    initial_user_vars: dict[str, object],
    perms: Permissions,
) -> None:
    """Run command loop for a long-lived isolated worker process."""
    local_user_vars = dict(initial_user_vars)
    apply_worker_memory_limit(perms.memory_limit_bytes)

    while True:
        try:
            payload = conn.recv()
        except (EOFError, OSError):
            break

        command = coerce_worker_command(payload)
        if command is None:
            if not send_worker_response(conn, build_worker_error_response("Invalid command payload.")):
                break
            continue

        response, should_continue = apply_persistent_command(
            command,
            local_user_vars=local_user_vars,
            perms=perms,
        )
        if not send_worker_response(conn, response):
            break
        if not should_continue:
            break

    conn.close()
