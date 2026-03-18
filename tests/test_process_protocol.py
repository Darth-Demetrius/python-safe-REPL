import pickle

import safe_repl.process_protocol as protocol
from safe_repl.process_protocol import open_command_payload


def test_coerce_worker_command_exec_normalizes_optional_fields() -> None:
    command = open_command_payload({"op": "exec", "code": "x = 1"})
    assert command == {"op": "exec", "code": "x = 1", "user_vars": {}}


def test_coerce_worker_command_reset_defaults_code_to_none() -> None:
    command = open_command_payload({"op": "reset", "user_vars": {"x": 2}})
    assert command == {"op": "reset", "code": None, "user_vars": {"x": 2}}


def test_coerce_worker_command_ignores_unknown_fields() -> None:
    command = open_command_payload({"op": "close", "extra": "ignored"})
    assert command == {"op": "close", "code": None, "user_vars": {}}


def test_coerce_worker_command_rejects_missing_or_invalid_op() -> None:
    assert open_command_payload({"code": "x = 1"}) is None
    assert open_command_payload({"op": 123}) is None
    assert open_command_payload({"op": "unknown"}) is None


def test_coerce_worker_command_rejects_invalid_optional_field_types() -> None:
    assert open_command_payload({"op": "exec", "code": None}) is None
    assert open_command_payload({"op": "reset", "user_vars": []}) is None


def test_open_command_payload_decodes_wrapped_user_vars() -> None:
    encoded_callable = protocol.encode_response_value(lambda value: value + 1)
    command = open_command_payload({"op": "reset", "user_vars": {"fn": encoded_callable}})

    assert command is not None
    if callable(command["user_vars"]["fn"]):
        assert command["user_vars"]["fn"](2) == 3
    else:
        assert isinstance(command["user_vars"]["fn"], str)


def test_encode_response_value_keeps_pickleable_values() -> None:
    assert protocol.encode_response_value({"x": 1}) == {"x": 1}


def test_encode_response_value_handles_unpickleable_objects() -> None:
    encoded = protocol.encode_response_value(lambda value: value + 1)
    # Whatever representation we choose, IPC still uses stdlib pickle.
    pickle.dumps(encoded)


def test_open_response_payload_decodes_wrapped_values() -> None:
    encoded_callable = protocol.encode_response_value(lambda value: value + 1)
    response = protocol.open_response_payload(
        {
            "ok": True,
            "result": encoded_callable,
            "user_vars": {"fn": encoded_callable},
            "output": None,
            "exception_type": None,
            "message": None,
        }
    )

    assert response["ok"] is True
    if callable(response["result"]):
        assert response["result"](2) == 3
        assert callable(response["user_vars"]["fn"])
        assert response["user_vars"]["fn"](2) == 3
    else:
        assert isinstance(response["result"], str)
        assert isinstance(response["user_vars"]["fn"], str)


def test_encode_user_vars_filters_unpickleable_values_when_cloudpickle_fails(
    monkeypatch,
) -> None:
    class _BrokenCloudpickle:
        @staticmethod
        def dumps(_value: object) -> bytes:
            raise RuntimeError("forced cloudpickle dump failure")

    monkeypatch.setattr(protocol, "cloudpickle", _BrokenCloudpickle)

    encoded = protocol.encode_user_vars_for_ipc({
        "x": 1,
        "fn": lambda value: value + 1,
    })

    assert encoded == {"x": 1}
