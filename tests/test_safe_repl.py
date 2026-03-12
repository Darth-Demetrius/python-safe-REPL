import argparse
import math
from typing import TypedDict

import pytest

from safe_repl.imports import (
    SafeReplCliArgError,
    SafeReplImportError,
    normalize_validate_import,
    validate_cli_args,
)
from safe_repl.repl_command_registry import CommandRegistry
from safe_repl import (
    PermissionLevel,
    Permissions,
    repl as run_repl,
    SafeReplCliArgError,
    SafeReplImportError,
    SafeSession,
    safe_exec,
)


def activate(level: PermissionLevel, imports: list[str] | None = None) -> Permissions:
    perms = Permissions(
        base_perms=level,
        allow_symbols=set(),
        block_symbols=set(),
        allow_nodes=set(),
        block_nodes=set(),
        imports=imports or [],
    )
    return perms


def run_limited(code: str, variables: dict[str, object]) -> object | None:
    perms = activate(PermissionLevel.LIMITED, ["math:*"])
    session = SafeSession(perms=perms, user_vars=variables)
    try:
        return session.exec(code)
    finally:
        if session.user_vars is not variables:
            variables.clear()
            variables.update(session.user_vars)
        session.close_worker_session()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("(2 < 3) and (4 != 5)", True),
        ("abs(-3)", 3),
        ("max(1, 5, 2)", 5),
        ("round(3.14159, 2)", 3.14),
        # star import (math:*) expands all public names as direct calls
        ("sqrt(16)", 4.0),
        ("floor(3.7)", 3),
    ],
)
def test_limited_allows_core_operations(code: str, expected: object) -> None:
    variables: dict[str, object] = {}
    assert run_limited(code, variables) == expected


def test_assignment_persists_between_calls() -> None:
    variables: dict[str, object] = {}
    assert run_limited("x = 5", variables) is None
    assert run_limited("x += 2", variables) is None
    assert run_limited("x", variables) == 7


def test_safe_session_exec_persists_state() -> None:
    perms = activate(PermissionLevel.LIMITED)
    session = SafeSession(perms)

    assert session.exec("x = 10") is None
    assert session.exec("x += 5") is None
    assert session.exec("x") == 15


def test_safe_session_reset_clears_user_vars() -> None:
    perms = activate(PermissionLevel.LIMITED)
    session = SafeSession(perms)

    session.exec("x = 10")
    session.reset()
    with pytest.raises(NameError, match="x"):
        session.exec("x")


def test_safe_session_constructor_defaults() -> None:
    session = SafeSession(Permissions(base_perms=PermissionLevel.MINIMUM))
    assert session.perms.level == PermissionLevel.MINIMUM
    assert session.user_vars == {}


def test_safe_session_constructor_with_imports() -> None:
    session = SafeSession(Permissions(base_perms=PermissionLevel.LIMITED, imports=["math:sqrt"]))
    assert session.exec("sqrt(9)") == 3.0


def test_safe_session_from_cli_args_uses_default_math_imports() -> None:
    args = argparse.Namespace(
        level="LIMITED",
        imports=None,
        allow_functions=None,
        block_functions=None,
        allow_nodes=None,
        block_nodes=None,
        list_functions=False,
        list_nodes=False,
    )
    session = SafeSession.from_cli_args(args)
    assert session.exec("sqrt(16)") == 4.0


def test_safe_session_from_cli_args_with_explicit_import() -> None:
    args = argparse.Namespace(
        level="LIMITED",
        imports=["json:dumps as dumps"],
        allow_functions=None,
        block_functions=None,
        allow_nodes=None,
        block_nodes=None,
        list_functions=False,
        list_nodes=False,
    )
    session = SafeSession.from_cli_args(args)
    assert session.exec("dumps({'x': 1})") == '{"x": 1}'


def test_safe_session_from_cli_args_empty_import_disables_default_math() -> None:
    args = argparse.Namespace(
        level="LIMITED",
        imports=[""],
        allow_functions=None,
        block_functions=None,
        allow_nodes=None,
        block_nodes=None,
        list_functions=False,
        list_nodes=False,
    )
    session = SafeSession.from_cli_args(args)
    with pytest.raises(ValueError, match="Function 'sqrt' is not allowed"):
        session.exec("sqrt(16)")


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("open('x.txt')", "is not allowed"),
        ("math._floor(3.7)", "Private methods are not allowed"),
        ("'abc'.__class__", "Private attributes are not allowed"),
    ],
)
def test_limited_blocks_unsafe_calls_and_attributes(code: str, error: str) -> None:
    variables: dict[str, object] = {}
    with pytest.raises(ValueError, match=error):
        run_limited(code, variables)


def test_star_import_does_not_put_module_in_scope() -> None:
    # math:* expands public names directly; the module object itself is not
    # injected, so math.sqrt-style attribute access must be blocked.
    variables: dict[str, object] = {}
    with pytest.raises(ValueError, match="Attribute access not allowed"):
        run_limited("math.sqrt(16)", variables)


def test_limited_allows_unpacking_targets() -> None:
    variables: dict[str, object] = {}
    assert run_limited("a, b = (1, 2)", variables) is None
    assert run_limited("a", variables) == 1
    assert run_limited("b", variables) == 2


def test_limited_allows_subscript_and_slice_assignment_for_existing_variable() -> None:
    variables: dict[str, object] = {}
    assert run_limited("arr = [1, 2, 3]", variables) is None
    assert run_limited("arr[0] = 9", variables) is None
    assert run_limited("arr[1:3] = [7, 8]", variables) is None
    assert run_limited("arr", variables) == [9, 7, 8]


def test_limited_blocks_subscript_assignment_for_unknown_variable() -> None:
    variables: dict[str, object] = {}
    with pytest.raises(
        ValueError,
        match="Subscript/slice assignment is only allowed on existing user variables",
    ):
        run_limited("arr[0] = 1", variables)


def test_minimum_blocks_all_attribute_access() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.MINIMUM)
    with pytest.raises(ValueError, match="Attribute access not allowed"):
        safe_exec("'hello'.upper()", variables, perms=perms)


def test_minimum_blocks_unpacking_but_allows_simple_assignment() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.MINIMUM)
    with pytest.raises(ValueError, match="Unpacking assignment is not allowed"):
        safe_exec("a, b = 1, 2", variables, perms=perms)

    assert safe_exec("x = 5", variables, perms=perms) is None
    assert variables["x"] == 5


def test_limited_enforces_timeout() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.LIMITED)
    perms.set_limits(timeout_seconds=0.01)
    assert perms.timeout_seconds == 1
    with pytest.raises(TimeoutError, match="Execution timed out"):
        safe_exec("while True:\n    pass", variables, perms=perms)


def test_limited_enforces_memory_limit() -> None:
    perms = activate(PermissionLevel.LIMITED)
    perms.set_limits(memory_limit_bytes=64 * 1024)
    assert perms.memory_limit_bytes == 64 * 1024
    session = SafeSession(perms)
    try:
        with pytest.raises((MemoryError, RuntimeError)):
            session.exec("x = list(range(200000))")
    finally:
        session.close_worker_session()


def test_limited_allows_attributes_on_literals() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.LIMITED)
    assert safe_exec("'hello'.upper()", variables, perms=perms) == "HELLO"
    assert safe_exec("[1, 2, 3].count(2)", variables, perms=perms) == 1


def test_limited_blocks_attributes_on_user_variables() -> None:
    variables: dict[str, object] = {"msg": "hello"}
    perms = activate(PermissionLevel.LIMITED)
    with pytest.raises(ValueError, match="Attribute access not allowed"):
        safe_exec("msg.upper()", variables, perms=perms)


def test_permissive_allows_attributes_on_user_variables() -> None:
    variables: dict[str, object] = {"msg": "hello"}
    perms = activate(PermissionLevel.PERMISSIVE)
    assert safe_exec("msg.upper()", variables, perms=perms) == "HELLO"


def test_permissive_allows_attributes_on_locals_defined_in_snippet() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.PERMISSIVE)
    assert safe_exec("msg = 'hello'", variables, perms=perms) is None
    assert safe_exec("msg.upper()", variables, perms=perms) == "HELLO"


def test_limited_allows_function_definition() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.LIMITED)
    safe_exec("def add(a, b):\n    return a + b", variables, perms=perms)
    assert safe_exec("add(2, 3)", variables, perms=perms) == 5


@pytest.mark.parametrize(
    "code",
    [
        "class A:\n    pass",
        "try:\n    x = 1\nexcept Exception:\n    x = 2",
    ],
)
def test_limited_blocks_class_and_exception_handling(code: str) -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.LIMITED)
    with pytest.raises(ValueError, match="Unsupported syntax"):
        safe_exec(code, variables, perms=perms)


def test_permissive_allows_class_and_try() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.PERMISSIVE)
    safe_exec("class A:\n    pass\n\ntry:\n    y = 1\nexcept Exception:\n    y = 2", variables, perms=perms)
    assert safe_exec("y", variables, perms=perms) == 1
    assert "A" in variables


def test_permissive_blocks_imports() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.PERMISSIVE)
    with pytest.raises(ValueError, match="Unsupported syntax"):
        safe_exec("import math", variables, perms=perms)


def test_permissive_allows_global_and_nonlocal() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.PERMISSIVE)
    safe_exec(
        "x = 0\ndef outer():\n    y = 1\n    def inner():\n        nonlocal y\n        global x\n        y = 2\n        x = 3\n    inner()\n    return y",
        variables,
        perms=perms,
    )
    assert safe_exec("outer()", variables, perms=perms) == 2
    assert perms.globals_dict["x"] == 3


def test_unsupervised_allows_imports_and_from_import() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.UNSUPERVISED)
    safe_exec("import math", variables, perms=perms)
    safe_exec("from math import sqrt", variables, perms=perms)
    assert safe_exec("math.sqrt(9)", variables, perms=perms) == 3.0
    assert safe_exec("sqrt(16)", variables, perms=perms) == 4


def test_unsupervised_still_blocks_eval() -> None:
    variables: dict[str, object] = {}
    perms = activate(PermissionLevel.UNSUPERVISED)
    with pytest.raises(ValueError, match="is not allowed"):
        safe_exec("eval('2 + 2')", variables, perms=perms)


def test_permission_level_invalid_value_warns_and_defaults_to_minimum() -> None:
    with pytest.warns(UserWarning, match="Invalid permission level"):
        level = PermissionLevel("not-a-level")
    assert level == PermissionLevel.MINIMUM


def test_parse_import_spec_raises_safe_repl_import_error() -> None:
    with pytest.raises(SafeReplImportError, match="Cannot import module"):
        normalize_validate_import("definitely_not_a_real_module_xyz")


def test_parse_import_spec_reports_missing_symbol() -> None:
    with pytest.raises(SafeReplImportError, match="Cannot import attribute"):
        normalize_validate_import("math:definitely_not_a_real_symbol_xyz")


@pytest.mark.parametrize(
    "spec",
    [
        "math as ",
        "math:sin cos",
        "math:sin as s in",
    ],
)
def test_parse_import_spec_rejects_invalid_symbol_specs(spec: str) -> None:
    with pytest.raises(SafeReplImportError, match="Invalid import symbol spec"):
        normalize_validate_import(spec)


def test_validate_cli_args_raises_safe_repl_cli_arg_error_for_unknown_node() -> None:
    args = argparse.Namespace(allow_nodes=["DefinitelyNotAnAstNode"], block_nodes=None)
    with pytest.raises(SafeReplCliArgError, match="Unknown node type"):
        validate_cli_args(args)


def test_typed_exceptions_reexported_from_top_level() -> None:
    assert SafeReplImportError.__name__ == "SafeReplImportError"
    assert SafeReplCliArgError.__name__ == "SafeReplCliArgError"


def test_print_user_vars_prints_names_only(capsys: pytest.CaptureFixture[str]) -> None:
    session = SafeSession(activate(PermissionLevel.LIMITED), user_vars={"b": 2, "a": 1})
    session.print_user_vars(include_values=False)

    output = capsys.readouterr().out
    assert output == "  User vars: a, b\n"


def test_print_user_vars_prints_values(capsys: pytest.CaptureFixture[str]) -> None:
    session = SafeSession(activate(PermissionLevel.LIMITED), user_vars={"b": 2, "a": 1})
    session.print_user_vars()

    output = capsys.readouterr().out
    assert output == "  User vars: \n    a=1\n    b=2\n"


@pytest.mark.parametrize("run_count", [1, 2])
def test_repl_startup_prints_basic_intro_and_help_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    run_count: int,
) -> None:
    session = SafeSession(activate(PermissionLevel.LIMITED))
    monkeypatch.setattr("builtins.input", lambda _prompt: "quit")

    for _ in range(run_count):
        session.repl()
        output = capsys.readouterr().out
        assert "Type 'quit' or 'exit' to exit." in output
        assert "Use ':help <command>' to show help for a command" in output
        assert "Bye" in output


@pytest.mark.parametrize(
    ("command", "expected_fragments"),
    [
        (":vars values", ["User vars:", "a=1", "b=2"]),
        (":vars", ["User vars: a, b"]),
    ],
)
def test_repl_vars_command_prints_expected_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected_fragments: list[str],
) -> None:
    inputs = iter([command, "quit"])
    session = SafeSession(activate(PermissionLevel.LIMITED), user_vars={"a": 1, "b": 2})
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    session.repl()
    output = capsys.readouterr().out

    for expected_fragment in expected_fragments:
        assert expected_fragment in output


@pytest.mark.parametrize(
    ("command_char", "command_name", "help_text"),
    [
        (":", "ping", "Use ':ping' to print pong."),
        ("!", "ping", "Use '{}ping' to print pong."),
    ],
)
def test_repl_runs_injected_custom_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_char: str,
    command_name: str,
    help_text: str,
) -> None:
    registry = CommandRegistry()

    @registry.command(command_name, help_text=help_text)
    def _ping_command(_args: str, _session: SafeSession) -> None:
        print("pong")

    inputs = iter([f"{command_char}{command_name}", "quit"])
    session = SafeSession(
        activate(PermissionLevel.LIMITED),
        repl_commands=registry,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    session.repl(command_char=command_char)
    output = capsys.readouterr().out

    assert "pong" in output


def test_show_help_for_specific_command_uses_current_prefix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CommandRegistry()

    @registry.command("ping", help_text="Use '{}ping' to print pong.")
    def _ping_command(_args: str, _session: SafeSession) -> None:
        print("pong")

    session = SafeSession(
        activate(PermissionLevel.LIMITED),
        repl_commands=registry,
        command_char="!",
    )
    session.command_registry.show_help("ping", cmd_char=session.command_char)

    output = capsys.readouterr().out
    assert output == "Use '!ping' to print pong.\n"


def test_show_help_includes_args_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CommandRegistry()

    @registry.command(
        "ping",
        help_text="Use '{0}ping <name>' to print pong.",
        args_desc="<name>: label to include in pong output.",
    )
    def _ping_command(_args: str, _session: SafeSession) -> None:
        print("pong")

    session = SafeSession(
        activate(PermissionLevel.LIMITED),
        repl_commands=registry,
        command_char="!",
    )
    session.command_registry.show_help("ping", cmd_char=session.command_char)

    output = capsys.readouterr().out
    assert output == "Use '!ping <name>' to print pong.\nArgs: <name>: label to include in pong output.\n"


def test_show_help_falls_back_when_help_template_is_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CommandRegistry()

    @registry.command("ping", help_text="Use '{1}ping' to print pong.")
    def _ping_command(_args: str, _session: SafeSession) -> None:
        print("pong")

    session = SafeSession(
        activate(PermissionLevel.LIMITED),
        repl_commands=registry,
        command_char="!",
    )
    session.command_registry.show_help("ping", cmd_char=session.command_char)

    output = capsys.readouterr().out
    assert output == "Use '{1}ping' to print pong.\n"


def test_builtin_inspection_commands_print_session_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SafeSession(activate(PermissionLevel.LIMITED, imports=["math:*"]))

    assert session.command_registry.dispatch("level", session=session) is True
    assert session.command_registry.dispatch("functions", session=session) is True
    assert session.command_registry.dispatch("nodes", session=session) is True
    assert session.command_registry.dispatch("imports", session=session) is True

    output = capsys.readouterr().out
    assert "Permission level: limited" in output
    assert "Builtins:" in output
    assert "Nodes:" in output
    assert "Imports:" in output


def test_builtin_imports_command_prints_none_when_no_imports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SafeSession(activate(PermissionLevel.LIMITED))

    assert session.command_registry.dispatch("imports", session=session) is True

    output = capsys.readouterr().out
    assert output == "  Imports: (none)\n"


def test_repl_persists_custom_command_char_between_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CommandRegistry()

    @registry.command("ping", help_text="Use '{}ping' to print pong.")
    def _ping_command(_args: str, _session: SafeSession) -> None:
        print("pong")

    session = SafeSession(activate(PermissionLevel.LIMITED), repl_commands=registry)

    first_inputs = iter(["!ping", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(first_inputs))
    session.repl(command_char="!")
    first_output = capsys.readouterr().out

    second_inputs = iter(["!ping", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(second_inputs))
    session.repl()
    second_output = capsys.readouterr().out

    assert "pong" in first_output
    assert "pong" in second_output


def test_repl_uses_worker_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Tracker(TypedDict):
        opened: int
        closed: int
        calls: list[str]

    tracker: _Tracker = {"opened": 0, "closed": 0, "calls": []}

    class _FakeWorkerSession:
        def __init__(self, *, perms: Permissions, user_vars: dict[str, object]) -> None:
            self._user_vars = user_vars

        def open(self) -> None:
            tracker["opened"] += 1

        def close(self) -> None:
            tracker["closed"] += 1

        def exec(self, code: str) -> object | None:
            tracker["calls"].append(code)
            return 42

        def reset(self) -> None:
            self._user_vars.clear()

    inputs = iter(["2 + 2", "quit"])
    session = SafeSession(activate(PermissionLevel.LIMITED))
    monkeypatch.setattr("safe_repl.session.WorkerSession", _FakeWorkerSession)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    session.repl()
    output = capsys.readouterr().out

    assert tracker["opened"] == 1
    assert tracker["closed"] == 1
    assert tracker["calls"] == ["2 + 2"]
    assert "42" in output


def test_repl_does_not_use_safe_session_exec(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FakeWorkerSession:
        def __init__(self, *, perms: Permissions, user_vars: dict[str, object]) -> None:
            self._user_vars = user_vars

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def exec(self, code: str) -> object | None:
            return 7

        def reset(self) -> None:
            self._user_vars.clear()

    inputs = iter(["3 + 4", "quit"])
    session = SafeSession(activate(PermissionLevel.LIMITED))
    monkeypatch.setattr("safe_repl.session.WorkerSession", _FakeWorkerSession)
    monkeypatch.setattr(
        SafeSession,
        "exec",
        lambda self, code: (_ for _ in ()).throw(AssertionError("SafeSession.exec should not be used by repl")),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    session.repl()
    output = capsys.readouterr().out

    assert "7" in output


def test_module_repl_uses_worker_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracker: dict[str, object] = {"calls": []}

    class _FakeWorkerSession:
        def __init__(self, *, perms: Permissions, user_vars: dict[str, object]) -> None:
            self._user_vars = user_vars

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def exec(self, code: str) -> object | None:
            cast_calls = tracker["calls"]
            assert isinstance(cast_calls, list)
            cast_calls.append(code)
            return 123

        def reset(self) -> None:
            self._user_vars.clear()

    monkeypatch.setattr("safe_repl.session.WorkerSession", _FakeWorkerSession)
    inputs = iter(["2 + 2", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    run_repl(perms=activate(PermissionLevel.LIMITED))
    output = capsys.readouterr().out

    assert tracker["calls"] == ["2 + 2"]
    assert "123" in output


def test_reset_propagates_to_open_worker_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = {"reset": 0}

    class _FakeWorkerSession:
        def __init__(self, *, perms: Permissions, user_vars: dict[str, object]) -> None:
            self._user_vars = user_vars

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def exec(self, code: str) -> object | None:
            return None

        def reset(self) -> None:
            tracker["reset"] += 1
            self._user_vars.clear()

    session = SafeSession(activate(PermissionLevel.LIMITED), user_vars={"x": 1})
    monkeypatch.setattr("safe_repl.session.WorkerSession", _FakeWorkerSession)
    session.open_worker_session()

    session.reset()

    assert tracker["reset"] == 1
    assert session.user_vars == {}
