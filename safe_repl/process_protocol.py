"""IPC protocol primitives for process-isolated execution."""

from __future__ import annotations

from typing import Final, Literal, TypedDict, cast


OP_EXEC: Final[str] = "exec"
OP_RESET: Final[str] = "reset"
OP_CLOSE: Final[str] = "close"
OPS: Final[set[str]] = {
    OP_EXEC,
    OP_RESET,
    OP_CLOSE,
}

PersistentOp = Literal["exec", "reset", "close"]


class WorkerResponse(TypedDict):
    """Serialized worker response payload for all persistent operations."""
    ok: bool
    result: object | None
    user_vars: dict[str, object]
    output: str | None
    exception_type: str | None
    message: str | None


class WorkerCommand(TypedDict):
    """Persistent worker command payload."""
    op: PersistentOp
    code: str | None
    user_vars: dict[str, object]

def open_command_payload(payload: object) -> WorkerCommand | None:
    """Best-effort parse of inbound IPC payload into worker command schema."""
    if not isinstance(payload, dict):
        return None

    op: PersistentOp | None = None
    code: str | None = None
    user_vars: dict[str, object] = {}

    for key, value in payload.items():
        match key:
            case "op":
                if not isinstance(value, str) or value not in OPS:
                    return None
                op = cast(PersistentOp, value)
            case "code":
                if not isinstance(value, str):
                    return None
                code = value
            case "user_vars":
                if not isinstance(value, dict):
                    return None
                user_vars = cast(dict[str, object], value)
            case _:
                continue

    if op is None:
        return None

    return {
        "op": op,
        "code": code,
        "user_vars": user_vars,
    }


def open_response_payload(payload: object) -> WorkerResponse:
    """Validate one worker response payload received over IPC."""
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response from isolated worker.")

    ok_value = payload.get("ok")
    user_vars = payload.get("user_vars")
    exception_type = payload.get("exception_type")
    message = payload.get("message")
    result = payload.get("result")
    output = payload.get("output")

    if not isinstance(ok_value, bool):
        raise RuntimeError("Invalid response status from isolated worker.")
    if not isinstance(user_vars, dict):
        raise RuntimeError("Isolated worker returned invalid user-vars payload.")
    if not (isinstance(output, str) or output is None):
        raise RuntimeError("Isolated worker returned invalid output payload.")

    if not (isinstance(exception_type, str) or exception_type is None):
        raise RuntimeError("Invalid exception metadata from isolated worker.")
    if not (isinstance(message, str) or message is None):
        raise RuntimeError("Invalid exception metadata from isolated worker.")
    if not ok_value and (not isinstance(exception_type, str) or not isinstance(message, str)):
        raise RuntimeError("Invalid exception metadata from isolated worker.")

    return {
        "ok": ok_value,
        "result": result,
        "user_vars": user_vars,
        "output": output,
        "exception_type": exception_type,
        "message": message,
    }
