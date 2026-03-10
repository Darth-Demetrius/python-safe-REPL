"""IPC protocol primitives for process-isolated execution."""

from __future__ import annotations

from typing import Final, Literal, TypedDict, cast


PERSISTENT_OP_EXEC: Final[str] = "exec"
PERSISTENT_OP_RESET: Final[str] = "reset"
PERSISTENT_OP_CLOSE: Final[str] = "close"
PERSISTENT_OPS: Final[set[str]] = {
    PERSISTENT_OP_EXEC,
    PERSISTENT_OP_RESET,
    PERSISTENT_OP_CLOSE,
}

PersistentOp = Literal["exec", "reset", "close"]


class WorkerSuccessResponse(TypedDict):
    """Serialized successful worker response payload."""

    ok: bool
    result: object | None
    user_vars: dict[str, object]


class WorkerErrorResponse(TypedDict):
    """Serialized worker exception metadata payload."""

    ok: bool
    exception_type: str
    message: str


class WorkerCommand(TypedDict):
    """Persistent worker command payload."""

    op: PersistentOp
    code: str | None
    user_vars: dict[str, object]


WorkerResponse = WorkerSuccessResponse | WorkerErrorResponse


def coerce_worker_command(payload: object) -> WorkerCommand | None:
    """Best-effort parse of inbound IPC payload into worker command schema."""
    if not isinstance(payload, dict):
        return None

    op: PersistentOp | None = None
    code: str | None = None
    user_vars: dict[str, object] = {}

    for key, value in payload.items():
        match key:
            case "op":
                if not isinstance(value, str) or value not in PERSISTENT_OPS:
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
