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
