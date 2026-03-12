from __future__ import annotations

import json

from safe_repl import PermissionLevel, Permissions, SafeSession


def test_module_alias_via_proxy_works_in_worker() -> None:
    # Use module-style import spec (as a list of spec strings)
    perms = Permissions(base_perms=PermissionLevel.LIMITED, imports=["json:dumps as dumps"])
    session = SafeSession(perms)

    # Should serialize into the spawn worker and execute with the imported function.
    result = session.exec("dumps({'x': 1})")
    assert result == json.dumps({"x": 1})
