"""IPC protocol primitives for process-isolated execution."""

from __future__ import annotations

from typing import Final, TypedDict


PERSISTENT_OP_EXEC: Final[str] = "exec"
PERSISTENT_OP_RESET: Final[str] = "reset"
PERSISTENT_OP_CLOSE: Final[str] = "close"
PERSISTENT_OPS: Final[set[str]] = {
    PERSISTENT_OP_EXEC,
    PERSISTENT_OP_RESET,
    PERSISTENT_OP_CLOSE,
}


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


class WorkerCommand(TypedDict, total=False):
    """Persistent worker command payload."""

    op: str
    code: str
    user_vars: dict[str, object]


WorkerResponse = WorkerSuccessResponse | WorkerErrorResponse


def _coerce_optional_field[
    TValue
](payload: dict[str, object], key: str, expected_type: type[TValue]) -> TValue | None:
    """Read optional field and validate exact runtime type when present."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, expected_type):
        return None
    return value


def coerce_worker_command(payload: object) -> WorkerCommand | None:
    """Best-effort parse of inbound IPC payload into worker command schema."""
    if not isinstance(payload, dict):
        return None

    command: WorkerCommand = {}

    op = _coerce_optional_field(payload, "op", str)
    if op is None and "op" in payload:
        return None
    if op is not None:
        command["op"] = op

    code = _coerce_optional_field(payload, "code", str)
    if code is None and "code" in payload:
        return None
    if code is not None:
        command["code"] = code

    user_vars = _coerce_optional_field(payload, "user_vars", dict)
    if user_vars is None and "user_vars" in payload:
        return None
    if user_vars is not None:
        command["user_vars"] = user_vars

    return command
