# safe-repl

Safe Python REPL with tiered permission levels for restricted code execution.

## Install

From PyPI (when published):

```bash
pip install safe-repl
```

From source (local development):

```bash
pip install -e .
```

## Import in another project

```python
from safe_repl import PermissionLevel, Permissions, safe_exec, set_active_permissions

perms = Permissions(
    base_perms=PermissionLevel.LIMITED,
    allow_symbols=set(),
    block_symbols=set(),
    allow_nodes=set(),
    block_nodes=set(),
    imports={},
)
set_active_permissions(perms)

user_vars: dict[str, object] = {}
result = safe_exec("2 + 3 * 4", user_vars)
print(result)  # 14
```

## CLI usage

After install, run:

```bash
safe-repl
```

Examples:

```bash
safe-repl --level MINIMUM
safe-repl --level PERMISSIVE
safe-repl --import "json"
```

## Notes

- Distribution/package name: `safe-repl`
- Python import name: `safe_repl`
