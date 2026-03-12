"""Worker-side execution helpers for process-isolated runtime."""

from __future__ import annotations
import builtins
import resource
from multiprocessing.connection import Connection

from .engine import safe_exec
from .imports import NormalizedImportSpec
from .policy import Permissions
from .process_protocol import (
    PERSISTENT_OP_CLOSE,
    PERSISTENT_OP_EXEC,
    PERSISTENT_OP_RESET,
    WorkerCommand,
    WorkerErrorResponse,
    WorkerResponse,
    WorkerSuccessResponse,
    coerce_worker_command,
)


def build_error_response(*,
        exc: BaseException | str | None = None,
        message: str = ""
    ) -> WorkerErrorResponse:
    """Create an error payload with explicit exception metadata."""
    if isinstance(exc, BaseException):
        message = message or str(exc)
        exc = type(exc).__name__
    elif exc is None:
        exc = "RuntimeError"

    return {
        "ok": False,
        "exception_type": exc,
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
        return build_error_response(exc=exc)


def send_worker_response(conn: Connection, response: WorkerResponse) -> bool:
    """Send worker response; return false when transport is unusable."""
    try:
        conn.send(response)
        return True
    except Exception as send_exc:  # noqa: BLE001
        transport_error = build_error_response(
            message=f"Failed to serialize isolated worker response: {send_exc}",
        )
        try:
            conn.send(transport_error)
            return True
        except Exception:  # noqa: BLE001
            return False


def run_worker_command(
    command: WorkerCommand,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> tuple[WorkerResponse, bool]:
    """Apply one persistent-worker command and return response plus continue flag."""
    operation = command["op"]

    if operation == PERSISTENT_OP_CLOSE:
        return build_worker_success_response(result=None, user_vars=local_user_vars), False

    if operation == PERSISTENT_OP_RESET:
        requested_vars = command["user_vars"]
        local_user_vars.clear()
        local_user_vars.update(requested_vars)
        return build_worker_success_response(result=None, user_vars=local_user_vars), True

    if operation == PERSISTENT_OP_EXEC:
        code = command["code"]
        if code is None:
            return build_error_response(message="Missing or invalid code payload."), True
        return execute_worker_code(code, local_user_vars=local_user_vars, perms=perms), True

    return build_error_response(message="Unknown operation."), True


def apply_worker_response_to_user_vars(
    response: object,
    user_vars: dict[str, object],
) -> object | None:
    """Validate worker response, map errors, and sync returned user variables."""
    if not isinstance(response, dict):
        raise RuntimeError("Invalid response from isolated worker.")

    ok_value = response.get("ok")
    if not isinstance(ok_value, bool):
        raise RuntimeError("Invalid response status from isolated worker.")
    if not ok_value:
        exception_type = response.get("exception_type")
        message = response.get("message")
        if not isinstance(exception_type, str) or not isinstance(message, str):
            raise RuntimeError("Invalid error payload from isolated worker.")
        raise_worker_exception(exception_type, message)

    synced_user_vars = response.get("user_vars")
    if not isinstance(synced_user_vars, dict):
        raise RuntimeError("Isolated worker returned invalid user-vars payload.")

    user_vars.clear()
    user_vars.update(synced_user_vars)
    return response.get("result")


def resolve_imports_for_worker(perms: Permissions) -> None:
    """Resolve imports in worker and inject them into child execution builtins."""
    builtins_scope = perms.globals_dict.get("__builtins__")
    if not isinstance(builtins_scope, dict):
        return

    import_specs = perms.imports
    blocked_symbols = perms.blocked_symbols
    for spec in import_specs:
        if not isinstance(spec["module"], tuple) or len(spec["module"]) != 2:
            continue
        module_name, module_alias = spec["module"]
        module = __import__(module_name)

        if not spec["names"]:
            # No explicit imports means we import the module itself under the alias
            builtins_scope[module_alias] = module
            continue

        if spec["names"][0][0] == "*":
            # Star import: inject the pre-expanded names from the spec directly.
            # The module alias is NOT injected - only the expanded public names
            # are accessible (matching policy.py's imported_symbols logic).
            for attr_name, import_alias in spec["names"][1:]:
                if attr_name not in blocked_symbols:
                    builtins_scope[import_alias] = getattr(module, attr_name)
            continue

        for attr_name, import_alias in spec["names"]:
            if attr_name not in blocked_symbols:
                attr = getattr(module, attr_name)
                builtins_scope[import_alias] = attr


def run_persistent_isolated_worker(
    conn: Connection,
    *,
    perms: Permissions,
    initial_user_vars: dict[str, object],
) -> None:
    """Run command loop for a long-lived isolated worker process."""
    if perms.memory_limit_bytes is not None:
        _, hard_limit = resource.getrlimit(resource.RLIMIT_AS)
        if hard_limit in (-1, resource.RLIM_INFINITY):
            mem_limit = perms.memory_limit_bytes
        else:
            mem_limit = min(perms.memory_limit_bytes, hard_limit)
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))

    local_user_vars = dict(initial_user_vars)
    resolve_imports_for_worker(perms)

    while True:
        try:
            payload = conn.recv()
        except (EOFError, OSError):
            break

        command = coerce_worker_command(payload)
        if command is None:
            if not send_worker_response(conn, build_error_response(message="Invalid command payload.")):
                break
            continue

        response, should_continue = run_worker_command(
            command,
            local_user_vars=local_user_vars,
            perms=perms,
        )
        if not send_worker_response(conn, response):
            break
        if not should_continue:
            break

    conn.close()
