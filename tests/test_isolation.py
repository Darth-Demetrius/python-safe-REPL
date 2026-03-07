import math

import pytest

from safe_repl import PermissionLevel, Permissions, safe_exec_process_isolated, supports_process_isolation


pytestmark = pytest.mark.skipif(
    not supports_process_isolation(),
    reason="Process-isolated mode requires fork support.",
)


def _perms(level: PermissionLevel = PermissionLevel.LIMITED) -> Permissions:
    return Permissions(
        base_perms=level,
        imports={"math": math},
    )


def test_process_isolated_exec_returns_expression_result() -> None:
    user_vars: dict[str, object] = {}
    result = safe_exec_process_isolated("2 + 3 * 4", user_vars, perms=_perms())
    assert result == 14


def test_process_isolated_exec_syncs_user_vars() -> None:
    user_vars: dict[str, object] = {}
    assert safe_exec_process_isolated("x = 10", user_vars, perms=_perms()) is None
    assert safe_exec_process_isolated("x += 5", user_vars, perms=_perms()) is None
    assert safe_exec_process_isolated("x", user_vars, perms=_perms()) == 15


def test_process_isolated_exec_honors_timeout() -> None:
    user_vars: dict[str, object] = {}
    perms = _perms()
    perms.set_timeout_seconds(0.01)

    with pytest.raises(TimeoutError, match="Execution timed out"):
        safe_exec_process_isolated("while True:\n    pass", user_vars, perms=perms)


def test_process_isolated_exec_supports_imported_symbols() -> None:
    user_vars: dict[str, object] = {}
    assert safe_exec_process_isolated("math.sqrt(81)", user_vars, perms=_perms()) == 9.0
