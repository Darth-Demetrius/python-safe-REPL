import argparse

import pytest

import safe_repl.cli as cli


class _DummySession:
    def __init__(self) -> None:
        self.perms = type(
            "Perms",
            (),
            {
                "globals_dict": {"__builtins__": {"abs": abs, "min": min}},
                "allowed_nodes": {argparse.Namespace, type},
            },
        )()
        self.repl_calls: list[tuple[bool, bool | None]] = []

    def repl(self, *, show_details: bool = False, show_details_once: bool | None = None) -> None:
        self.repl_calls.append((show_details, show_details_once))


def test_cli_exits_with_code_1_for_invalid_node(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["safe-repl", "--allow-nodes", "DefinitelyNotAnAstNode"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == 1
    assert "Unknown node type" in capsys.readouterr().err


def test_cli_exits_with_code_1_for_invalid_import(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["safe-repl", "--import", "definitely_not_a_real_module_xyz"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == 1
    assert "Failed to import" in capsys.readouterr().err


def test_cli_passes_repl_detail_flags_to_session(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _DummySession()
    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(lambda cls, args: dummy))
    monkeypatch.setattr(
        "sys.argv",
        ["safe-repl", "--show-repl-details", "--no-show-repl-details-once"],
    )

    cli.main()

    assert dummy.repl_calls == [(True, False)]


def test_cli_passes_repl_detail_once_true(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _DummySession()
    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(lambda cls, args: dummy))
    monkeypatch.setattr(
        "sys.argv",
        ["safe-repl", "--show-repl-details", "--show-repl-details-once"],
    )

    cli.main()

    assert dummy.repl_calls == [(True, True)]


def test_cli_default_repl_detail_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _DummySession()
    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(lambda cls, args: dummy))
    monkeypatch.setattr("sys.argv", ["safe-repl"])

    cli.main()

    assert dummy.repl_calls == [(False, None)]


def test_cli_parses_execution_mode_process(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    dummy = _DummySession()

    def _from_cli_args(_cls: type[cli.SafeSession], args: argparse.Namespace) -> _DummySession:
        seen["execution_mode"] = args.execution_mode
        return dummy

    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(_from_cli_args))
    monkeypatch.setattr("sys.argv", ["safe-repl", "--execution-mode", "process"])

    cli.main()

    assert seen["execution_mode"] == "process"


def test_cli_list_functions_prints_names(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dummy = _DummySession()
    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(lambda cls, args: dummy))
    monkeypatch.setattr("sys.argv", ["safe-repl", "--list-functions"])

    cli.main()

    output = capsys.readouterr().out
    assert "Allowed functions:" in output
    assert "abs" in output
    assert "min" in output


def test_cli_list_nodes_prints_names(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dummy = _DummySession()
    monkeypatch.setattr(cli.SafeSession, "from_cli_args", classmethod(lambda cls, args: dummy))
    monkeypatch.setattr("sys.argv", ["safe-repl", "--list-nodes"])

    cli.main()

    output = capsys.readouterr().out
    assert "Allowed AST nodes:" in output
