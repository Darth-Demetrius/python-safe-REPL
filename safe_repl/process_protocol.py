"""IPC protocol primitives for process-isolated execution."""

from __future__ import annotations

import pickle
from typing import Final, Literal, TypedDict, cast

import cloudpickle


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


_CLOUDPICKLE_MARKER_KEY: Final[str] = "__safe_repl_cloudpickle__"
_CLOUDPICKLE_DATA_KEY: Final[str] = "data"


def _unpickleable_placeholder(value: object, *, reason: Exception) -> str:
    """Create stable fallback text for values that cannot be serialized."""
    return f"<unpickleable:{type(value).__name__}:{reason}>"


def _try_encode_value_for_ipc(value: object) -> tuple[bool, object]:
    """Attempt to encode one value for IPC, returning success + encoded payload."""
    try:
        pickle.dumps(value)
        return True, value
    except Exception as pickle_error:
        try:
            return True, {
                _CLOUDPICKLE_MARKER_KEY: True,
                _CLOUDPICKLE_DATA_KEY: cloudpickle.dumps(value),
            }
        except Exception as cloudpickle_error:
            return False, _unpickleable_placeholder(value, reason=cloudpickle_error or pickle_error)


def encode_response_value(value: object) -> object:
    """Return a transport-safe representation for worker response values."""
    _ok, encoded_value = _try_encode_value_for_ipc(value)
    return encoded_value


def decode_response_value(value: object) -> object:
    """Decode one transport-safe worker response value."""
    if not isinstance(value, dict) or value.get(_CLOUDPICKLE_MARKER_KEY) is not True:
        return value

    payload = value.get(_CLOUDPICKLE_DATA_KEY)
    if not isinstance(payload, bytes):
        return "<unpickleable:invalid-cloudpickle-payload>"

    try:
        return cast(object, cloudpickle.loads(payload))
    except Exception as error:
        return f"<unpickleable:cloudpickle-load-failed:{error}>"


def encode_user_vars_for_ipc(user_vars: dict[str, object]) -> dict[str, object]:
    """Encode user vars for IPC, dropping entries that cannot be serialized."""
    encoded_user_vars: dict[str, object] = {}
    for key, value in user_vars.items():
        ok, encoded_value = _try_encode_value_for_ipc(value)
        if ok:
            encoded_user_vars[key] = encoded_value
    return encoded_user_vars


def decode_user_vars_from_ipc(user_vars: dict[str, object]) -> dict[str, object]:
    """Decode user variable values received from IPC transport."""
    return {
        key: decode_response_value(value)
        for key, value in user_vars.items()
    }

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
        "user_vars": decode_user_vars_from_ipc(user_vars),
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

    decoded_result = decode_response_value(result)
    decoded_user_vars = decode_user_vars_from_ipc(user_vars)

    return {
        "ok": ok_value,
        "result": decoded_result,
        "user_vars": decoded_user_vars,
        "output": output,
        "exception_type": exception_type,
        "message": message,
    }
