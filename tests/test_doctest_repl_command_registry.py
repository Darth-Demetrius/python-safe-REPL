import doctest

import safe_repl.repl_command_registry as repl_command_registry


def test_repl_command_registry_module_doctest() -> None:
    failures, _ = doctest.testmod(repl_command_registry)
    assert failures == 0
