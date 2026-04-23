# safe-repl

Safe Python REPL with tiered permission levels for restricted code execution.

## Overview

`safe-repl` provides a process-isolated Python REPL and API for executing untrusted code with configurable permission levels, import controls, and resource limits. All execution is process-isolated for safety. The public API is re-exported from focused internal modules.

The repository also includes `respy_repl`, a RestrictedPython-based variant designed for in-process execution scenarios (for example, async bot command handlers) where process-based isolation is not required.

For `respy_repl`, `SafeSession.exec(...)` and `SafeSession.async_exec(...)` return `(result, output)`, where `output` contains captured `print(...)` text from the executed snippet.
When you need rich outputs (for example matplotlib figures), use `SafeSession.exec_response(...)` or `SafeSession.async_exec_response(...)` and read `response.display_artifacts`.
When a `respy_repl` execution times out, `SafeSession.exec_response(...)` and `SafeSession.async_exec_response(...)` raise `ExecutionTimeoutError`, which includes partial `output` and `display_artifacts` generated before timeout.
Timeout exception messages include the effective timeout duration and a short code preview to make timeout failures easier to diagnose.
If an asyncio-level timeout fires before the in-thread timeout path completes, partial output may be unavailable.
When a `respy_repl` execution exceeds `memory_limit_bytes`, these response-oriented APIs raise `ExecutionMemoryLimitError`, which also includes partial `output` and `display_artifacts` generated before the memory-limit failure.

Example:

```python
from respy_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(Permissions(PermissionLevel.CONTROLLED, imports=["matplotlib.pyplot:*", "math:*"]))
response = session.exec_response(
  """
import matplotlib.pyplot as plt
plt.plot([1, 2, 3], [1, 4, 9])
plt.title('Demo Plot')
"""
)

for artifact in response.display_artifacts:
  if artifact.mime_type == "image/png":
    # send artifact.data to your client (Discord attachment, HTTP response, etc.)
    print(f"Captured PNG bytes: {len(artifact.data)}")
```

## Public API

- `PermissionLevel`, `Permissions`, `SafeSession`, `CommandRegistry`
- `safe_exec`, `validate_ast`, `main`
- `SafeReplImportError`, `SafeReplCliArgError`

Submodules (such as `safe_repl.policy`, `safe_repl.engine`, `safe_repl.validator`, etc.) are implementation details and may change.

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
from safe_repl import PermissionLevel, Permissions, SafeSession
import io
import contextlib

perms = Permissions(
    perm_level=PermissionLevel.CONTROLLED,
    imports=["numpy:sum", "math:sqrt as root"],
)

buf = io.StringIO()
session = SafeSession(perms)
with contextlib.redirect_stdout(buf):
    session.exec("x = sum(range(9))")
    session.exec("print(root(x))")
captured = buf.getvalue()

print(captured)  # '6.0'
```

## API Reference

- `PermissionLevel`: Enum of permission levels: `NONE`, `RESTRICTED`, `CONTROLLED`, `TRUSTED`. Invalid values warn and default to `NONE`.
- `Permissions`: Policy object for execution and REPL. Supports per-instance overrides for `timeout_seconds` and `memory_limit_bytes` via `set_limits()`.
- `SafeSession`: Stateful executor that keeps `user_vars` across calls. All execution is process-isolated.
- `CommandRegistry`: Decorator-based registry for custom REPL commands.
- `safe_exec`: Low-level stateless execution function.
- `validate_ast`: AST validation helper.
- `main`: CLI entrypoint.
- `SafeReplImportError`, `SafeReplCliArgError`: Exception types for import and CLI errors.

### Permission-level attribute access

- `RESTRICTED`: Attribute access is blocked.
- `CONTROLLED`: Attribute access is allowed on literals and imported symbols (e.g. `'abc'.split()`, or `np.sqrt(9)` after `numpy as np`).
- `TRUSTED`: Also allows attributes on in-scope user names. Private and dunder attributes are still blocked.

### Pickle round-trip and relaunch

```python
import pickle

from safe_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(
    Permissions(perm_level=PermissionLevel.CONTROLLED, imports=["math:sqrt as root"]),
    user_vars={"x": 25},
)

# Direct session pickle round-trip.
restored = pickle.loads(pickle.dumps(session))
print(restored.exec("root(x)"))  # 5.0

# Explicit relaunch payload workflow.
payload = session.to_relaunch_data()
blob = pickle.dumps(payload)
restored2 = SafeSession.from_relaunch_data(pickle.loads(blob))
print(restored2.exec("x + 1"))  # 26
```

## Quickstart

Install:

```bash
pip install safe-repl
# or for development:
pip install -e .
```

Run REPL:

```bash
safe-repl
# or
python -m safe_repl

# RestrictedPython variant
respy-repl
# or
python -m respy_repl
```

## Usage Example

```python
from safe_repl import PermissionLevel, Permissions, SafeSession
perms = Permissions(perm_level=PermissionLevel.CONTROLLED, imports=["math:*"])
session = SafeSession(perms)
print(session.exec("2 + 3 * 4"))  # 14
```

## CLI Arguments

- `--level LEVEL` — Permission level: RESTRICTED/1, CONTROLLED/2 (default), TRUSTED/3
- `--import SPEC` — Import module/spec (e.g. `math:*`, disables default if used)
- `--allow-functions ...` / `--block-functions ...` — Add/remove builtins
- `--allow-nodes ...` / `--block-nodes ...` — Add/remove AST nodes
- `--list-functions` / `--list-nodes` — Show allowed functions/nodes and exit

## REPL Commands

- `:commands` — List commands
- `:help <command>` — Show help
- `:level` — Print permission level
- `:functions` — Print available functions
- `:nodes` — Print allowed AST nodes
- `:imports` — Print imported symbols
- `:vars` — Print user variable names
- `:vars values` — Print user variables with values

## Embedding & Custom Commands

```python
from safe_repl import PermissionLevel, Permissions, SafeSession
from safe_repl.repl_command_registry import CommandRegistry
registry = CommandRegistry("!")
@registry.command("ping", help_text="Use '{0}ping' to print pong.")
def ping_command(_args, _session): print("pong")
session = SafeSession(Permissions(perm_level=PermissionLevel.CONTROLLED), command_registry=registry)
session.repl()
```

## Error Handling

| error_type   | Exception type      | Meaning                                      |
| ------------ | ------------------ | --------------------------------------------- |
| validation   | `ValueError`       | Input rejected by AST/safety validation       |
| timeout      | `TimeoutError`     | Execution exceeded configured timeout         |
| runtime      | `RuntimeError`     | Policy/runtime failure (e.g. memory exceeded) |
| user_code    | any other          | Exception raised by executed user code        |

## TODO

- Add ability to remove items from blocklists.
- Add ability to create custom REPL commands during runtime via session API.
- Use `colorama` or similar for colored CLI output.
- Graceful shutdown handling for subprocess workers (for example on `KeyboardInterrupt`).

## Sandbox upgrade paths

Current process isolation improves containment, but stronger boundaries can be added in layers.
The most promising near-term options are Linux namespaces and microVM execution.

- Replace denylist-heavy `TRUSTED` policy behavior with a capability/profile-based model.
- Linux namespaces (recommended next step)
  - Run workers in isolated `user`, `pid`, `mount`, and `net` namespaces.
  - Combine with `no_new_privs`, read-only mounts, and restricted `/tmp`.
  - Pair with seccomp and cgroup limits for syscall and resource control.
- MicroVMs (strongest practical boundary)
  - Run each execution in a minimal VM (for example Firecracker-class isolation).
  - Provides stronger kernel boundary than process/container isolation.
  - Higher startup/runtime overhead, but best fit for multi-tenant untrusted code.
- Optional middle layer: rootless containers
  - Easier operationally than microVMs, stronger than plain processes.
  - Still shares host kernel, so boundary is weaker than microVM/VM isolation.

## Notes

- Distribution/package name: `safe-repl`
- Python import name: `safe_repl`
- See `CHANGELOG.md` for recent API and behavior changes.
