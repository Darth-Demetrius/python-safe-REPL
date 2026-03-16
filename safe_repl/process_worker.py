"""Worker-side execution helpers for process-isolated runtime."""

from __future__ import annotations

import contextlib
import io
import resource
from multiprocessing.connection import Connection

from .engine import safe_exec
from .policy import Permissions
from .process_protocol import (
    OP_CLOSE,
    OP_EXEC,
    OP_RESET,
    WorkerCommand,
    WorkerResponse,
    open_command_payload,
)

__all__ = [
    "build_worker_response",
    "execute_worker_code",
    "send_worker_response",
    "run_worker_command",
    "resolve_imports_for_worker",
    "run_persistent_isolated_worker",
]


def build_worker_response(
    *,
    user_vars: dict[str, object],
    result: object | None = None,
    output: str | None = None,
    exception_type: BaseException | str | None = None,
    message: str | None = None,
) -> WorkerResponse:
    """Create one normalized worker response payload for success or failure."""
    match exception_type:
        case None:
            ok = True
            message = None
        case BaseException():
            ok = False
            result = None
            message = message or str(exception_type)
            exception_type = type(exception_type).__name__
        case _:
            ok = False
            result = None
            exception_type = str(exception_type) or "RuntimeError"
            message = message or ""

    return {
        "ok": ok,
        "result": result,
        "user_vars": dict(user_vars),
        "output": output,
        "exception_type": exception_type,
        "message": message,
    }


def execute_worker_code(
    code: str,
    *,
    local_user_vars: dict[str, object],
    perms: Permissions,
) -> WorkerResponse:
    """Execute code and return one structured worker response payload."""
    output_buffer = io.StringIO()
    exc: BaseException | None = None
    result: object | None = None
    with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
        try:
            result = safe_exec(code, local_user_vars, perms=perms)
        except BaseException as err:  # noqa: BLE001
            exc = err

    output = output_buffer.getvalue() or None

    return build_worker_response(user_vars=local_user_vars, output=output, exception_type=exc, result=result)


def send_worker_response(conn: Connection, response: WorkerResponse) -> bool:
    """Send worker response; return false when transport is unusable."""
    try:
        conn.send(response)
        return True
    except Exception as send_exc:  # noqa: BLE001
        transport_error = build_worker_response(
            user_vars={},
            exception_type="RuntimeError",
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
) -> WorkerResponse:
    """Apply one persistent-worker command and return one response payload."""
    operation = command["op"]

    if operation == OP_CLOSE:
        return build_worker_response(user_vars=local_user_vars)

    if operation == OP_RESET:
        requested_vars = command["user_vars"]
        local_user_vars.clear()
        local_user_vars.update(requested_vars)
        return build_worker_response(user_vars=local_user_vars)

    if operation == OP_EXEC:
        code = command["code"]
        if code is None:
            return build_worker_response(
                user_vars=local_user_vars,
                exception_type="RuntimeError",
                message="Missing or invalid code payload.",
            )
        return execute_worker_code(code, local_user_vars=local_user_vars, perms=perms)

    return build_worker_response(
        user_vars=local_user_vars,
        exception_type="RuntimeError",
        message="Unknown operation.",
    )


def resolve_imports_for_worker(perms: Permissions) -> None:
    """Resolve imports in worker and inject them into child execution builtins."""
    builtins_scope = perms.globals_dict.get("__builtins__")
    if not isinstance(builtins_scope, dict):
        return

    blocked_symbols = perms.blocked_symbols
    for spec in perms.imports:
        if not isinstance(spec["module"], tuple) or len(spec["module"]) != 2:
            continue
        module_name, module_alias = spec["module"]
        module = __import__(module_name)

        if not spec["names"]:
            builtins_scope[module_alias] = module
            continue

        if spec["names"][0][0] == "*":
            for attr_name, import_alias in spec["names"][1:]:
                if attr_name not in blocked_symbols:
                    builtins_scope[import_alias] = getattr(module, attr_name)
            continue

        for attr_name, import_alias in spec["names"]:
            if attr_name not in blocked_symbols:
                builtins_scope[import_alias] = getattr(module, attr_name)


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

        command = open_command_payload(payload)
        if command is None:
            if not send_worker_response(
                conn,
                build_worker_response(
                    user_vars=local_user_vars,
                    exception_type="RuntimeError",
                    message="Invalid command payload.",
                ),
            ):
                break
            continue

        response = run_worker_command(
            command,
            local_user_vars=local_user_vars,
            perms=perms,
        )
        if not send_worker_response(conn, response):
            break
        if command["op"] == OP_CLOSE:
            break

    conn.close()
